"""Read-only combat context, state signatures and legal-action screening.

AI sequences are conditional plans, NOT simulated multi-card guarantees.
Only the first suggested action is verified against live card/target legality;
after each action a fresh game state and recommendation are required.
"""
from __future__ import annotations

import hashlib
import json
import re
from .run_memory import atomic_json

COMBAT_KINDS = {'monster', 'elite', 'boss', 'hand_select'}


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


def summary(state: dict, sig: str, run_id: str | None) -> dict:
    p, b, r = state.get('player') or {}, state.get('battle') or {}, state.get('run') or {}
    return {
        'run_id': run_id, 'signature': sig, 'screen': state.get('state_type'),
        'act': r.get('act'), 'floor': r.get('floor'), 'round': b.get('round'),
        'hp': p.get('hp'), 'max_hp': p.get('max_hp'), 'block': p.get('block'),
        'energy': p.get('energy'), 'max_energy': p.get('max_energy'),
        'enemies': [{'name': e.get('name'), 'hp': e.get('hp'), 'block': e.get('block'),
                     'intents': e.get('intents') or []} for e in b.get('enemies') or []],
        'hand': [{'index': c.get('index'), 'name': c.get('name'),
                  'can_play': c.get('can_play')} for c in _player_cards(state)],
        'selection': (state.get('hand_select') or {}).get('prompt'),
    }


def prompt(state: dict, thesis_text: str, history: str, build: str, reference_text: str = "") -> str:
    p = state.get('player') or {}
    b = state.get('battle') or {}
    r = state.get('run') or {}
    cards = [_safe_card(c) for c in _player_cards(state)]
    enemies = [{k: e.get(k) for k in ('entity_id', 'name', 'hp', 'max_hp', 'block',
                                      'status', 'intents')}
               for e in (b.get('enemies') or [])]
    core = {
        'screen': state.get('state_type'), 'act': r.get('act'), 'floor': r.get('floor'),
        'round': b.get('round'), 'turn': b.get('turn'), 'is_play_phase': b.get('is_play_phase'),
        'hp': p.get('hp'), 'max_hp': p.get('max_hp'), 'block': p.get('block'),
        'energy': p.get('energy'), 'max_energy': p.get('max_energy'), 'stars': p.get('stars'),
        'status': p.get('status') or [], 'orbs': p.get('orbs') or [],
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
            "later steps. Never invent a card or enemy. Use the required JSON format only.")


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


def validate_response(text: str, state: dict, sig: str, run_id: str | None) -> dict:
    """Reject invalid immediate moves. Subsequent steps are clearly tentative."""
    data = _parse_json(text)
    base = {'run_id': run_id, 'signature': sig, 'status': 'unavailable',
            'steps': [], 'why': '', 'risk': '', 'warning': ''}
    if not data or not isinstance(data.get('steps'), list) or not data['steps']:
        return {**base, 'warning': 'Claude did not return a valid combat plan.'}
    cards = _player_cards(state)
    by_index = {c.get('index', i): c for i, c in enumerate(cards)}
    enemies = {e.get('entity_id'): e for e in (state.get('battle') or {}).get('enemies') or []
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
            parsed.update(card_index=idx, card_id=card.get('id'),
                          name=card.get('name'), target=target)
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
            parsed.update(slot=slot, name=potion.get('name'), target=target)
        elif action == 'end_turn' and not select:
            parsed.update(name='End turn')
        else:
            continue
        out.append(parsed)
    if not out or out[0].get('tentative'):
        return {**base, 'warning': 'No legal first action could be verified. Recheck the board.'}
    # A multi-card sequence is not guaranteed after reactive card effects.
    return {**base, 'status': 'ready', 'steps': out,
            'why': str(data.get('why') or '')[:300],
            'risk': str(data.get('risk') or '')[:220],
            'warning': 'Only step 1 is validated. Later steps are conditional and update after each action.'}
