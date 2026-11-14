"""Offline Claude quota snapshot, display, and setup tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bridge import usage
from tools.install_usage_statusline import install


class UsageTests(unittest.TestCase):
    def test_valid_subscription_snapshot_and_no_secrets(self):
        data = {'rate_limits': {'five_hour': {'used_percentage': 24.5, 'resets_at': 2000},
                                'seven_day': {'used_percentage': 64, 'resets_at': 9900}},
                'session_id': 'PRIVATE', 'workspace': {'project_dir': 'PRIVATE'}}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'usage.json'
            self.assertTrue(usage.save_statusline_snapshot(data, p, now=1000))
            content = p.read_text()
            self.assertNotIn('PRIVATE', content)
            result = usage.usage_text(usage.load_snapshot(p), now=1005)
            self.assertIn('24.5% used', result)
            self.assertIn('75.5% left', result)
            self.assertIn('7d: 64% used', result)
            self.assertIn('last checked 0m ago', result)
            self.assertIn('STALE', usage.usage_text(usage.load_snapshot(p), now=1801))

    def test_missing_subscription_usage_does_not_invent_values(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'usage.json'
            self.assertFalse(usage.save_statusline_snapshot({'cost': {'total_cost_usd': 5}}, p, now=1000))
            self.assertFalse(p.exists())
            self.assertIn('unavailable', usage.usage_text({}, now=1000))

    def test_expired_window_never_shown_current(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'usage.json'
            usage.save_statusline_snapshot({'rate_limits': {
                'five_hour': {'used_percentage': 99, 'resets_at': 1020},
                'seven_day': {'used_percentage': 40, 'resets_at': 5000}}}, p, now=1000)
            shown = usage.usage_text(usage.load_snapshot(p), now=1100)
            self.assertNotIn('99%', shown)
            self.assertIn('7d: 40%', shown)
            self.assertTrue('STALE' not in shown)

    def test_rejects_incorrect_pct_and_missing_reset(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'usage.json'
            self.assertFalse(usage.save_statusline_snapshot({'rate_limits': {'five_hour': {
                'used_percentage': 40}}}, p, now=1000))
            self.assertFalse(usage.save_statusline_snapshot({'rate_limits': {'five_hour': {
                'used_percentage': 110, 'resets_at': 3000}}}, p, now=1000))
            self.assertFalse(p.exists())

    def test_completed_advice_count_is_not_total_api_requests(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'transcript.jsonl'
            path.write_text('\n'.join([json.dumps({'kind': 'run_started'}),
                              json.dumps({'kind': 'exchange'}), 'broken',
                              json.dumps({'kind': 'exchange'}),
                              json.dumps({'kind': 'combat_advice'})]))
            self.assertEqual(usage.completed_advice_count(path), 2)

    def test_install_preserves_other_settings_and_refuses_replace(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / '.claude' / 'settings.json'
            cfg.parent.mkdir()
            cfg.write_text(json.dumps({'theme': 'light', 'statusLine': {
                'type': 'command', 'command': 'existing-cmd'}}))
            with self.assertRaisesRegex(ValueError, 'Refusing to replace'):
                install(cfg, Path(td) / 'listener.py', executable='python')
            self.assertEqual(json.loads(cfg.read_text())['statusLine']['command'], 'existing-cmd')
            result = install(cfg, Path(td) / 'listener.py', replace=True, executable='python')
            self.assertIn('backup:', result)
            saved = json.loads(cfg.read_text())
            self.assertEqual(saved['theme'], 'light')
            self.assertTrue(saved['statusLine']['command'].startswith('"python"'))
            self.assertTrue(list(cfg.parent.glob('settings.json.backup-spire-oracle-*')))
            self.assertEqual(install(cfg, Path(td) / 'listener.py', executable='python'), 'already installed')


if __name__ == '__main__':
    unittest.main()