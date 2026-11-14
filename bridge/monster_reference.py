"""Conservative enemy-name matching against locally imported XLSX movesets.

Reference text is an advisory hint. Current live intent, HP and powers take
precedence. Never silently match ambiguous enemy variants to one another.
"""
from __future__ import annotations

import json
import re
from .beta_compat import monster_patch
from pathlib import Path


def normalize(name: str) -> str:
    return ''.join(c for c in str(name or '').casefold() if c.isalnum())


class MonsterReference:
    def __init__(self, entries: list[dict], source_version: str = 'unknown'):
        self.entries = entries
        self.source_version = source_version
        self.by_key = {}
        for entry in entries:
            key = normalize(entry.get('name', ''))
            if key:
                self.by_key.setdefault(key, []).append(entry)

    @classmethod
    def load(cls, path: str | Path) -> 'MonsterReference':
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            return cls(data.get('entries', []), data.get('source_version', 'unknown'))
        except (OSError, ValueError, TypeError):
            return cls([])

    def lookup(self, name: str, kind: str | None = None) -> dict | None:
        key = normalize(name)
        options = self.by_key.get(key, [])
        if kind:
            narrowed = [e for e in options if e.get('kind') == kind]
            if len(narrowed) == 1:
                return narrowed[0]
        if len(options) == 1:
            return options[0]
        return None

    def encounter(self, state: dict) -> list[dict]:
        kind = state.get('state_type')
        expected = kind if kind in {'monster', 'elite', 'boss'} else None
        result = []
        for enemy in (state.get('battle') or {}).get('enemies') or []:
            if not isinstance(enemy, dict):
                continue
            entry = self.lookup(enemy.get('name', ''), expected)
            result.append({'live_name': enemy.get('name'),
                           'entity_id': enemy.get('entity_id'),
                           'reference': entry})
        return result

    def prompt_for_battle(self, state: dict, max_chars: int = 7000) -> str:
        if not self.entries:
            return '(No local monster spreadsheet imported. Use live game state only.)'
        parts = [f'REFERENCE VERSION: {self.source_version}. '
                 'These are historical possible moves, NOT confirmed next actions. '
                 'The workbook may cover a different game version. '
                 'LIVE ENEMY INTENTS AND POWERS OVERRIDE THIS REFERENCE.']
        for found in self.encounter(state):
            name = found['live_name'] or 'Unknown'
            entry = found['reference']
            if entry is None:
                parts.append(f'Enemy {name!r}: no exact unambiguous reference match. Do not guess.')
                continue
            override = monster_patch(name)
            lines = [f'Enemy {name!r} [{entry.get("kind")}]; reference HP {entry.get("hp")}']
            if override:
                lines.append('V0.113.0 OFFICIAL PATCH OVERRIDE (supersedes contradictory spreadsheet rows): ' + override)
            for move in ([] if 'infested prism' in str(name).casefold() else entry.get('moves', [])):
                details = '; '.join(move.get('details') or [])
                lines.append(f'- {move.get("name")}: {details}' if details else f'- {move.get("name")}')
            if entry.get('patterns') and not 'infested prism' in str(name).casefold():
                lines.append('PATTERN: ' + ' '.join(entry['patterns']))
            if entry.get('notes') and not 'infested prism' in str(name).casefold():
                lines.append('NOTES: ' + ' '.join(entry['notes']))
            item = '\n'.join(lines)
            if sum(map(len, parts)) + len(item) > max_chars:
                parts.append('(Additional reference notes omitted to limit token use.)')
                break
            parts.append(item)
        return '\n\n'.join(parts)
