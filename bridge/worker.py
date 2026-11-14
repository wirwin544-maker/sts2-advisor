"""Async Claude worker for strategic decisions, build suggestions and combat.

Latest state signature wins. In combat all returned plans are checked against
state captured at request time, and stale results are discarded.
"""
from __future__ import annotations

import logging
import re
import threading

from . import combat, thesis as thesis_mod, util
from .run_memory import atomic_json, candidates


class AdviceWorker:
    def __init__(self, model_client, thesis_store: thesis_mod.ThesisStore,
                 advice_file: str, logger: logging.Logger, journal=None,
                 combat_file: str = 'runtime/combat_plan.json', pause_gate=None):
        self.model_client = model_client
        self.thesis = thesis_store
        self.advice_path = util.resolve(advice_file)
        self.advice_path.parent.mkdir(parents=True, exist_ok=True)
        self.combat_path = util.resolve(combat_file)
        self.journal = journal
        self.pause_gate = pause_gate
        self.logger = logger
        self._cv = threading.Condition()
        self._job = None
        self._latest_sig = None
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def invalidate(self, signature: str | None) -> None:
        """Invalidate pending result even when no new Claude job has fired."""
        with self._cv:
            if self._latest_sig != signature:
                self._latest_sig = signature
                self._job = None

    def request(self, signature: str, payload: str, alias: str, kind: str,
                run_id: str | None = None, state: dict | None = None,
                build_options: list[str] | None = None) -> bool:
        # Do not even enqueue a request if the player paused that advice type.
        # The state can change after the bridge's last poll, so enforce it here.
        if self.pause_gate is not None and not self.pause_gate.allows(kind):
            self.invalidate(None)
            return False
        with self._cv:
            self._job = (signature, payload, alias, kind, run_id, state, build_options)
            self._latest_sig = signature
            self._cv.notify()
        if kind not in ('combat', 'build'):
            self._write(f"[ {kind} ]  thinking…")
        return True

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._job is None and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                signature, payload, alias, kind, run_id, state, choices = self._job
                self._job = None
            # A paused fight must not start a queued model request, even if
            # the bridge had already submitted the job before the pause click.
            if self.pause_gate is not None and not self.pause_gate.allows(kind):
                self.invalidate(None)
                continue
            mode = kind if kind in ('combat', 'build') else 'strategy'
            try:
                response = self.model_client.advise(payload, alias, mode=mode)
            except Exception as exc:
                self.logger.exception('model call failed')
                if self._is_current(signature, run_id):
                    if kind == 'combat':
                        atomic_json(self.combat_path, {
                            'signature': signature, 'run_id': run_id,
                            'status': 'unavailable', 'steps': [],
                            'warning': f'Model call failed: {str(exc)[:160]}'})
                    elif kind == 'build' and self.journal:
                        options = choices or []
                        self.journal.record_suggestion({
                            'run_id': run_id, 'request_id': signature.split(':')[-1],
                            'status': 'error', 'build': '',
                            'why': f'Claude could not provide a recommendation: {str(exc)[:120]}'})
                    else:
                        self._write(f"[ {kind} ] advisor error: {str(exc)[:160]}")
                continue
            if not self._is_current(signature, run_id):
                self.logger.info('Dropping stale %s advice for %s', kind, signature)
                continue
            if self.journal:
                # Complete local transcript, even though only a bounded memory
                # summary is replayed to Claude. Each run has its own JSONL.
                self.journal.append('exchange', screen=kind, model=alias,
                                    request=payload, response=response)
            if kind == 'combat':
                plan = combat.validate_response(response, state or {}, signature, run_id)
                atomic_json(self.combat_path, plan)
                if self.journal:
                    action_names = [s.get('name') or s.get('action') for s in plan.get('steps', [])]
                    self.journal.append('combat_advice', round=(state.get('battle') or {}).get('round'),
                                        summary=' > '.join(map(str, action_names)),
                                        warning=plan.get('warning', ''))
                self.logger.info('Combat plan %s (%d steps)', plan['status'], len(plan['steps']))
                continue
            if kind == 'build':
                options = choices or []
                m = re.search(r'^PICK:\s*(.+?)\s*$', response, re.M | re.I)
                raw = m.group(1).strip() if m else ''
                selected = next((o for o in options if o.casefold() == raw.casefold()), '')
                # Be conservative if Claude invents a build rather than selecting one.
                if not selected:
                    self.logger.warning('Build suggestion did not match an available option: %r', raw)
                    selected = options[0] if options else ''
                why = re.search(r'^WHY:\s*(.+?)\s*$', response, re.M | re.I)
                result = {'run_id': run_id, 'request_id': signature.split(':')[-1],
                          'status': 'ready', 'build': selected,
                          'why': why.group(1).strip() if why else
                          'No verified explanation returned.'}
                if self.journal:
                    self.journal.record_suggestion(result)
                self.logger.info('Recommended starting build: %s', selected)
                continue
            advice, locked, plan = thesis_mod.parse_response(response)
            self.thesis.update(locked, plan)
            self.thesis.save()
            display = advice if advice else response.strip()
            self._write(f"[ {kind} ]\n{display}")
            if self.journal:
                self.journal.append('decision', screen=kind, signature=signature,
                                    model=alias, advice=display[:1500],
                                    plan=plan[:800], locked=locked[:30])
            self.logger.info('Advice committed for %s (%s)', kind, alias)

    def _is_current(self, signature: str, run_id: str | None) -> bool:
        # Reject delayed model results as soon as Pause All / Pause Battle is
        # enabled. This also protects the brief interval before the next poll.
        with self._cv:
            latest = (self._latest_sig == signature and
                      (not self.journal or self.journal.run_id == run_id))
        if not latest:
            return False
        # Only combat advice is battle-gated; noncombat jobs remain allowed.
        kind = 'combat' if signature.startswith('combat:') else 'strategy'
        return self.pause_gate is None or self.pause_gate.allows(kind)

    def _write(self, value: str) -> None:
        try:
            self.advice_path.write_text(value + '\n', encoding='utf-8')
        except OSError:
            self.logger.exception('failed writing advice file')
