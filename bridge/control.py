"""Read-only controls shared between the Oracle overlay and bridge.

The historical ``paused`` flag remains the total-pause setting. A separate
``battle_paused`` flag skips only combat advice. Tracking continues either way.
"""
from __future__ import annotations

import json
from pathlib import Path


def pause_flags(path: str | Path) -> tuple[bool, bool]:
    """Return (all_advice_paused, battle_advice_paused), tolerating old files."""
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        if isinstance(value, dict):
            return value.get('paused') is True, value.get('battle_paused') is True
    except (OSError, ValueError, TypeError):
        pass
    return False, False


def is_paused(path: str | Path) -> bool:
    """Backward-compatible legacy total-pause API."""
    return pause_flags(path)[0]


def is_battle_paused(path: str | Path) -> bool:
    return pause_flags(path)[1]
