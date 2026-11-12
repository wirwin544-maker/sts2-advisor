"""Claude Code subscription usage snapshot handling.

The only supported source of *actual account utilization* here is Claude
Code's interactive statusLine JSON, which includes rate_limits for eligible
subscription accounts after a response. Oracle's `claude -p` subprocess does
not expose these percentages; do not infer them from local requests/tokens.

Never store credentials, entire statusLine payloads, or session identifiers.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path

from .run_memory import atomic_json

WINDOWS = ('five_hour', 'seven_day')


def _window(obj: object, now: float) -> dict | None:
    if not isinstance(obj, dict):
        return None
    pct = obj.get('used_percentage')
    reset = obj.get('resets_at')
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None
    if isinstance(reset, bool) or not isinstance(reset, (int, float)):
        return None
    if not math.isfinite(pct) or not 0 <= pct <= 100:
        return None
    if not math.isfinite(reset) or reset <= now - 60:
        return None
    return {'used_percentage': round(float(pct), 1), 'resets_at': int(reset)}


def save_statusline_snapshot(payload: object, destination: str | Path,
                             *, now: float | None = None) -> bool:
    """Store ONLY validated rate-limit windows, atomically, if present.

    Returns False before Claude's first response, or for unsupported accounts.
    A payload with no rate limits does NOT overwrite a prior useful snapshot.
    """
    now = time.time() if now is None else now
    limits = payload.get('rate_limits') if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return False
    valid = {k: v for k in WINDOWS if (v := _window(limits.get(k), now))}
    if not valid:
        return False
    atomic_json(Path(destination), {'source': 'claude_code_statusline',
                                   'captured_at': now, 'windows': valid})
    return True


def load_snapshot(path: str | Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict) or raw.get('source') != 'claude_code_statusline':
        return {}
    return raw


def usage_text(snapshot: dict, *, now: float | None = None,
               stale_after_s: float = 300) -> str:
    """Display utilization, resets, and age without implying live telemetry."""
    now = time.time() if now is None else now
    captured = snapshot.get('captured_at')
    if not isinstance(captured, (int, float)) or not math.isfinite(captured):
        return 'Claude limits: unavailable. Use Claude Code /usage or the Usage button.'
    age = max(0, now - captured)
    # Invalid or future snapshots should not be mistaken for account usage.
    if captured > now + 60:
        return 'Claude limits: unavailable. Check system clock.'
    values = []
    windows = snapshot.get('windows')
    if isinstance(windows, dict):
        for key, label in (('five_hour', '5h'), ('seven_day', '7d')):
            w = windows.get(key)
            if not isinstance(w, dict):
                continue
            checked = _window(w, now)
            if not checked or checked['resets_at'] <= now:
                continue
            pct = checked['used_percentage']
            remaining = max(0, 100 - pct)
            reset_at = datetime.fromtimestamp(checked['resets_at']).strftime(
                '%a %H:%M' if key == 'seven_day' else '%H:%M')
            values.append(f'{label}: {pct:g}% used / {remaining:g}% left (reset {reset_at})')
    if not values:
        return 'Claude limits: no current verified snapshot. Open Usage for live limits.'
    suffix = f'last checked {int(age // 60)}m ago'
    if age > stale_after_s:
        suffix = f'STALE, {int(age // 60)}m old; may have changed'
    return '  |  '.join(values) + '  |  ' + suffix


def completed_advice_count(transcript_path: str | Path) -> int:
    """Count successfully committed model exchanges, not total billable calls."""
    try:
        with Path(transcript_path).open('r', encoding='utf-8') as fh:
            count = 0
            for line in fh:
                # Only the event kind is needed, not the private prompt content.
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get('kind') == 'exchange':
                    count += 1
            return count
    except OSError:
        return 0