"""Regression tests for independent pause controls and no-choice map suppression."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from bridge import control, screens, signature
from overlay.overlay import Overlay, format_combat


class PauseFlagTests(unittest.TestCase):
    def _view(self, path: Path):
        view = Overlay.__new__(Overlay)
        view.control_path = path
        view.pause_button = MagicMock()
        view.battle_pause_button = MagicMock()
        view._set_text = MagicMock()
        view._paused = False
        view._battle_paused = False
        return view

    def test_missing_corrupt_and_old_control_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'control.json'
            self.assertEqual(control.pause_flags(p), (False, False))
            p.write_text('{corrupted', encoding='utf-8')
            self.assertEqual(control.pause_flags(p), (False, False))
            p.write_text('{"paused":true}', encoding='utf-8')
            self.assertEqual(control.pause_flags(p), (True, False))
            self.assertTrue(control.is_paused(p))
            self.assertFalse(control.is_battle_paused(p))

    def test_battle_pause_independent_of_total_pause(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'control.json'
            view = self._view(p)
            view._toggle_battle_pause()
            self.assertEqual(control.pause_flags(p), (False, True))
            self.assertTrue(view._battle_paused)
            view.battle_pause_button.configure.assert_called()
            view._toggle_pause()
            self.assertEqual(control.pause_flags(p), (True, True))
            view._toggle_pause()
            self.assertEqual(control.pause_flags(p), (False, True))
            view._toggle_battle_pause()
            self.assertEqual(control.pause_flags(p), (False, False))

    def test_pause_state_survives_new_overlay_and_preserves_other_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'control.json'
            p.write_text(json.dumps({'paused': False, 'custom': 42}), encoding='utf-8')
            view = self._view(p)
            view._toggle_battle_pause()
            self.assertEqual(json.loads(p.read_text())['custom'], 42)
            self.assertEqual(control.pause_flags(p), (False, True))
            new_view = self._view(p)
            new_view._toggle_pause()
            self.assertEqual(control.pause_flags(p), (True, True))

    def test_battle_paused_never_displays_prior_combat_plan(self):
        status = {'status': 'paused_battle', 'act': 1, 'floor': 5,
                  'round': 1, 'hp': 20, 'max_hp': 50, 'block': 0,
                  'energy': 2, 'max_energy': 3, 'enemies': [],
                  'signature': 'current', 'run_id': 'run-1'}
        old_plan = {'signature': 'current', 'run_id': 'run-1', 'status': 'ready',
                    'steps': [{'action': 'play_card', 'name': 'Strike', 'card_index': 0}],
                    'why': 'Old result should not appear'}
        rendered = format_combat(status, old_plan)
        self.assertIn('BATTLE SUGGESTIONS PAUSED', rendered)
        self.assertNotIn('Strike', rendered)
        self.assertNotIn('Old result', rendered)
        self.assertIn('Non-combat advice remains enabled', rendered)


class AutomaticMapTests(unittest.TestCase):
    @staticmethod
    def _state(options):
        return {'state_type': 'map', 'run': {'act': 1, 'floor': 8},
                'map': {'next_options': options}}

    def test_one_available_route_skips_model(self):
        state = self._state([{'index': 0, 'type': 'Monster', 'row': 8, 'col': 1}])
        msg = screens.automatic_map_message(state)
        self.assertIn('Only one available route: Monster', msg)
        self.assertIn('No AI suggestion needed', msg)
        self.assertEqual(len(screens.extract_options(state, 'map')), 1)

    def test_multiple_routes_still_request_advice(self):
        state = self._state([{'index': 0, 'type': 'Monster', 'col': 0},
                             {'index': 1, 'type': 'Elite', 'col': 1}])
        self.assertIsNone(screens.automatic_map_message(state))
        self.assertEqual(len(screens.extract_options(state, 'map')), 2)

    def test_empty_map_options_defer_advice(self):
        self.assertIn('Waiting', screens.automatic_map_message(self._state([])))
        self.assertIsNone(screens.automatic_map_message({'state_type': 'map', 'map': {}}))
        self.assertIsNone(screens.automatic_map_message({'state_type': 'event',
                                                          'map': {'next_options': [1]}}))

    def test_signature_changes_when_a_fork_appears(self):
        start = self._state([{'index': 0, 'type': 'Monster', 'row': 8, 'col': 1}])
        s1 = signature.build(start, 'map')
        start['map']['next_options'].append({'index': 1, 'type': 'Elite', 'row': 8, 'col': 2})
        s2 = signature.build(start, 'map')
        self.assertNotEqual(s1, s2)
        self.assertIsNone(screens.automatic_map_message(start))


if __name__ == '__main__':
    unittest.main()
