"""Run-scoped persistent journal and build preferences.

A full JSONL transcript is kept locally. Only bounded recent entries and the
thesis are sent back to Claude, avoiding unbounded token consumption. This is
logical run continuity, not a promise of a single native Claude chat session.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from . import util

BUILDS = {
    "ironclad": ["Flexible / adapt to rewards", "Strength scaling", "Exhaust synergy", "Self-damage payoff", "Block / Barricade"],
    "silent": ["Flexible / adapt to rewards", "Poison", "Shivs", "Discard / Sly"],
    "defect": ["Flexible / adapt to rewards", "Frost / Focus", "Lightning / Orbs", "Dark orbs", "Glass / Multi-target"],
    "regent": ["Flexible / adapt to rewards", "Stars", "Forge / Sovereign Blade"],
    "necrobinder": ["Flexible / adapt to rewards", "Osty / Summon", "Doom", "Souls / HP-cost"],
}


def character_name(state: dict) -> str:
    raw = (state.get('player') or {}).get('character') or (state.get('run') or {}).get('character') or 'Unknown'
    return str(raw).replace('The ', '').strip()


def candidates(character: str) -> list[str]:
    return BUILDS.get(character.lower(), ["Flexible / adapt to rewards"])


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


class RunJournal:
    def __init__(self, runtime_dir: str):
        self.root = util.resolve(runtime_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.active_path = self.root / 'active_run.json'
        self.status_path = self.root / 'run_status.json'
        self.choice_path = self.root / 'build_choice.json'
        self.request_path = self.root / 'build_request.json'
        self.suggestion_path = self.root / 'build_suggestion.json'
        self.active = read_json(self.active_path)
        self._last_event_key = None

    @property
    def run_id(self) -> str | None:
        return self.active.get('run_id')

    @property
    def build(self) -> str:
        return self.active.get('build') or ''

    @property
    def transcript_path(self) -> Path | None:
        if not self.run_id:
            return None
        return self.root / 'runs' / self.run_id / 'transcript.jsonl'

    def _save_active(self) -> None:
        atomic_json(self.active_path, self.active)
        self._save_status()

    def _save_status(self) -> None:
        if not self.run_id:
            return
        atomic_json(self.status_path, {
            'run_id': self.run_id, 'character': self.active.get('character'),
            'ascension': self.active.get('ascension'), 'act': self.active.get('act'),
            'floor': self.active.get('floor'), 'build': self.build,
            'build_options': candidates(self.active.get('character', '')),
            'created_at': self.active.get('created_at'),
            'status': self.active.get('status', 'active'),
        })

    def append(self, kind: str, **values) -> None:
        path = self.transcript_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'time': time.time(), 'kind': kind, **values}, ensure_ascii=False) + '\n')

    def observe(self, state: dict) -> bool:
        """Update run identity. True only when a real new run is inferred.

        A resumed advisor at floor 1 does not erase an existing floor-1 run.
        No run-id is exposed by early STS2MCP builds, so restarts/new runs at
        exactly the same floor and character remain inherently ambiguous.
        """
        if state.get('state_type') == 'game_over':
            return False
        run = state.get('run') or {}
        floor = run.get('floor')
        act = run.get('act')
        if not isinstance(floor, int):
            return False
        char = character_name(state)
        asc = run.get('ascension')
        prev = self.active
        new = not prev.get('run_id') or prev.get('status') == 'ended'
        if prev and not new:
            if prev.get('character') != char or prev.get('ascension') != asc:
                new = True
            elif (floor <= 1 and act == 1 and isinstance(prev.get('floor'), int)
                  and prev['floor'] > floor):
                new = True
            elif (isinstance(prev.get('act'), int) and isinstance(act, int)
                  and prev['act'] > act and act == 1):
                new = True
        if new:
            self.active = {
                'run_id': str(uuid.uuid4()), 'character': char, 'ascension': asc,
                'floor': floor, 'act': act, 'status': 'active',
                'build': '', 'created_at': time.time(),
            }
            self._last_event_key = None
            self._save_active()
            self.append('run_started', character=char, ascension=asc, act=act, floor=floor)
            # Prevent a previous run's build preference from being applied.
            for stale in (self.choice_path, self.request_path, self.suggestion_path):
                try:
                    stale.unlink()
                except FileNotFoundError:
                    pass
            return True

        changed = (prev.get('floor') != floor or prev.get('act') != act)
        if changed:
            self.active['floor'], self.active['act'] = floor, act
            self._save_active()
            self.append('floor', act=act, floor=floor,
                        hp=(state.get('player') or {}).get('hp'))
        return False

    def finish(self, outcome: str) -> None:
        if self.active and self.active.get('status') != 'ended':
            self.append('run_finished', outcome=outcome)
            self.active['status'] = 'ended'
            self._save_active()

    def accept_build_choice(self) -> bool:
        choice = read_json(self.choice_path)
        if choice.get('run_id') != self.run_id:
            return False
        selection = str(choice.get('build', ''))
        if selection not in candidates(self.active.get('character', '')):
            return False
        if selection == self.build:
            return False
        self.active['build'] = selection
        self._save_active()
        self.append('build_selected', build=selection)
        return True

    def build_request(self) -> dict | None:
        req = read_json(self.request_path)
        if req.get('run_id') != self.run_id or not req.get('request_id'):
            return None
        if req.get('request_id') == self.active.get('last_build_request'):
            return None
        self.active['last_build_request'] = req['request_id']
        self._save_active()
        return req

    def record_suggestion(self, suggestion: dict) -> None:
        if suggestion.get('run_id') == self.run_id:
            atomic_json(self.suggestion_path, suggestion)
            self.append('build_suggested', suggestion=suggestion.get('build'),
                        reason=suggestion.get('why', ''))

    def note_observation(self, state: dict) -> None:
        if not self.run_id:
            return
        player = state.get('player') or {}
        run = state.get('run') or {}
        relics = tuple(sorted(str(r.get('name') or r.get('id'))
                              for r in (player.get('relics') or []) if isinstance(r, dict)))
        key = (run.get('act'), run.get('floor'), relics)
        if key != self._last_event_key:
            self._last_event_key = key
            self.append('observation', act=run.get('act'), floor=run.get('floor'),
                        hp=player.get('hp'), max_hp=player.get('max_hp'),
                        gold=player.get('gold'), relics=list(relics))

    def format_for_prompt(self, recent: int = 10, max_chars: int = 4000) -> str:
        """Bounded context, drawn from a complete append-only disk journal."""
        path = self.transcript_path
        entries = []
        if path and path.exists():
            try:
                # For typical runs the journal is small; never send it all to Claude.
                lines = path.read_text(encoding='utf-8').splitlines()
                for line in lines[-max(30, recent * 5):]:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get('kind') in ('decision', 'build_selected', 'floor', 'run_started',
                                         'observation', 'build_suggested', 'combat_advice'):
                        entries.append(e)
            except OSError:
                pass
        formatted = []
        for e in entries[-recent:]:
            kind = e.get('kind')
            if kind == 'decision':
                formatted.append(f"{e.get('screen')}: {str(e.get('advice',''))[:240]}")
            elif kind == 'combat_advice':
                formatted.append(f"Combat r{e.get('round')}: {str(e.get('summary',''))[:140]}")
            elif kind == 'observation':
                formatted.append(f"Act {e.get('act')} F{e.get('floor')}: {e.get('hp')} HP, relics {', '.join(e.get('relics', []))}")
            elif kind == 'floor':
                formatted.append(f"Entered Act {e.get('act')} floor {e.get('floor')}")
            else:
                formatted.append(f"{kind}: {str(e.get('build') or e.get('suggestion') or e.get('character') or '')}")
        base = (f"RUN ID: {self.run_id or '(unknown)'}\n"
                f"SELECTED BUILD: {self.build or 'None selected; adapt to actual rewards'}\n"
                'This is the same run. Previous recommendations do NOT prove the player took them.\n'
                'RECENT EVENTS (full journal stored locally):\n' + ('\n'.join(formatted) or '(none)'))
        return base[-max_chars:]
