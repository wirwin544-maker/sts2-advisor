"""Read-only combat context, state signatures and legal-action screening.

AI sequences are conditional plans, NOT simulated multi-card guarantees.
Only the first suggested action is verified against live card/target legality;
after each action a fresh game state and recommendation are required.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from .run_memory import atomic_json

COMBAT_KINDS = {'monster', 'elite', 'boss', 'hand_select'}


class OrbStabilizer:
    """Confirm successive orb readings before changing player-facing advice.

    A partial read during card animations can briefly report a different queue.
    The advisor must not treat one such sample as a valid new Dualcast target.
    A snapshot is accepted after ``required`` consecutive matching samples.
    """

    def __init__(self, required: int = 3):
        self.required = max(2, int(required))
        self.reset()

    def reset(self) -> None:
        self.confirmed: list[dict] = []
        self._confirmed_key: str | None = None
        self._candidate_key: str | None = None
        self._count = 0

    @staticmethod
    def _key(orbs: list[dict]) -> str:
        # Do not include display descriptions or transient hover-text values.
        canonical = [{k: orb.get(k) for k in ('id', 'name', 'passive_val', 'evoke_val')}
                     for orb in orbs if isinstance(orb, dict)]
        return json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)

    def observe(self, raw_orbs: object) -> bool:
        """Return True only when the current queue matches a confirmed reading.

        Absence of an ``orbs`` field after observing orbs is NOT evidence that
        they vanished; the state reader may have omitted an incomplete field.
        """
        if not isinstance(raw_orbs, list):
            if self._confirmed_key is not None and self.confirmed:
                self._candidate_key = None
                self._count = 0
                return False
            raw_orbs = []
        raw_orbs = [o for o in raw_orbs if isinstance(o, dict)]
        key = self._key(raw_orbs)
        if key == self._confirmed_key:
            self._candidate_key = None
            self._count = 0
            return True
        if key == self._candidate_key:
            self._count += 1
        else:
            self._candidate_key = key
            self._count = 1
        if self._count < self.required:
            return False
        self.confirmed = deepcopy(raw_orbs)
        self._confirmed_key = key
        self._candidate_key = None
        self._count = 0
        return True

    def stable_state(self, state: dict) -> dict:
        """A copy with verified orbs, never the unconfirmed raw API reading."""
        copy = dict(state)
        copy['player'] = {**(state.get('player') or {}), 'orbs': deepcopy(self.confirmed)}
        return copy


def active(state: dict) -> bool:
    battle = state.get('battle') or {}
    return state.get('state_type') in COMBAT_KINDS and bool(battle) and (
        state.get('state_type') == 'hand_select' or
        (str(battle.get('turn', 'player')).lower() == 'player' and
         battle.get('is_play_phase', True) is not False))


def _player_cards(state: dict) -> list[dict]:
    if state.get('state_type') == 'hand_select':
        return (state.get('hand_select') or {}).get('cards') or []
    return (state.get('player') or {}).get('hand') or []


def _safe_card(card: dict) -> dict:
    return {key: card.get(key) for key in (
        'index', 'id', 'name', 'type', 'cost', 'star_cost', 'description',
        'target_type', 'can_play', 'unplayable_reason', 'is_upgraded', 'keywords')}


def digest(state: dict) -> str:
    """Changes for hand/energy/status/target/intent/potions and card effects."""
    player = state.get('player') or {}
    battle = state.get('battle') or {}
    run = state.get('run') or {}
    subset = {
        'screen': state.get('state_type'),
        'floor': run.get('floor'), 'act': run.get('act'),
        'round': battle.get('round'), 'turn': battle.get('turn'),
        'is_play_phase': battle.get('is_play_phase'),
        'enemies': battle.get('enemies'),
        'hand': _player_cards(state),
        'hand_select': state.get('hand_select'),
        'player': {k: player.get(k) for k in ('hp', 'max_hp', 'block', 'energy', 'max_energy',
                    'stars', 'status', 'orbs', 'draw_pile_count', 'discard_pile_count',
                    'exhaust_pile_count', 'potions', 'relics')},
    }
    raw = json.dumps(subset, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def player_facing_enemies(state: dict) -> list[dict]:
    """Stable human labels for currently living targets, in state list order.

    Internal IDs like WRIGGLER_0 are deliberately retained for target validation.
    No claim about physical screen x-coordinates is made: the API does not
    expose those coordinates. HP helps distinguish same-name enemies.
    """
    enemies = (state.get('battle') or {}).get('enemies') or []
    result = []
    for pos, enemy in enumerate(enemies, 1):
        if not isinstance(enemy, dict):
            continue
        label = f"Enemy {pos}: {enemy.get('name') or 'Unknown'} ({enemy.get('hp', '?')} HP)"
        result.append({**enemy, 'number': pos, 'label': label})
    return result


def display_orbs(orbs: list[dict]) -> dict:
    """Expose UI left-to-right order explicitly, independent of raw queue order.

    STS2 OrbQueue.Orbs has its oldest/next-to-evoke orb first (rightmost on
    screen). The newest orb is last (leftmost on screen). STS2 OrbCmd.EvokeNext
    selects Orbs.First(). Dualcast evokes that rightmost orb twice.
    """
    queue = [o for o in (orbs or []) if isinstance(o, dict)]
    left_to_right = []
    for slot, orb in enumerate(reversed(queue), 1):
        left_to_right.append({
            'slot_from_left': slot,
            'name': orb.get('name') or orb.get('id') or 'Unknown',
            'id': orb.get('id'),
            'passive_val': orb.get('passive_val'),
            'evoke_val': orb.get('evoke_val'),
            'next_to_evoke': slot == len(queue),
        })
    return {
        'left_to_right': left_to_right,
        'next_to_evoke': left_to_right[-1] if left_to_right else None,
        'evoke_direction': 'rightmost orb first',
        'dualcast_rule': 'Evoke the same rightmost orb twice',
    }


def summary(state: dict, sig: str, run_id: str | None) -> dict:
    p, b, r = state.get('player') or {}, state.get('battle') or {}, state.get('run') or {}
    return {
        'run_id': run_id, 'signature': sig, 'screen': state.get('state_type'),
        'act': r.get('act'), 'floor': r.get('floor'), 'round': b.get('round'),
        'hp': p.get('hp'), 'max_hp': p.get('max_hp'), 'block': p.get('block'),
        'energy': p.get('energy'), 'max_energy': p.get('max_energy'),
        'enemies': [{'entity_id': e.get('entity_id'), 'number': e['number'],
                     'label': e['label'], 'name': e.get('name'), 'hp': e.get('hp'),
                     'block': e.get('block'), 'intents': e.get('intents') or []}
                    for e in player_facing_enemies(state)],
        'orbs': display_orbs(p.get('orbs') or []),
        'hand': [{'index': c.get('index'), 'display_number': c.get('index', i) + 1,
                  'name': c.get('name'), 'can_play': c.get('can_play')}
                 for i, c in enumerate(_player_cards(state))],
        'selection': (state.get('hand_select') or {}).get('prompt'),
    }


def prompt(state: dict, thesis_text: str, history: str, build: str, reference_text: str = "") -> str:
    p = state.get('player') or {}
    b = state.get('battle') or {}
    r = state.get('run') or {}
    cards = [_safe_card(c) for c in _player_cards(state)]
    enemies = [{k: e.get(k) for k in ('entity_id', 'name', 'hp', 'max_hp', 'block',
                                      'status', 'intents', 'number', 'label')}
               for e in player_facing_enemies(state)]
    for c in cards:
        if type(c.get('index')) is int:
            c['display_number'] = c['index'] + 1
    core = {
        'screen': state.get('state_type'), 'act': r.get('act'), 'floor': r.get('floor'),
        'round': b.get('round'), 'turn': b.get('turn'), 'is_play_phase': b.get('is_play_phase'),
        'hp': p.get('hp'), 'max_hp': p.get('max_hp'), 'block': p.get('block'),
        'energy': p.get('energy'), 'max_energy': p.get('max_energy'), 'stars': p.get('stars'),
        'status': p.get('status') or [],
        'orbs': display_orbs(p.get('orbs') or []),
        'draw_count': p.get('draw_pile_count'), 'discard_count': p.get('discard_pile_count'),
        'exhaust_count': p.get('exhaust_pile_count'),
        'hand': cards, 'enemies': enemies, 'potions': p.get('potions') or [],
        'relics': p.get('relics') or [],
        'hand_selection': state.get('hand_select') if state.get('state_type') == 'hand_select' else None,
    }
    return (f"READ-ONLY COMBAT ADVICE FOR CURRENT STATE. No moves are executed.\n"
            f"BUILD PREFERENCE: {build or 'Flexible'}\n"
            f"RUNNING STRATEGY:\n{thesis_text}\nRECENT RUN HISTORY:\n{history}\n"
            f"ENEMY MOVESET REFERENCE (informational; do NOT override live state):\n{reference_text or 'none'}\n"
            f"AUTHORITATIVE LIVE COMBAT STATE:\n{json.dumps(core, ensure_ascii=False, default=str)}\n"
            "Recommend an ordered sequence only of cards currently in hand and legal actions. "
            "The first action must be immediately legal. Later actions are tentative and "
            "will be recalculated after the first action resolves. Account for card draw, "
            "energy changes, buffs, dead targets, potions and unknown effects by qualifying "
            "later steps. CRITICAL ORB RULE: 'orbs.left_to_right' lists the slots as "
            "seen on screen. Dualcast evokes the RIGHTMOST orb twice, matching "
            "orbs.next_to_evoke, not the leftmost orb. If it is Frost, calculate "
            "Frost Block rather than Dark damage, even if there is a Dark orb on "
            "the left. Each enemy has a player-facing 1-based label but JSON "
            "target must still use its exact entity_id. Refer to enemies by "
            "'Enemy 1', 'Enemy 2', etc. in human-readable explanations; "
            "never use raw _0 or _1 suffixes in text. "
            "Never invent a card or enemy. Use the required JSON format only.")


def _parse_json(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```\s*$', '', text)
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def player_text(value: object, enemies: dict) -> str:
    """Replace opaque zero-based engine target IDs in free-form explanations."""
    result = str(value or '')
    for entity_id, enemy in sorted(enemies.items(), key=lambda item: -len(str(item[0]))):
        result = re.sub(re.escape(str(entity_id)), str(enemy['label']), result,
                        flags=re.IGNORECASE)
    return result


def validate_response(text: str, state: dict, sig: str, run_id: str | None) -> dict:
    """Reject invalid immediate moves. Subsequent steps are clearly tentative."""
    data = _parse_json(text)
    base = {'run_id': run_id, 'signature': sig, 'status': 'unavailable',
            'steps': [], 'why': '', 'risk': '', 'warning': ''}
    if not data or not isinstance(data.get('steps'), list) or not data['steps']:
        return {**base, 'warning': 'Claude did not return a valid combat plan.'}
    cards = _player_cards(state)
    by_index = {c.get('index', i): c for i, c in enumerate(cards)}
    enemies = {e.get('entity_id'): e for e in player_facing_enemies(state)
               if e.get('entity_id') and e.get('hp', 1) != 0}
    potions = {p.get('slot', i): p for i, p in enumerate((state.get('player') or {}).get('potions') or [])}
    out = []
    used_cards = set()
    select = state.get('state_type') == 'hand_select'
    for ordinal, step in enumerate(data['steps'][:8]):
        if not isinstance(step, dict):
            continue
        action = step.get('action')
        parsed = {'action': action, 'reason': str(step.get('reason') or '')[:160],
                  'tentative': ordinal > 0}
        if action in ('play_card', 'select_card'):
            if select != (action == 'select_card'):
                continue
            idx = step.get('card_index')
            if type(idx) is not int or idx not in by_index or idx in used_cards:
                continue
            card = by_index[idx]
            # Requiring ID or name blocks hallucinated names assigned to real indices.
            claimed_id = step.get('card_id')
            claimed_name = step.get('name')
            if claimed_id and str(claimed_id).lower() != str(card.get('id')).lower():
                continue
            if claimed_name and str(claimed_name).lower() != str(card.get('name')).lower():
                continue
            if ordinal == 0 and action == 'play_card' and card.get('can_play') is not True:
                continue
            # Dualcast always evokes the RIGHTMOST orb twice, regardless of
            # any Dark orb visible on the left. Require the model to name the
            # orb it thinks it is evoking; never show an unverified Dualcast plan.
            if ordinal == 0 and action == 'play_card' and str(card.get('name', '')).casefold() == 'dualcast':
                expected = display_orbs((state.get('player') or {}).get('orbs') or [])['next_to_evoke']
                if expected:
                    claimed = str(step.get('orb_evoked_id') or '').casefold()
                    valid = {str(expected.get('id') or '').casefold()}
                    # Exact orb name is accepted when a game mod omits an ID.
                    valid.add(str(expected.get('name') or '').casefold())
                    if not claimed or claimed not in valid:
                        return {**base, 'warning': 'Dualcast orb mismatch: cannot verify the rightmost orb. Recheck the orb queue before playing.'}
            target_type = str(card.get('target_type') or 'None')
            target = step.get('target')
            if action == 'play_card' and target_type in ('AnyEnemy', 'AllEnemies'):
                if target_type == 'AnyEnemy' and target not in enemies:
                    continue
                if target_type == 'AllEnemies':
                    target = None
            elif action == 'play_card' and target and target not in enemies:
                continue
            used_cards.add(idx)
            parsed.update(card_index=idx, display_card_number=idx + 1,
                          card_id=card.get('id'), name=card.get('name'),
                          target=target,
                          target_label=enemies[target]['label'] if target in enemies else None)
        elif action == 'use_potion' and not select:
            slot = step.get('slot')
            if type(slot) is not int or slot not in potions:
                continue
            potion = potions[slot]
            if ordinal == 0 and potion.get('can_use_in_combat') is not True:
                continue
            target = step.get('target')
            if str(potion.get('target_type')) == 'AnyEnemy' and target not in enemies:
                continue
            parsed.update(slot=slot, name=potion.get('name'), target=target,
                          target_label=enemies[target]['label'] if target in enemies else None)
        elif action == 'end_turn' and not select:
            parsed.update(name='End turn')
        else:
            continue
        out.append(parsed)
    if not out or out[0].get('tentative'):
        return {**base, 'warning': 'No legal first action could be verified. Recheck the board.'}
    for entry in out:
        entry['reason'] = player_text(entry.get('reason'), enemies)
    # A multi-card sequence is not guaranteed after reactive card effects.
    return {**base, 'status': 'ready', 'steps': out,
            'why': player_text(data.get('why'), enemies)[:300],
            'risk': player_text(data.get('risk'), enemies)[:220],
            'warning': 'Only step 1 is validated. Later steps are conditional and update after each action.'}
