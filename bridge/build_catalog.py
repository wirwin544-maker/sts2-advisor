"""Static, version-labelled community archetypes for the offline build chooser.

No live scraping or opaque AI-made rankings. Card and build tier sources may
change on later StS2 patches and should be rechecked before updating catalog.
"""
from __future__ import annotations
import json
import re
from functools import lru_cache
from . import util

CHARACTERS = ('Ironclad', 'Silent', 'Defect', 'Regent', 'Necrobinder')


def normalize_character(value) -> str:
    """Canonical character ID from known STS2MCP field shapes."""
    if isinstance(value, dict):
        for key in ('name', 'id', 'character', 'character_id', 'class', 'display_name'):
            found = normalize_character(value.get(key))
            if found != 'Unknown':
                return found
        return 'Unknown'
    if not isinstance(value, str):
        return 'Unknown'
    clean = re.sub(r'[^a-z]', '', value.casefold())
    for name in CHARACTERS:
        if name.casefold() in clean:
            return name
    return 'Unknown'


def from_state(state: dict) -> str:
    p = state.get('player') or {}
    r = state.get('run') or {}
    if not isinstance(p, dict): p = {}
    if not isinstance(r, dict): r = {}
    for source in (p, r, state):
        for key in ('character','character_id','class','player_class','character_name'):
            result = normalize_character(source.get(key))
            if result != 'Unknown':
                return result
    return 'Unknown'


@lru_cache(maxsize=1)
def catalog() -> dict:
    try:
        path = util.resolve('data/build_catalog.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data.get('characters'),dict):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {'characters': {}}


def entries(character: str) -> list[dict]:
    key = normalize_character(character).lower()
    found = catalog().get('characters', {}).get(key)
    return found if isinstance(found,list) else []


def names(character: str) -> list[str]:
    return [row['name'] for row in entries(character) if isinstance(row,dict) and isinstance(row.get('name'),str)]


def details_for_prompt(character: str) -> str:
    lines = []
    for entry in entries(character):
        lines.append(f"- {entry['name']} [source tier {entry['tier']}]: {entry.get('description','')} | Core cards: {', '.join(entry.get('core_cards', []))}")
    return '\n'.join(lines)
