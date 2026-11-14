"""Slay the Spire 2 public-beta v0.113.0 decision and patch-note grounding.

This is not a compiled-game compatibility guarantee. Live MCP state always wins;
old workbook contents are treated as historical. No code sends game actions.
"""
from __future__ import annotations

import re
from typing import Any

TARGET_VERSION = '0.113.0'
STEAM_BUILD_ID = '26625880'
RELEASE_DATE = '2026-11-12'
PATCH_SOURCE = 'https://store.steampowered.com/news/app/2868840/view/708914333639245837'

# Only facts supported by the official release notes. These replace specific
# v0.111.0 spreadsheet claims, never the current enemy intent.
PATCH_FACTS: dict[str, str] = {
    'infested prism': 'v0.113.0: Radiate REMOVED. Pattern is Jab, Jab, Whirlwind, Pulsate. Pulsate applies 1 Vulnerable instead of gaining 20/22 Block.',
    'axebot': 'v0.113.0: HP is fixed at 70, or 80 at Ascension 8+, rather than the former HP range. LIVE HP overrides.',
    'tunneler': 'v0.113.0: Attack from Below renamed From Below; damage 24, or 28 at Ascension 9+ (before live modifiers).',
    'expect a fight': 'v0.113.0: Gain 15(20) Block. Attacks in hand cost 1 less Energy until played. Old Strength-scaling description is obsolete.',
    'forgotten ritual': 'v0.113.0: Gain 3(4) Energy only if a card was Exhausted this turn.',
    'expertise': 'v0.113.0: Draw 2(3) cards; Retain your hand this turn, not only the drawn cards.',
    'memento mori': 'v0.113.0: Cost 3, Sly; deal 19(23) damage to lowest-HP enemy, not a discard-scaling attack.',
    'speedster': 'v0.113.0: Base damage 3 instead of 2.',
    'phantom blades': 'v0.113.0: Additional Shiv damage 8(11), down from 9(12).',
    'charge!!': 'v0.113.0: Minion Dive Bomb damage 11(13), down from 13(16).',
    'salvo': 'v0.113.0: Damage 10(14), down from 12(16).',
    'ringing triangle': 'v0.113.0: Retain your hand at start of combat; stacks with other Retain Hand.',
    'brilliant scarf': 'v0.113.0: The SIXTH card from hand each turn is free, not the fifth.',
    'dowsing rod': 'v0.113.0: Dowsing transforms after FOUR question-mark rooms; transforming room cannot be a combat.',
    'doors of light and dark': 'v0.113.0: Light Door upgrades ONE chosen card, not two random cards.',
    'zen weaver': 'v0.113.0: Breathing Techniques costs 25 Gold and adds ONE Enlightenment without Exhaust.',
    'waterlogged scriptorium': 'v0.113.0: Prickly Sponge price is 120 Gold, not 99.',
    'power cell': 'v0.113.0: Prefers zero-cost cards without Innate before Innate ones.',
    'ceremonial beast': 'v0.113.0: When stunned by effects such as Thorns during Plow, does not regain Strength at end of move.',
}
NEW_EVENTS = ('Waterfall of Obvious Secrets', 'Wuppy in Trouble', 'Museum of Torture',
              'Shrine of the Warlord', 'Thermae Nonupeipe')


def _normalize(value: object) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(value or '').casefold()).strip()


def mode_from_state(state: dict, override: str = 'auto') -> str:
    """Read known mode fields if exposed; never infer a mode from absence of a map."""
    if isinstance(override, str) and override.lower() in {'blitz','dread','standard'}:
        return override.lower()
    run = state.get('run') if isinstance(state.get('run'), dict) else {}
    for src in (run, state):
        if not isinstance(src, dict):
            continue
        for key in ('game_mode','run_mode','mode','gameMode'):
            raw = src.get(key)
            if not isinstance(raw, str):
                continue
            token = _normalize(raw)
            if 'blitz' in token: return 'blitz'
            if 'dread' in token: return 'dread'
            if token in ('standard','normal','classic','singleplayer'): return 'standard'
    return 'unknown'


def relevant_patch_facts(state: dict, max_items: int = 7) -> list[str]:
    """Context-sensitive patch deltas for visible cards, enemies, relics and events."""
    values = []
    def take(items: Any):
        if isinstance(items, dict):
            values.extend(str(items.get(k) or '') for k in ('name','id','title','label','description'))
        elif isinstance(items, list):
            for row in items: take(row)
    for source in (state.get('battle'), state.get('player'), state.get('event'),
                   state.get('shop'), state.get('card_reward'), state.get('card_select'),
                   state.get('relic_select'), state.get('ancient'), state.get('rest_site')):
        take(source)
    # Check structured nested options, hand, enemies, relics.
    for holder in (state, state.get('battle') or {}, state.get('player') or {},
                   state.get('shop') or {}, state.get('event') or {},
                   state.get('card_reward') or {}, state.get('card_select') or {}):
        if isinstance(holder, dict):
            for k in ('enemies','hand','relics','cards','items','options','status'):
                take(holder.get(k))
    blob = _normalize(' '.join(values))
    found = []
    for key, fact in PATCH_FACTS.items():
        if re.search(r'(?<!\w)' + re.escape(_normalize(key)) + r'(?!\w)', blob):
            found.append(fact)
        if len(found) >= max_items: break
    return found


def contextual_advice(state: dict, *, override_mode: str = 'auto') -> str:
    """Small official-patch correction attached to every Claude prompt."""
    mode = mode_from_state(state, override_mode)
    lines = [
        f'GAME PATCH: Slay the Spire 2 PUBLIC BETA v{TARGET_VERSION} ({RELEASE_DATE}).',
        'The imported monster/event workbook is v0.111.0 and may be outdated.',
        'LIVE card text, enemy intents, game-state rules and selectable options override all historical reference claims.',
    ]
    if mode == 'blitz':
        lines.append('MODE: BLITZ. No normal map and Gold does not matter. Do not offer map paths, shop purchases based on Gold or normal-run route optimization. Choose among LIVE options.')
    elif mode == 'dread':
        lines.append('MODE: DREAD. All ascension modifiers apply; bosses are stronger and buff enemies in their act; curses accumulate. Prioritize survival and curse mitigation.')
    elif mode == 'unknown':
        lines.append('MODE: unconfirmed by STS2MCP. Do not assume Standard, Blitz, or Dread mechanics from a missing field.')
    else:
        lines.append('MODE: Standard (as reported by game or configured override).')
    character = (state.get('player') or {}).get('character') or (state.get('run') or {}).get('character')
    if character and 'fool' in str(character).casefold():
        lines.append('THE FOOL: Aim empowers Arrow shots; an Impaled enemy can release an Arrow after sufficient follow-up hits; Melodies interact with Wah/Cho/Ki cards. Track actual Arrow availability, Aim and Impale from LIVE state; never assume a Shot is possible without an Arrow.')
    lines.extend(relevant_patch_facts(state))
    if mode == 'blitz':
        lines.append('Ignore any v0.111.0 spreadsheet rows suggesting Standard-mode map routes or Gold shopping.')
    return '\n'.join(lines)


def monster_patch(name: str) -> str:
    return PATCH_FACTS.get(_normalize(name), '')
