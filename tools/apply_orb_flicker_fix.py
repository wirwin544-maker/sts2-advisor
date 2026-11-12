"""Safely install a targeted Spire Oracle orb-stabilization patch."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
DEFAULT = Path(r'C:\Users\hunte\OneDrive\Desktop\sts2-oracle-enhanced')
FILES = (
    'bridge/combat.py',
    'bridge/main.py',
    'overlay/overlay.py',
    'tests/test_runtime_stability.py',
    'tests/test_orb_identity.py',
)


def install(folder: Path) -> Path:
    dest = Path(folder).expanduser().resolve()
    if not (dest / 'bridge' / 'main.py').is_file() or not (dest / 'overlay' / 'overlay.py').is_file():
        raise RuntimeError(f'Not a Spire Oracle installation: {dest}')
    required_data = ['data/monster_moves.json', 'data/reference_cache.json']
    if not all((dest / path).is_file() for path in required_data):
        raise RuntimeError('Excel-reference cache not found. Refusing to update the wrong Oracle folder.')
    for name in FILES:
        if not (PACKAGE / 'files' / name).is_file():
            raise RuntimeError(f'Package is incomplete: missing {name}')

    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = dest / 'backups' / ('orb-stability-v2-' + stamp)
    changed = []
    try:
        for name in FILES:
            source = PACKAGE / 'files' / name
            target = dest / name
            exists = target.is_file()
            if exists:
                original = backup / name
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, original)
            target.parent.mkdir(parents=True, exist_ok=True)
            # A unique file prevents collisions with another stale installer.
            with tempfile.NamedTemporaryFile(delete=False, prefix=target.name + '.install-',
                                             dir=target.parent) as f:
                pending = Path(f.name)
            try:
                shutil.copy2(source, pending)
                os.replace(pending, target)
            finally:
                pending.unlink(missing_ok=True)
            changed.append((target, name, exists))
    except BaseException:
        for target, name, existed in reversed(changed):
            try:
                if existed:
                    shutil.copy2(backup / name, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError:
                print(f'WARNING: could not roll back {target}')
        raise

    print('Installed orb-stabilization v2 into:', dest)
    print('Code backup:', backup)
    print('Preserved: runtime, config.yaml, imported spreadsheet data, Claude settings.')
    print('Restart the Oracle bridge and overlay for this to take effect.')
    return backup


if __name__ == '__main__':
    try:
        install(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT)
    except Exception as exc:
        print('ERROR:', exc)
        raise SystemExit(1)
