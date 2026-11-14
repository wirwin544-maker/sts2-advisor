"""Read-only controls shared between the Oracle overlay and bridge.

The historical ``paused`` flag remains the total-pause setting. A separate
``battle_paused`` flag skips only combat advice. Tracking continues either way.
"""
from __future__ import annotations

import json
import threading
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


# A combat screen can be delivered before MCP populates the ``battle`` object.
# Some card-selection overlays can occur *within* combat, even though they use
# the same state_type as noncombat reward/transform selections.
_COMBAT_SCREEN_TYPES = frozenset(('monster', 'elite', 'boss', 'hand_select'))


def is_combat_screen(state: dict) -> bool:
    """Recognize combat even if an early/transition poll has no battle details."""
    if not isinstance(state, dict):
        return False
    st = state.get('state_type')
    return (st in _COMBAT_SCREEN_TYPES or
            (st == 'card_select' and isinstance(state.get('battle'), dict)))


class PauseGate:
    """Shared, fail-closed pause state for the bridge and its model worker.

    A temporary unreadable/corrupt control file must *not* silently resume a
    previously paused fight. Pause flags are global settings, never per-fight.
    Only a valid JSON dict with an explicit boolean setting can change a flag.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._last = (False, False)
        self._lock = threading.Lock()

    def flags(self) -> tuple[bool, bool]:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(raw, dict):
                    all_pause, battle_pause = self._last
                    if type(raw.get('paused')) is bool:
                        all_pause = raw['paused']
                    if type(raw.get('battle_paused')) is bool:
                        battle_pause = raw['battle_paused']
                    self._last = (all_pause, battle_pause)
            except (OSError, ValueError, TypeError):
                pass  # retain last verified setting, especially battle pause
            return self._last

    def allows(self, kind: str) -> bool:
        all_pause, battle_pause = self.flags()
        return not all_pause and not (kind == 'combat' and battle_pause)
