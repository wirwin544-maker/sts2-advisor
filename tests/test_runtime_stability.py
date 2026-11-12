"""Regression tests for orb flicker, Windows runtime-file races, duplicate launches."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from bridge.combat import OrbStabilizer, summary
from bridge.run_memory import RunJournal, atomic_json, candidates
from bridge.single_instance import claim_instance
from overlay.overlay import format_combat


def orb(name, evoke=8):
    return {'name': name, 'id': name.upper(), 'passive_val': 2, 'evoke_val': evoke}


class OrbTests(unittest.TestCase):
    def test_unconfirmed_change_holds_last_verified_orb(self):
        tracker = OrbStabilizer(required=3)
        initial = [orb('Frost', 5), orb('Dark', 24)]
        changed = [orb('Lightning', 8), orb('Frost', 5)]
        self.assertFalse(tracker.observe(initial))
        self.assertFalse(tracker.observe(initial))
        self.assertTrue(tracker.observe(initial))
        self.assertEqual(tracker.confirmed, initial)
        self.assertFalse(tracker.observe(changed))
        self.assertEqual(tracker.confirmed, initial)
        self.assertTrue(tracker.observe(initial))
        self.assertEqual(tracker.confirmed, initial)
        self.assertFalse(tracker.observe(changed))
        self.assertFalse(tracker.observe(changed))
        self.assertTrue(tracker.observe(changed))
        self.assertEqual(tracker.confirmed, changed)

    def test_missing_orb_data_cannot_discard_confirmed_queue(self):
        tracker = OrbStabilizer(required=2)
        self.assertFalse(tracker.observe([orb('Dark')]))
        self.assertTrue(tracker.observe([orb('Dark')]))
        self.assertFalse(tracker.observe(None))
        self.assertEqual(tracker.confirmed[0]['name'], 'Dark')
        self.assertTrue(tracker.observe([orb('Dark')]))

    def test_unstable_orb_state_hides_preexisting_plan(self):
        state = {'state_type': 'monster', 'run': {'act': 1, 'floor': 2},
                 'battle': {'round': 1, 'enemies': []},
                 'player': {'orbs': [orb('Frost')]}}
        status = {**summary(state, 'combat:example', 'run1'),
                  'status': 'waiting', 'orb_read_stable': False}
        plan = {'status': 'ready', 'run_id': 'run1', 'signature': 'combat:example',
                'steps': [{'action': 'end_turn'}]}
        text = format_combat(status, plan)
        self.assertIn('ORB STATE UNVERIFIED', text)
        self.assertIn('suspended', text)
        self.assertNotIn('NEXT EVOKE', text)
        self.assertNotIn('End turn', text)


class RuntimeWriteTests(unittest.TestCase):
    def test_parallel_atomic_writers_do_not_share_temp_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'active_run.json'
            errors = []
            def write(n):
                try:
                    for i in range(15):
                        atomic_json(path, {'worker': n, 'index': i})
                except Exception as error:
                    errors.append(error)
            threads = [threading.Thread(target=write, args=(i,)) for i in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertIsInstance(json.loads(path.read_text()), dict)
            self.assertEqual(list(Path(folder).glob('.active_run.json.*.tmp')), [])

    def test_unchanged_build_choice_does_not_rewrite_active_run(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = RunJournal(folder)
            build = candidates('ironclad')[0]
            journal.active = {'run_id': 'test', 'character': 'ironclad',
                              'build': build, 'status': 'active'}
            journal._save_active()
            atomic_json(journal.choice_path,
                        {'run_id': 'test', 'character': 'ironclad', 'build': build})
            initial = journal.active_path.read_bytes()
            calls = []
            journal._save_active = lambda: calls.append(True)
            for _ in range(5):
                self.assertFalse(journal.accept_build_choice())
            self.assertEqual(calls, [])
            self.assertEqual(journal.active_path.read_bytes(), initial)

    def test_single_instance_socket_rejects_second_bridge(self):
        owner = claim_instance(0)
        self.assertIsNotNone(owner)
        port = owner.getsockname()[1]
        try:
            self.assertIsNone(claim_instance(port))
        finally:
            owner.close()
        retry = claim_instance(port)
        self.assertIsNotNone(retry)
        retry.close()


if __name__ == '__main__':
    unittest.main()
