"""Build chooser data, identity recovery and request lifecycle regression."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bridge import build_catalog
from bridge.run_memory import RunJournal, atomic_json, candidates


def state(character=None, floor=1):
    return {'state_type': 'event', 'run': {'act': 1, 'floor': floor, 'ascension': 0},
            'player': {'character': character, 'hp': 75, 'relics': []}}


class BuildCatalogTests(unittest.TestCase):
    def test_character_recognition_from_multiple_api_shapes(self):
        self.assertEqual(build_catalog.normalize_character('The Ironclad'), 'Ironclad')
        self.assertEqual(build_catalog.normalize_character('CHARACTER_NECROBINDER'), 'Necrobinder')
        self.assertEqual(build_catalog.from_state({'player': {'character': {'name': 'Regent'}}}), 'Regent')
        self.assertEqual(build_catalog.from_state({'run': {'character_id': 'THE_DEFECT'}}), 'Defect')
        self.assertEqual(build_catalog.from_state({'player': {}}), 'Unknown')

    def test_all_five_classes_have_clickable_guides_with_versioned_ranks(self):
        self.assertEqual(build_catalog.catalog()['version'], 'v0.107.1')
        for name in build_catalog.CHARACTERS:
            items = build_catalog.entries(name)
            self.assertGreaterEqual(len(items), 5)
            self.assertTrue(any(x.get('tier') == 'S' for x in items))
            self.assertEqual(candidates(name), [x['name'] for x in items])
            for row in items:
                self.assertTrue(row['url'].startswith('https://'))
                self.assertTrue(row['secondary_url'].startswith('https://'))
        self.assertEqual(candidates('Unknown'), [])

    def test_unknown_character_can_be_selected_manually_without_reset(self):
        with tempfile.TemporaryDirectory() as td:
            j = RunJournal(td)
            self.assertTrue(j.observe(state(character=None)))
            id_ = j.run_id
            self.assertEqual(j.active['character'], 'Unknown')
            atomic_json(j.choice_path, {'run_id': id_, 'character': 'Ironclad',
                                        'build': 'Exhaust synergy'})
            self.assertTrue(j.accept_build_choice())
            self.assertEqual(j.active['character'], 'Ironclad')
            self.assertEqual(j.active['character_source'], 'manual')
            self.assertFalse(j.observe(state(character=None)))
            self.assertEqual(j.run_id, id_)
            self.assertFalse(j.observe(state(character='The Ironclad')))
            self.assertEqual(j.run_id, id_)
            self.assertEqual(j.build, 'Exhaust synergy')

    def test_discovered_real_character_corrects_wrong_manual_selection(self):
        with tempfile.TemporaryDirectory() as td:
            j = RunJournal(td)
            j.observe(state(character=None))
            id_ = j.run_id
            atomic_json(j.choice_path, {'run_id': id_, 'character': 'Silent',
                                        'build': 'Poison'})
            self.assertTrue(j.accept_build_choice())
            self.assertFalse(j.observe(state(character='The Ironclad')))
            self.assertEqual(j.run_id, id_)
            self.assertEqual(j.active['character'], 'Ironclad')
            self.assertEqual(j.build, '')

    def test_cancelled_request_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            j = RunJournal(td)
            j.observe(state(character=None))
            atomic_json(j.request_path, {'run_id': j.run_id, 'request_id': 'req001',
                                         'character': 'Silent'})
            atomic_json(j.cancel_path, {'run_id': j.run_id, 'request_id': 'req001'})
            self.assertIsNone(j.build_request())
            atomic_json(j.request_path, {'run_id': j.run_id, 'request_id': 'req002',
                                         'character': 'Silent'})
            self.assertEqual(j.build_request()['request_id'], 'req002')
            self.assertIsNone(j.build_request())

    def test_cannot_assign_unrelated_class_when_game_knows_identity(self):
        with tempfile.TemporaryDirectory() as td:
            j = RunJournal(td)
            j.observe(state(character='The Ironclad'))
            atomic_json(j.choice_path, {'run_id': j.run_id, 'character': 'Silent',
                                        'build': 'Poison'})
            self.assertFalse(j.accept_build_choice())
            self.assertEqual(j.active['character'], 'Ironclad')


if __name__ == '__main__':
    unittest.main()
