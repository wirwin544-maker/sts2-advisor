"""Offline regression tests. No real game or Claude account required."""
from __future__ import annotations

import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from bridge import combat
from bridge.run_memory import RunJournal, atomic_json
from bridge.worker import AdviceWorker
from overlay.overlay import format_combat


def game_state(round=1):
    return {
        'state_type': 'monster',
        'run': {'act': 1, 'floor': 5, 'ascension': 0},
        'player': {
            'character': 'The Ironclad', 'hp': 63, 'max_hp': 80,
            'energy': 3, 'max_energy': 3, 'block': 0,
            'status': [], 'relics': [], 'potions': [],
            'hand': [
                {'index': 0, 'id': 'BASH', 'name': 'Bash', 'cost': '2',
                 'can_play': True, 'target_type': 'AnyEnemy',
                 'description': 'Deal damage. Apply vulnerable.'},
                {'index': 1, 'id': 'STRIKE_R', 'name': 'Strike', 'cost': '1',
                 'can_play': True, 'target_type': 'AnyEnemy',
                 'description': 'Deal 6 damage.'},
                {'index': 2, 'id': 'DEFEND_R', 'name': 'Defend', 'cost': '1',
                 'can_play': True, 'target_type': 'Self',
                 'description': 'Gain 5 block.'},
            ],
        },
        'battle': {'round': round, 'turn': 'player', 'is_play_phase': True,
                   'enemies': [{'entity_id': 'JAW_WORM_0', 'name': 'Jaw Worm',
                                'hp': 44, 'block': 0, 'intents': [{'label': '11'}]}]},
    }


class CombatTests(unittest.TestCase):
    def test_live_card_order_and_recheck_after_effect(self):
        state = game_state()
        sig = combat.digest(state)
        response = json.dumps({'steps': [
            {'action': 'play_card', 'card_index': 0, 'card_id': 'BASH',
             'name': 'Bash', 'target': 'JAW_WORM_0', 'reason': 'Vulnerable first'},
            {'action': 'play_card', 'card_index': 1, 'card_id': 'STRIKE_R',
             'name': 'Strike', 'target': 'JAW_WORM_0'}],
            'why': 'Damage sequence', 'risk': 'Draw changes the hand'})
        plan = combat.validate_response(response, state, sig, 'run-one')
        self.assertEqual(plan['status'], 'ready')
        self.assertEqual(len(plan['steps']), 2)
        self.assertFalse(plan['steps'][0]['tentative'])
        self.assertTrue(plan['steps'][1]['tentative'])
        status = {**combat.summary(state, sig, 'run-one'), 'status': 'active'}
        self.assertIn('NOW. [0] Bash', format_combat(status, plan))
        state['player']['hand'].pop(0)
        state['player']['energy'] = 1
        next_sig = combat.digest(state)
        self.assertNotEqual(sig, next_sig)
        status = {**combat.summary(state, next_sig, 'run-one'), 'status': 'active'}
        self.assertIn('Updating play order', format_combat(status, plan))
        self.assertNotIn('NOW. [0] Bash', format_combat(status, plan))

    def test_rejects_invalid_target_and_card(self):
        state = game_state()
        for step in (
            {'action': 'play_card', 'card_index': 9, 'name': 'Fake'},
            {'action': 'play_card', 'card_index': 0, 'card_id': 'BASH',
             'target': 'NONEXISTENT_0'},
            {'action': 'play_card', 'card_index': 0, 'card_id': 'MISMATCH',
             'target': 'JAW_WORM_0'},
        ):
            result = combat.validate_response(json.dumps({'steps': [step]}),
                                              state, combat.digest(state), 'r1')
            self.assertEqual(result['status'], 'unavailable')
        state['player']['hand'][0]['can_play'] = False
        result = combat.validate_response(json.dumps({'steps': [
            {'action': 'play_card', 'card_index': 0, 'card_id': 'BASH',
             'target': 'JAW_WORM_0'}]}), state, combat.digest(state), 'r1')
        self.assertEqual(result['status'], 'unavailable')

    def test_state_hash_updates_with_relic_effect(self):
        state = game_state()
        original = combat.digest(state)
        state['player']['block'] = 4
        self.assertNotEqual(original, combat.digest(state))
        original = combat.digest(state)
        state['battle']['enemies'][0]['intents'][0]['label'] = '15'
        self.assertNotEqual(original, combat.digest(state))


class JournalTests(unittest.TestCase):
    def test_run_survives_restart_and_archives_each_run(self):
        with tempfile.TemporaryDirectory() as td:
            state = game_state()
            state['run']['floor'] = 1
            journal = RunJournal(td)
            self.assertTrue(journal.observe(state))
            first = journal.run_id
            journal.append('decision', screen='card_reward', advice='Take Shrug It Off')
            self.assertIn('Take Shrug', journal.format_for_prompt())
            restarted = RunJournal(td)
            self.assertFalse(restarted.observe(state))
            self.assertEqual(first, restarted.run_id)
            state['run']['floor'] = 15
            restarted.observe(state)
            state['run']['floor'] = 1
            self.assertTrue(restarted.observe(state))
            self.assertNotEqual(first, restarted.run_id)
            self.assertTrue((Path(td) / 'runs' / first / 'transcript.jsonl').exists())

    def test_build_selected_and_gameover_not_reset(self):
        with tempfile.TemporaryDirectory() as td:
            journal = RunJournal(td)
            state = game_state()
            journal.observe(state)
            runid = journal.run_id
            atomic_json(journal.choice_path, {'run_id': runid, 'build': 'Exhaust synergy'})
            self.assertTrue(journal.accept_build_choice())
            self.assertIn('Exhaust synergy', journal.format_for_prompt())
            state['state_type'] = 'game_over'
            self.assertFalse(journal.observe(state))
            journal.finish('Defeat')
            self.assertFalse(journal.observe(state))
            state['state_type'] = 'event'
            state['run']['floor'] = 1
            self.assertTrue(journal.observe(state))
            self.assertNotEqual(runid, journal.run_id)


class WorkerTests(unittest.TestCase):
    def test_stale_advice_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            journal = RunJournal(td)
            state = game_state()
            journal.observe(state)
            logger = logging.getLogger('test_worker')
            class SlowModel:
                def advise(self, payload, alias, mode='strategy'):
                    time.sleep(.15)
                    return json.dumps({'steps': [{'action': 'end_turn'}]})
            thesis = MagicMock()
            worker = AdviceWorker(SlowModel(), thesis, str(Path(td)/'advice.txt'),
                                  logger, journal, str(Path(td)/'plan.json'))
            worker.start()
            sig = 'combat:' + combat.digest(state)
            worker.request(sig, 'test', 'sonnet', 'combat', journal.run_id, state)
            time.sleep(.05)
            worker.invalidate('combat:changed')
            time.sleep(.25)
            worker.stop()
            self.assertFalse((Path(td)/'plan.json').exists())


if __name__ == '__main__':
    unittest.main()
