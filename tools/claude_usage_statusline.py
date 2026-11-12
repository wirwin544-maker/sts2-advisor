"""Claude Code interactive statusLine listener for the Spire Oracle overlay.

Claude Code launches this command with statusLine JSON on standard input.
Only two quota windows are saved locally. No API calls, tokens, or OAuth access.
Run `python tools/install_usage_statusline.py` once to opt in.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bridge.usage import save_statusline_snapshot, load_snapshot  # noqa: E402


def main() -> int:
    try:
        obj = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    output = ROOT / 'runtime' / 'claude_usage.json'
    try:
        saved = save_statusline_snapshot(obj, output)
        if saved:
            # Preserve a useful local Claude Code status line, too.
            recorded = load_snapshot(output).get('windows', {})
            pieces = []
            for key, label in (('five_hour', '5h'), ('seven_day', '7d')):
                info = recorded.get(key) or {}
                if 'used_percentage' in info:
                    pieces.append(f"{label} {info['used_percentage']:g}%")
            if pieces:
                print('Spire Oracle usage: ' + ' | '.join(pieces))
    except OSError:
        return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())