"""Regression for per-fight battle pause persistence and worker fail-closed gating."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock

from bridge import control
from bridge.worker import AdviceWorker


class CountingModel:
    def __init__(self, block=False):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()

    def advise(self, payload, alias, mode='strategy'):
        self.calls += 1
        self.started.set()
        self.release.wait(3)
        return json.dumps({'steps': [], 'why': 'test'})


class BattlePausePersistenceTests(unittest.TestCase):
    def test_pause_gate_persists_across_combat_screens_and_transient_io(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'control.json'
            gate = control.PauseGate(path)
            self.assertTrue(gate.allows('combat'))
            path.write_text('{"paused":false,"battle_paused":true}', encoding='utf-8')
            self.assertEqual(gate.flags(), (False, True))
            for floor in (2, 5, 9, 19):
                for kind in ('monster', 'elite', 'boss', 'hand_select'):
                    self.assertTrue(control.is_combat_screen({'state_type':kind, 'run':{'floor':floor}}))
                    self.assertFalse(gate.allows('combat'))
                # Non-combat decisions must keep working while battle is paused.
                self.assertTrue(gate.allows('strategy'))
            path.write_text('{"paused":false,"battle_paused":', encoding='utf-8')
            self.assertFalse(gate.allows('combat'))  # partial OneDrive read
            path.unlink()
            self.assertFalse(gate.allows('combat'))  # missing transient file
            path.write_text('{"paused":false,"battle_paused":false}', encoding='utf-8')
            self.assertTrue(gate.allows('combat'))   # explicit Resume Battle

    def test_noncombat_card_select_not_blocked_and_incombat_selection_blocked(self):
        self.assertFalse(control.is_combat_screen({'state_type':'card_select', 'card_select':{}}))
        self.assertTrue(control.is_combat_screen({'state_type':'card_select', 'battle':{}}))

    def test_worker_refuses_any_combat_jobs_for_multiple_fights_until_resumed(self):
        with tempfile.TemporaryDirectory() as td:
            dir = Path(td)
            path = dir/'control.json'
            gate = control.PauseGate(path)
            model = CountingModel()
            worker = AdviceWorker(model, MagicMock(), str(dir/'advice.txt'),
                                  logging.getLogger('test-pauses'),
                                  combat_file=str(dir/'combat_plan.json'), pause_gate=gate)
            worker.start()
            try:
                path.write_text('{"paused":false,"battle_paused":true}', encoding='utf-8')
                for i in range(5):
                    self.assertFalse(worker.request(f'combat:fight{i}', 'prompt', 'sonnet',
                                                     'combat', run_id='run', state={}))
                time.sleep(0.08)
                self.assertEqual(model.calls, 0)
                self.assertFalse((dir/'combat_plan.json').exists())
                self.assertTrue(worker.request('map:one', 'noncombat prompt', 'sonnet',
                                               'strategy', run_id='run'))
                self.assertTrue(model.started.wait(2))
                path.write_text('{"paused":false,"battle_paused":false}', encoding='utf-8')
                self.assertTrue(worker.request('combat:fight6', 'prompt', 'sonnet',
                                               'combat', run_id='run', state={}))
            finally:
                worker.stop()
            self.assertGreaterEqual(model.calls, 1)

    def test_inflight_model_response_discarded_on_battle_pause(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            path=d/'control.json'
            path.write_text('{"paused":false,"battle_paused":false}', encoding='utf-8')
            gate=control.PauseGate(path)
            model=CountingModel(block=True)
            worker=AdviceWorker(model, MagicMock(), str(d/'advice.txt'),
                                logging.getLogger('test-inflight'),
                                combat_file=str(d/'combat_plan.json'), pause_gate=gate)
            worker.start()
            try:
                self.assertTrue(worker.request('combat:fight1', 'prompt', 'sonnet', 'combat',
                                               run_id='run', state={}))
                self.assertTrue(model.started.wait(2))
                path.write_text('{"paused":false,"battle_paused":true}', encoding='utf-8')
                model.release.set()
                time.sleep(0.2)
                self.assertFalse((d/'combat_plan.json').exists())
                self.assertEqual(model.calls, 1)
            finally:
                model.release.set()
                worker.stop()

    def test_all_pause_blocks_all_requests_even_when_battle_pause_off(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'control.json'
            path.write_text('{"paused":true,"battle_paused":false}', encoding='utf-8')
            gate=control.PauseGate(path)
            self.assertFalse(gate.allows('combat'))
            self.assertFalse(gate.allows('strategy'))
            self.assertFalse(gate.allows('build'))


if __name__ == '__main__':
    unittest.main()
