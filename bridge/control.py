"""Read-only bridge-side access to overlay's pause control file.

No network requests or modifications to the game are involved. The overlay
writes this file atomically, and the bridge checks it before enqueuing advice.
"""
from __future__ import annotations

import json
from pathlib import Path


def is_paused(path: str | Path) -> bool:
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value.get('paused') is True if isinstance(value, dict) else False
    except (OSError, ValueError, TypeError):
        return False
