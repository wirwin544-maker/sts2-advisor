"""Regression coverage for numeric orb changes without queue replacement."""
import unittest
from bridge.combat import OrbStabilizer, summary
from overlay.overlay import format_combat


def orb(id, evoke):
    return {'id': id, 'name': id.title(), 'passive_val': 2, 'evoke_val': evoke}


class OrbIdentityTests(unittest.TestCase):
    def setUp(self):
        self.time = [0.0]
        self.s = OrbStabilizer(required=3, value_required=2, quiet_seconds=1,
                               clock=lambda: self.time[0])
        self.start = [orb('FROST', 5), orb('DARK', 18)]
        for t in (0., .3, .6, 1.05):
            self.time[0] = t
            self.s.observe(self.start)
        self.assertTrue(self.s.observe(self.start))

    def test_dark_value_changing_does_not_change_layout(self):
        newer = [orb('FROST', 5), orb('DARK', 24)]
        for t in (2., 2.3, 2.6):
            self.time[0] = t
            self.assertFalse(self.s.observe(newer))
            self.assertEqual(self.s.confirmed, self.start)
        self.time[0] = 3.05
        self.assertTrue(self.s.observe(newer))
        self.assertEqual(self.s.confirmed, newer)

    def test_one_bad_sample_does_not_change_display(self):
        newer = [orb('FROST', 5), orb('DARK', 24)]
        self.time[0] = 2.
        self.assertFalse(self.s.observe(newer))
        self.time[0] = 2.3
        self.assertFalse(self.s.observe(self.start))
        self.assertEqual(self.s.confirmed, self.start)
        self.time[0] = 3.05
        self.assertTrue(self.s.observe(self.start))
        self.assertEqual(self.s.confirmed, self.start)

    def test_reorder_requires_quiet_window(self):
        switched = list(reversed(self.start))
        for t in (2., 2.3, 2.6):
            self.time[0] = t
            self.assertFalse(self.s.observe(switched))
            self.assertEqual(self.s.confirmed, self.start)
        self.time[0] = 3.05
        self.assertTrue(self.s.observe(switched))
        self.assertEqual(self.s.confirmed, switched)

    def test_missing_orb_field_never_clears_confirmed(self):
        self.time[0] = 2.
        self.assertFalse(self.s.observe(None))
        self.assertEqual(self.s.confirmed, self.start)

    def test_hover_text_does_not_count_as_orb_change(self):
        self.time[0] = 2.
        updated = [dict(x, description='another text') for x in self.start]
        self.assertTrue(self.s.observe(updated))
        self.assertEqual(self.s.confirmed, self.start)

    def test_pending_display_keeps_last_known_orbs_and_hides_old_plan(self):
        state = {'state_type':'monster', 'run':{'floor':1, 'act':1},
                 'battle':{'round':1,'enemies':[]},
                 'player':{'orbs':self.start}}
        status = {**summary(state,'combat:123','run'), 'status':'waiting', 'orb_read_stable':False}
        text = format_combat(status, {'signature':'combat:123', 'run_id':'run',
                                      'status':'ready','steps':[{'action':'end_turn'}]})
        self.assertIn('ORBS LEFT → RIGHT: Dark (18 evoke) | Frost (5 evoke)', text)
        self.assertIn('rightmost Frost', text)
        self.assertIn('advice paused', text)
        self.assertNotIn('ORB STATE UNVERIFIED', text)
        self.assertNotIn('End turn', text)


if __name__ == '__main__':
    unittest.main()
