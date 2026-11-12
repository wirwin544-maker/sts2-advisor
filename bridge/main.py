"""StS2 Advisor — entry point and poll loop.

Polls the STS2MCP bridge (GET only), detects owned decision screens, debounces
and de-dupes per decision, grounds the prompt with authoritative card/relic
text + the running thesis, and fires the model on a worker thread. Writes a
heartbeat the overlay watches so it opens/closes with the game.

Run:  python -m bridge.main
"""
from __future__ import annotations

import json
import time

from . import client as client_mod
from .single_instance import claim_instance
from . import combat, control, grounding, screens, signature, thesis, util, worker
from .monster_reference import MonsterReference
from .reference_search import ReferenceLibrary
from .run_memory import RunJournal, atomic_json, candidates, read_json
from . import build_catalog
from .model_client import ModelClient


class RunTracker:
    """Detects when a new run has started so the thesis can reset."""

    def __init__(self):
        self._char = None
        self._act = None
        self._floor = None

    @staticmethod
    def _character(state: dict) -> str | None:
        # character lives under player in the live API (run has only act/floor/asc)
        return (state.get("player") or {}).get("character") or \
               (state.get("run") or {}).get("character")

    def run_key(self, state: dict) -> str:
        run = state.get("run") or {}
        return f"{self._character(state)}|asc{run.get('ascension')}"

    def is_new_run(self, state: dict) -> bool:
        run = state.get("run") or {}
        char = self._character(state)
        act = run.get("act")
        floor = run.get("floor")
        new = False
        if self._char is None:
            # First observation this session. Only treat it as a NEW run if we're
            # clearly at a run's very start (floor <= 1). A mid-run RESTART must NOT
            # wipe the persisted deck/thesis just because we forgot the character.
            if isinstance(floor, int) and floor <= 1:
                new = True
        elif char and char != self._char:
            new = True
        elif (self._floor is not None and floor is not None
              and act == 1 and floor <= 1 and self._floor > floor):
            new = True  # floor reset back to act 1 start
        self._char, self._act, self._floor = char, act, floor
        return new


class DeckTracker:
    """Maintains the player's current deck.

    STS2MCP doesn't expose the deck outside combat, so we:
      1. seed it from the character's starter deck at run start, then
      2. overwrite it from the combat piles (hand+draw+discard+exhaust) every
         time we observe a combat — the game's own truth, refreshed each fight.
    Persisted to runtime/deck.json so it survives an advisor restart mid-run.
    Each deck entry is {name, is_upgraded, count}.
    """

    _PILE_KEYS = ("hand", "draw_pile", "discard_pile", "exhaust_pile")

    def __init__(self, starter_decks: dict, persist_path, logger):
        self._starters = starter_decks or {}
        self._path = persist_path
        self._logger = logger
        self._cards: list[dict] = []
        self._source = ""
        self._floor: int | None = None   # floor of the last combat snapshot
        self._combat_best = 0             # largest pile-union seen in the current combat
        self._combat_clean = False        # got an authoritative turn-1 capture this combat
        self._combat_logged = False       # logged pile sizes once this combat
        self._load()

    # ---- persistence -----------------------------------------------------
    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._cards = data.get("cards", [])
                self._source = data.get("source", "")
                self._floor = data.get("floor")
        except (ValueError, OSError):
            pass

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(
                {"source": self._source, "floor": self._floor, "cards": self._cards},
                indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- seeding + snapshotting -----------------------------------------
    def seed_starter(self, character: str | None) -> None:
        key = (character or "").replace("The ", "").strip().lower()
        starter = self._starters.get(key)
        self._floor = None
        if starter:
            self._cards = [{"name": c["name"], "is_upgraded": False,
                            "count": int(c.get("count", 1))} for c in starter]
            self._source = f"starter deck for {key} (assumed; verifies on first combat)"
            self._logger.info("Seeded starter deck for %s (%d cards).",
                              key, sum(c["count"] for c in self._cards))
        else:
            self._cards = []
            self._source = "unknown until first combat observed"
        self._save()

    @staticmethod
    def _pile_len(player: dict, list_key: str, count_key: str) -> int:
        v = player.get(list_key)
        if isinstance(v, list):
            return len(v)
        return int(player.get(count_key) or 0)

    def maybe_snapshot(self, state: dict) -> None:
        player = state.get("player") or {}
        hand = player.get("hand") or []
        draw = player.get("draw_pile") or []
        discard = player.get("discard_pile") or []
        exhaust = player.get("exhaust_pile") or []
        if not (hand or draw or discard or exhaust):
            # Not in combat — reset per-combat tracking for the next fight.
            self._combat_best = 0
            self._combat_clean = False
            self._combat_logged = False
            return

        if not self._combat_logged:
            self._logger.info("In combat: piles hand=%d draw=%d discard=%d exhaust=%d",
                              len(hand), len(draw), len(discard), len(exhaust))
            self._combat_logged = True

        discard_n = self._pile_len(player, "discard_pile", "discard_pile_count")
        clean = discard_n == 0   # turn 1, nothing played yet -> authoritative deck

        # Authoritative view: a clean turn 1 (Powers still in draw, nothing consumed).
        # Fallback: if we never catch a clean turn 1 this combat (some characters
        # auto-play on turn 1), use the LARGEST all-piles union we see so we're not
        # perpetually blind — it may include combat-generated cards, and the staleness
        # note flags it; the next clean turn 1 corrects it.
        if clean:
            src_cards = list(hand) + list(draw) + list(exhaust)
            self._combat_clean = True
        elif self._combat_clean:
            return  # already have an authoritative deck this combat
        else:
            union = list(hand) + list(draw) + list(discard) + list(exhaust)
            if len(union) <= self._combat_best:
                return
            src_cards = union

        counts: dict[tuple, int] = {}
        total = 0
        for c in src_cards:
            if isinstance(c, dict):
                name, up = c.get("name"), bool(c.get("is_upgraded"))
            else:
                name, up = str(c), False
            if name:
                counts[(name, up)] = counts.get((name, up), 0) + 1
                total += 1
        if total == 0:
            return
        self._combat_best = max(self._combat_best, total)
        new_cards = [{"name": n, "is_upgraded": u, "count": ct}
                     for (n, u), ct in sorted(counts.items())]
        floor = (state.get("run") or {}).get("floor")
        old_floor = self._floor
        old_source = self._source
        self._floor = floor if isinstance(floor, int) else self._floor
        how = "turn 1" if clean else "approx (mid-combat)"
        src = f"observed in combat {how} (floor {floor}, {total} cards)"
        changed = new_cards != self._cards
        self._cards = new_cards
        self._source = src
        if changed or self._floor != old_floor or self._source != old_source:
            self._save()
        if changed:
            self._logger.info("Deck updated %s: %d cards (floor %s).", how, total, floor)

    @property
    def cards(self) -> list[dict]:
        return self._cards

    @property
    def source(self) -> str:
        return self._source

    def source_with_staleness(self, current_floor) -> str:
        """Source string plus how stale the snapshot is (cards gained/removed since
        the last combat aren't visible — the mod only exposes the deck in combat)."""
        if isinstance(self._floor, int) and isinstance(current_floor, int):
            gap = current_floor - self._floor
            if gap > 0:
                return (f"{self._source} — last verified {gap} floor(s) ago; may be "
                        f"missing cards gained/removed since (rewards, shops, relics)")
        return self._source


def _load_sample(cfg) -> dict:
    path = util.resolve(cfg["dev"]["sample_state_file"])
    return json.loads(path.read_text(encoding="utf-8"))


_WIN_WORDS = ("victor", "triumph", " win", "won", "ascend", "cleared", "complete", "escape")
_LOSS_WORDS = ("died", "death", "defeat", "lost", "slain", "fell", "perish")


def _game_over_message(state: dict) -> str:
    """Build a victory/defeat acknowledgement. STS2MCP gives no win/loss flag, so
    infer from the game_over message text, falling back to HP (you finish a won
    run alive; death is 0 HP)."""
    go = state.get("game_over") or {}
    run = state.get("run") or {}
    player = state.get("player") or {}
    raw = str(go.get("message") or "").lower()
    char = (player.get("character") or "?").replace("The ", "")
    act = run.get("act", "?")
    floor = run.get("floor", "?")
    hp = player.get("hp")

    if any(w in raw for w in _WIN_WORDS):
        won = True
    elif any(w in raw for w in _LOSS_WORDS):
        won = False
    else:
        won = (hp or 0) > 0  # finished alive -> victory

    if won:
        return (f"[ run complete ]\n🏆 VICTORY — {char}! You beat the Spire.\n"
                f"Reached Act {act}. GG — start a new run when ready.")
    return (f"[ run over ]\n💀 Defeated — {char}, Act {act}, Floor {floor}.\n"
            f"{go.get('message') or 'The run has ended.'}")


def main() -> None:
    cfg = util.load_config()
    # Avoid two bridge loops issuing duplicate Claude requests and writing the
    # same runtime files when autostart and start.bat are both enabled.
    instance_guard = claim_instance(int(cfg.get('bridge', {}).get('instance_port', 15581)))
    if instance_guard is None:
        print('Spire Oracle bridge is already running; declining duplicate start.')
        return
    logger = util.setup_logging(cfg["paths"]["log_file"])
    logger.info("StS2 Advisor starting.")

    dataset = grounding.Dataset.load(cfg["paths"]["data_dir"])
    reference = MonsterReference.load(util.resolve(
        cfg['paths'].get('monster_reference_file', 'data/monster_moves.json')))
    logger.info('Monster reference loaded: %d entries, game %s',
                len(reference.entries), reference.source_version)
    library = ReferenceLibrary.load(util.resolve(
        cfg['paths'].get('reference_cache_file', 'data/reference_cache.json')))
    logger.info('Full reference loaded: %d sheets, game %s',
                len(library.sheets), library.version)
    logger.info("Dataset loaded: %d cards, %d relics (game v%s)",
                len(dataset.cards), len(dataset.relics), dataset.version)
    if not dataset.cards:
        logger.warning("No card data found. Run `python data/fetch_data.py` first; "
                       "advice will fall back to in-state text only.")

    starter_decks = {}
    starter_path = util.resolve(cfg["paths"]["data_dir"]) / "starter_decks.json"
    if starter_path.exists():
        try:
            starter_decks = {k: v for k, v in
                             json.loads(starter_path.read_text(encoding="utf-8")).items()
                             if not k.startswith("_")}
        except (ValueError, OSError):
            logger.warning("Could not read starter_decks.json")

    bridge = client_mod.BridgeClient(
        base_url=cfg["bridge"]["base_url"],
        state_path=cfg["bridge"]["state_path"],
        health_path=cfg["bridge"]["health_path"],
        timeout=cfg["bridge"]["request_timeout_s"],
    )
    model = ModelClient(cfg, logger)
    thesis_store = thesis.ThesisStore(cfg["paths"]["thesis_file"])
    debouncer = signature.Debouncer(cfg["debounce"]["settle_s"])
    journal = RunJournal(cfg["paths"].get("runtime_dir", "runtime"))
    deck = DeckTracker(starter_decks, util.resolve("runtime/deck.json"), logger)
    adv_worker = worker.AdviceWorker(
        model, thesis_store, cfg["paths"]["advice_file"], logger,
        journal=journal, combat_file=cfg["paths"].get("combat_plan_file", "runtime/combat_plan.json"))
    adv_worker.start()

    heartbeat_path = util.resolve(cfg["paths"]["heartbeat_file"])
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)

    use_sample = cfg["dev"].get("use_sample_state", False)
    poll = cfg["bridge"]["poll_interval_s"]
    backoff = cfg["bridge"]["reconnect_backoff_s"]
    log_prompts = cfg["dev"].get("log_prompts", False)
    game_over_handled = False
    combat_debounce = signature.Debouncer(cfg.get("combat", {}).get("settle_s", 0.65))
    orb_stabilizer = combat.OrbStabilizer(
        cfg.get('combat', {}).get('orb_confirmation_polls', 3))
    combat_enabled = bool(cfg.get("combat", {}).get("enabled", True))
    combat_interval = float(cfg.get("combat", {}).get("min_request_interval_s", 3.0))
    combat_max = int(cfg.get("combat", {}).get("max_requests_per_fight", 30))
    combat_status_path = util.resolve(cfg["paths"].get("combat_status_file", "runtime/combat_status.json"))
    control_path = util.resolve(cfg['paths'].get('control_file', 'runtime/control.json'))
    was_paused = False
    current_fight = None
    combat_requests = 0
    last_combat_call = 0.0
    last_state_sig = None
    build_pending_sig = None
    build_pending_at = 0.0
    logger.info("Polling %s%s", bridge.base_url, bridge.state_path)
    try:
        while True:
            # 1. Read state (or sample fixture in dev mode).
            try:
                state = _load_sample(cfg) if use_sample else bridge.get_state()
            except client_mod.BridgeError as exc:
                logger.debug("bridge unreachable: %s", exc)
                # Don't touch heartbeat -> overlay hides itself (game not running).
                time.sleep(backoff)
                continue

            # Bridge is up: heartbeat so the overlay shows.
            heartbeat_path.write_text(str(time.time()), encoding="utf-8")

            # Everything below can hit unexpected game state. Guard it so one bad
            # screen logs + shows a friendly note instead of killing the advisor.
            try:
                # 2. Durable run identity. Do not reset on a same-floor restart.
                previous_run_id = journal.run_id
                new_run = journal.observe(state)
                if new_run:
                    # First install while already in a run must not overwrite
                    # the player's real deck/thesis with a starter guess.
                    mid_run_migration = (previous_run_id is None and
                        isinstance((state.get('run') or {}).get('floor'), int) and
                        (state.get('run') or {}).get('floor') > 1)
                    if mid_run_migration:
                        logger.info("Adopting existing mid-run deck/thesis under %s", journal.run_id)
                        thesis_store.run_key = journal.run_id
                        thesis_store.save()
                    else:
                        logger.info("New run %s: resetting thesis + seeding deck.", journal.run_id)
                        thesis_store.reset(journal.run_id)
                        deck.seed_starter(RunTracker._character(state))
                    model.reset_sessions()
                    debouncer.reset()
                    combat_debounce.reset()
                    orb_stabilizer.reset()
                    adv_worker.invalidate(None)
                    current_fight = None
                    combat_requests = 0
                if journal.accept_build_choice():
                    # Selecting a build must immediately release the advisor,
                    # even if a previous model call has not completed yet.
                    build_pending_sig = None
                    debouncer.reset()
                    adv_worker.invalidate(None)
                    last_state_sig = None
                journal.note_observation(state)

                if state.get("state_type") == "game_over" or state.get("game_over"):
                    if not game_over_handled:
                        msg = _game_over_message(state)
                        util.resolve(cfg["paths"]["advice_file"]).write_text(
                            msg + "\n", encoding="utf-8")
                        logger.info("Run ended: %s", msg.splitlines()[0])
                        journal.finish(msg.splitlines()[0])
                        adv_worker.invalidate(None)
                        debouncer.reset()
                        game_over_handled = True
                    atomic_json(combat_status_path, {"status": "inactive", "run_id": journal.run_id})
                    time.sleep(poll)
                    continue
                game_over_handled = False

                # Continue collecting deck and run observations even while
                # paused, but never request or display new recommendations.
                deck.maybe_snapshot(state)
                paused = control.is_paused(control_path)
                if paused != was_paused:
                    adv_worker.invalidate(None)  # invalidates in-flight results
                    debouncer.reset()
                    combat_debounce.reset()
                    last_state_sig = None
                    build_pending_sig = None
                    was_paused = paused
                    logger.info('Suggestions %s.', 'paused' if paused else 'resumed')
                    if not paused:
                        util.resolve(cfg['paths']['advice_file']).write_text(
                            'Resuming. Rechecking current state…\n', encoding='utf-8')
                if paused:
                    atomic_json(combat_status_path, {
                        'status': 'paused', 'run_id': journal.run_id})
                    time.sleep(poll)
                    continue
                cancelled = read_json(journal.cancel_path)
                if (build_pending_sig and cancelled.get('run_id') == journal.run_id and
                        cancelled.get('request_id') == build_pending_sig.split(':')[-1]):
                    build_pending_sig = None
                    adv_worker.invalidate(None)
                    last_state_sig = None
                    logger.info('Build suggestion cancelled by player. Continuing normal coaching.')
                build_req = journal.build_request()
                if build_req:
                    requested_character = build_catalog.normalize_character(build_req.get('character'))
                    actual_character = build_catalog.normalize_character(journal.active.get('character'))
                    character = actual_character if actual_character != 'Unknown' else requested_character
                    opts = candidates(character)
                    if not opts:
                        logger.warning('Build recommendation needs a character; skipping request.')
                        journal.record_suggestion({
                            'run_id': journal.run_id, 'request_id': build_req['request_id'],
                            'status': 'error', 'build': '', 'why': 'Select your character first.'})
                        time.sleep(poll)
                        continue
                    start_state = {
                        "character": character,
                        "ascension": journal.active.get("ascension"),
                        "act": (state.get("run") or {}).get("act"),
                        "floor": (state.get("run") or {}).get("floor"),
                        "current_screen": state.get("state_type"),
                        "available_options": screens.extract_options(state, "event")
                            if state.get("state_type") == "event" else
                            screens.extract_options(state, state.get("state_type") or ""),
                        "owned_relics": (state.get("player") or {}).get("relics") or [],
                    }
                    payload = ("Suggest a starting strategic BUILD for this StS2 run, before "
                               "the first Ancient blessing or relic pick if possible. "
                               "Choose EXACTLY from these options:\n" +
                               build_catalog.details_for_prompt(character) +
                               "\nReference source uses v0.107.1 editorial tiers, not verified win-rates. "
                               "Do not demand an unavailable rare card. "
                               "If no reliable starting information is available choose Flexible / adapt to rewards.\n"
                               "CURRENT STATE:\n" + json.dumps(start_state, default=str) +
                               "\nFormat PICK: <exact option> and WHY: <short sentence>.")
                    req_sig = "build:" + journal.run_id + ":" + build_req["request_id"]
                    adv_worker.request(req_sig, payload, model.model_for("build"),
                                       "build", run_id=journal.run_id, build_options=opts)
                    # The bridge pauses ordinary advice while Claude recommends a build.
                    # If a player advances anyway, advice resumes after the next poll.
                    last_state_sig = req_sig
                    build_pending_sig = req_sig
                    build_pending_at = time.monotonic()
                    time.sleep(poll)
                    continue

                # Keep the build proposal alive until it completes or times out.
                if build_pending_sig is not None:
                    suggestion = read_json(journal.suggestion_path)
                    if (suggestion.get('run_id') == journal.run_id and
                            suggestion.get('request_id') == build_pending_sig.split(':')[-1]):
                        build_pending_sig = None
                        last_state_sig = None
                    elif time.monotonic() - build_pending_at < 55:
                        time.sleep(poll)
                        continue
                    else:
                        logger.warning('Build recommendation timed out; resuming normal coaching.')
                        journal.record_suggestion({
                            'run_id': journal.run_id,
                            'request_id': build_pending_sig.split(':')[-1],
                            'status': 'timeout', 'build': '',
                            'why': 'Claude took too long. Choose a build directly or retry.'})
                        build_pending_sig = None
                        adv_worker.invalidate(None)
                        last_state_sig = None

                # 3. Combat uses a separate, instantly invalidated plan. Card
                # effects change the signature and force a fresh legal-action check.
                is_battle_screen = (state.get("state_type") in combat.COMBAT_KINDS and
                                    bool(state.get("battle")))
                if combat_enabled and is_battle_screen:
                    sig = "combat:" + combat.digest(state)
                    round_no = (state.get("battle") or {}).get("round")
                    fight_key = ((state.get("run") or {}).get("act"),
                                 (state.get("run") or {}).get("floor"),
                                 state.get("state_type"), round_no)
                    if current_fight is None or current_fight[:3] != fight_key[:3]:
                        current_fight = fight_key
                        combat_requests = 0
                        orb_stabilizer.reset()
                        found = reference.encounter(state)
                        logger.info('Encounter reference: %d/%d enemies matched (sheet v%s): %s',
                                    sum(f['reference'] is not None for f in found),
                                    len(found), reference.source_version,
                                    ', '.join(str(f['live_name']) for f in found))
                    # Stabilize the orb queue independently of the rest of the
                    # battle. Never ask Claude to act on one disputed orb read.
                    orb_verified = orb_stabilizer.observe((state.get('player') or {}).get('orbs'))
                    verified_state = orb_stabilizer.stable_state(state)
                    sig = 'combat:' + combat.digest(verified_state)
                    if last_state_sig != sig or not orb_verified:
                        adv_worker.invalidate(sig)
                        last_state_sig = sig
                    if not orb_verified:
                        # Invalidate any prior advice immediately, including if
                        # an oscillating orb queue returns the same digest.
                        adv_worker.invalidate(None)
                        last_state_sig = None
                        combat_debounce.reset()
                    can_advise = combat.active(state)
                    combat_limit = combat_requests >= combat_max
                    found = reference.encounter(state)
                    atomic_json(combat_status_path, {
                        **combat.summary(verified_state, sig, journal.run_id),
                        'orb_read_stable': orb_verified,
                        'reference_matched': sum(f['reference'] is not None for f in found),
                        'reference_total': len(found),
                        'reference_version': reference.source_version,
                        "status": "waiting" if not orb_verified or not can_advise else
                                  "limit" if combat_limit else "active",
                        "remaining_requests": max(0, combat_max - combat_requests),
                    })
                    if not orb_verified or not can_advise or combat_limit:
                        time.sleep(poll)
                        continue
                    combat_debounce.observe(sig)
                    now = time.monotonic()
                    if (combat_debounce.should_fire(sig) and
                            now - last_combat_call >= combat_interval and
                            combat_requests < combat_max):
                        payload = combat.prompt(
                            verified_state, thesis_store.format_for_prompt(),
                            journal.format_for_prompt(4, 1200), journal.build,
                            reference_text=reference.prompt_for_battle(state))
                        adv_worker.request(sig, payload, model.model_for("combat"),
                                           "combat", run_id=journal.run_id, state=verified_state)
                        combat_debounce.mark_fired(sig)
                        last_combat_call = now
                        combat_requests += 1
                    time.sleep(poll)
                    continue
                atomic_json(combat_status_path, {"status": "inactive", "run_id": journal.run_id})
                current_fight = None
                orb_stabilizer.reset()
                combat_requests = 0
                combat_debounce.reset()

                # 4. Non-combat decision: old advice must not leak to a new screen.
                kind, is_decision = screens.classify(state)
                if not is_decision:
                    if last_state_sig is not None:
                        adv_worker.invalidate(None)
                        last_state_sig = None
                        util.resolve(cfg["paths"]["advice_file"]).write_text(
                            "Waiting for the next decision screen...\n", encoding="utf-8")
                    time.sleep(poll)
                    continue
                sig = signature.build(state, kind)
                if last_state_sig != sig:
                    adv_worker.invalidate(sig)
                    last_state_sig = sig
                debouncer.observe(sig)
                if debouncer.should_fire(sig):
                    m_kind = screens.model_kind(state, kind)
                    alias = model.model_for(m_kind)
                    payload = grounding.build_payload(
                        state, kind, dataset, thesis_store.format_for_prompt(),
                        deck_cards=deck.cards,
                        deck_source=deck.source_with_staleness((state.get("run") or {}).get("floor")))
                    reference_excerpt = library.context_for_screen(state, kind)
                    if reference_excerpt:
                        payload += "\n\n=== IMPORTED REFERENCE EXCERPTS ===\n" + reference_excerpt
                    payload += ("\n\n=== PERSISTENT RUN JOURNAL ===\n" +
                                journal.format_for_prompt(cfg.get("memory", {}).get("recent_events", 10)))
                    if log_prompts:
                        logger.info("PROMPT [%s -> %s]:\n%s", kind, alias, payload)
                    logger.info("Firing advice: %s (model=%s, sig=%s)", kind, alias, sig)
                    adv_worker.request(sig, payload, alias, kind, run_id=journal.run_id)
                    debouncer.mark_fired(sig)
            except PermissionError as exc:
                # OneDrive/AV can briefly hold the run-journal path. Do not
                # replace valid advice with a generic error for a recoverable
                # Windows file-lock failure. The next poll retries the save.
                logger.warning('Temporary runtime file access failure; retrying: %s', exc)
                adv_worker.invalidate(None)
                combat_debounce.reset()
                last_state_sig = None
            except Exception:  # noqa: BLE001 - keep the advisor alive on any bad state
                logger.exception("Error processing state (state_type=%s)",
                                 state.get("state_type"))
                try:
                    util.resolve(cfg["paths"]["advice_file"]).write_text(
                        "[ advisor ]\nHit an error on this screen — skipping it. "
                        "See runtime/advisor.log.\n", encoding="utf-8")
                except OSError:
                    pass

            time.sleep(poll)
    except KeyboardInterrupt:
        logger.info("Shutting down (Ctrl-C).")
    finally:
        adv_worker.stop()
        model.shutdown()
        instance_guard.close()
        try:
            heartbeat_path.unlink()  # signal overlay to close
        except OSError:
            pass


if __name__ == "__main__":
    main()
