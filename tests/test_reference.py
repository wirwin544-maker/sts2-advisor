"""Reference importer, read-only moveset lookup, and pause state tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from bridge import combat, control
from bridge.monster_reference import MonsterReference
from bridge.reference_search import ReferenceLibrary
from data.import_reference import build_monster_index
from overlay.overlay import Overlay


class ReferenceTests(unittest.TestCase):
    def test_enemy_move_patterns_preserved_and_matched(self):
        sheet = [
            {'row': 1, 'cells': {'A': {'value': 'Monster Name'}}},
            {'row': 2, 'cells': {'A': {'value': 'Axebot'}, 'B': {'value': '70 - 78'},
                                  'C': {'value': 'Boot Up'}, 'D': {'value': 'One-Two'},
                                  'J': {'value': 'Alternates with Uppercut.'}}},
            {'row': 3, 'cells': {'C': {'value': 'Block 15'},
                                  'D': {'value': 'Damage 10x2'},
                                  'I': {'value': 'Starts with Stock 2'}}},
            {'row': 6, 'cells': {'A': {'value': 'Another Monster'},
                                  'B': {'value': '30'},
                                  'C': {'value': 'Bite'}}},
            {'row': 7, 'cells': {'C': {'value': 'Damage 9'}}},
        ]
        data = build_monster_index({'game_version': 'v0.111.0',
                                    'imported_utc': 'today',
                                    'sheets': {'Monsters': sheet}})
        self.assertEqual(len(data['entries']), 2)
        ref = MonsterReference(data['entries'], data['source_version'])
        state = {'state_type': 'monster', 'battle': {'enemies': [
            {'name': 'Axebot', 'entity_id': 'AXEBOT_0'},
            {'name': 'Unlisted', 'entity_id': 'UNLISTED_0'}]}}
        results = ref.encounter(state)
        self.assertEqual(results[0]['reference']['name'], 'Axebot')
        self.assertIsNone(results[1]['reference'])
        hint = ref.prompt_for_battle(state)
        self.assertIn('Damage 10x2', hint)
        self.assertIn('Alternates with Uppercut', hint)
        self.assertIn('LIVE ENEMY INTENTS', hint)
        self.assertIn('no exact unambiguous reference match', hint)
        self.assertIn('ENEMY MOVESET REFERENCE', combat.prompt(state, '', '', '', hint))

    def test_ambiguous_names_are_not_falsely_matched(self):
        ref = MonsterReference([{'name': 'Slime', 'kind': 'monster'},
                                {'name': 'Slime', 'kind': 'monster'}])
        self.assertIsNone(ref.lookup('Slime'))
        self.assertIsNone(ref.lookup('Slime', 'monster'))

    def test_full_reference_retrieval_for_events(self):
        library = ReferenceLibrary({'Events': [
            {'row': 5, 'cells': {'A': {'value': 'Aroma of Chaos'},
                                  'B': {'value': 'Let Go'},
                                  'C': {'value': 'Transform a card.'}}}]}, 'v0.111.0')
        state = {'state_type': 'event', 'event': {'name': 'Aroma of Chaos',
            'options': [{'index': 0, 'title': 'Let Go', 'description': 'Transform a card.'}]}}
        prompt = library.context_for_screen(state, 'event')
        self.assertIn('Transform a card.', prompt)
        self.assertIn('Events row 5', prompt)
        self.assertEqual(library.search('nonexistent'), [])


class PauseTests(unittest.TestCase):
    def test_pause_toggle_updates_shared_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'control.json'
            view = Overlay.__new__(Overlay)
            view.control_path = path
            view._paused = False
            view.pause_button = MagicMock()
            view._set_text = MagicMock()
            view._toggle_pause()
            self.assertTrue(control.is_paused(path))
            view.pause_button.configure.assert_called()
            view._toggle_pause()
            self.assertFalse(control.is_paused(path))
            self.assertEqual(json.loads(path.read_text())['paused'], False)


if __name__ == '__main__':
    unittest.main()
