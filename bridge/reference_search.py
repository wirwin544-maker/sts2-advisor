"""Bounded context retrieval from all locally imported spreadsheet worksheets.

All populated worksheet cells are available through `search()`. Only rows
relevant to the current decision are put into Claude prompts; sending the
entire reference workbook every turn would exceed useful context and cost.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import screens, beta_compat


def _plain(value) -> str:
    return re.sub(r'[^\w]+', ' ', str(value or '').casefold()).strip()


class ReferenceLibrary:
    def __init__(self, sheets: dict | None = None, version: str = 'unknown'):
        self.sheets = sheets or {}
        self.version = version

    @classmethod
    def load(cls, path: str | Path) -> 'ReferenceLibrary':
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            return cls(data.get('sheets', {}), data.get('game_version', 'unknown'))
        except (OSError, ValueError, TypeError):
            return cls()

    def search(self, term: str, sheets: list[str] | None = None,
               limit: int = 8) -> list[dict]:
        """Exact-ish token phrase search. Returns row locations and text."""
        query = _plain(term)
        if len(query) < 4:
            return []
        results = []
        names = sheets if sheets is not None else list(self.sheets)
        for name in names:
            for row in self.sheets.get(name, []):
                cells = row.get('cells') or {}
                for col, meta in cells.items():
                    value = str(meta.get('value') or '')
                    if query == _plain(value) or query in _plain(value):
                        results.append({'sheet': name, 'row': row['row'],
                                        'column': col, 'text': value})
                        break
                if len(results) >= limit:
                    return results
        return results

    def context_for_screen(self, state: dict, kind: str,
                           max_chars: int = 2400) -> str:
        if not self.sheets:
            return ''
        if kind == 'event':
            priorities = ['Events', 'Ancients']
        elif kind == 'ancient':
            priorities = ['Ancients', 'Events']
        elif kind == 'map':
            priorities = ['Act 1 Overgrowth', 'Act 1 Underdocks',
                          'Act 2 Hive', 'Act 3 Glory', 'MechanicsStatistics']
        else:
            priorities = ['MechanicsStatistics', 'Ancients', 'Events']
        terms = []
        for block in ('event', 'ancient', 'shop'):
            x = state.get(block) or {}
            if isinstance(x, dict):
                terms.extend(x.get(key) for key in ('title', 'name') if x.get(key))
        for opt in screens.extract_options(state, kind):
            label = opt.get('label') or opt.get('name')
            if label and not any(_plain(label) == _plain(t) for t in terms):
                terms.append(label)
        snippets = []
        seen = set()
        for term in terms[:15]:
            for hit in self.search(str(term), priorities, limit=3):
                key = (hit['sheet'], hit['row'])
                if key in seen:
                    continue
                seen.add(key)
                row = next((r for r in self.sheets.get(hit['sheet'], [])
                            if r.get('row') == hit['row']), None)
                if not row:
                    continue
                cell_text = '; '.join(f'{k}: {v.get("value")}' for k, v in
                                      row['cells'].items() if v.get('value') is not None)
                excerpt = f"[{hit['sheet']} row {hit['row']}] {cell_text}"
                if sum(len(x) for x in snippets) + len(excerpt) > max_chars:
                    break
                snippets.append(excerpt)
        if not snippets:
            return ''
        return (f'SPREADSHEET REFERENCE v{self.version} (historical; may not match v0.113.0 beta):\n'
                + '\n'.join(snippets)
                + '\nOFFICIAL V0.113.0 PATCH UPDATES: ' + '; '.join(beta_compat.relevant_patch_facts(state, 5))
                + '\nPrefer live game state for prices, lock status, current options and effects.')
