"""Opt-in installation of Spire Oracle's Claude Code statusLine listener.

Does not read credentials or configure an OAuth endpoint. Existing statusLine
commands are NOT replaced unless the user explicitly supplies --replace.
Settings are backed up before writing and replaced atomically.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def install(settings_file: Path, listener_file: Path, *, replace: bool = False,
            executable: str | None = None) -> str:
    settings_file = Path(settings_file)
    existing = {}
    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as exc:
            raise ValueError(f'Claude settings are not valid JSON: {exc}') from exc
        if not isinstance(existing, dict):
            raise ValueError('Claude settings must be a JSON object')
    python_exe = str(executable or sys.executable).replace('\\', '/')
    listener_path = str(listener_file.resolve()).replace('\\', '/')
    command = f'"{python_exe}" "{listener_path}"'
    prior = existing.get('statusLine')
    if prior:
        if isinstance(prior, dict) and prior.get('command') == command:
            return 'already installed'
        if not replace:
            raise ValueError('A Claude statusLine is already configured. ' 
                'Refusing to replace it. Review your existing statusLine first; ' 
                'rerun with --replace only if you wish to change it.')
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    if settings_file.exists():
        backup = settings_file.with_name(
            'settings.json.backup-spire-oracle-' + time.strftime('%Y%m%d-%H%M%S'))
        shutil.copy2(settings_file, backup)
    else:
        backup = None
    updated = dict(existing)
    updated['statusLine'] = {'type': 'command', 'command': command}
    temp = settings_file.with_name(settings_file.name + '.spire-oracle.tmp')
    try:
        temp.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + '\n',
                        encoding='utf-8')
        os.replace(temp, settings_file)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    return f'installed; backup: {backup}' if backup else 'installed'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace', action='store_true',
                        help='Replace an existing statusLine after backing up settings')
    opts = parser.parse_args()
    settings = Path.home() / '.claude' / 'settings.json'
    listener = ROOT / 'tools' / 'claude_usage_statusline.py'
    try:
        message = install(settings, listener, replace=opts.replace)
    except (OSError, ValueError) as exc:
        print(f'Status line setup not changed: {exc}', file=sys.stderr)
        return 1
    print(f'Claude Code statusLine {message}.')
    print('Open interactive `claude`, send a message, and keep it running to refresh usage.')
    print('Oracle will show the last VERIFIED reading, with timestamp; '
          'headless `claude -p` cannot refresh account percentages directly.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())