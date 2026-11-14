"""Install the runtime stability patch into the active Excel-reference Oracle.

Only code files and one regression test are updated. Config, game mod,
reference cache, Claude settings and existing run memory are preserved.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
from pathlib import Path

PATCH = Path(__file__).resolve().parent
DEFAULT = Path(r'C:\Users\hunte\OneDrive\Desktop\sts2-oracle-enhanced')
FILES = [
    'bridge/main.py',
    'bridge/combat.py',
    'bridge/run_memory.py',
    'bridge/single_instance.py',
    'bridge/util.py',
    'overlay/overlay.py',
    'tests/test_runtime_stability.py',
]


def install(target: Path):
    target = target.expanduser().resolve()
    if not (target / 'bridge' / 'main.py').is_file() or not (target / 'overlay' / 'overlay.py').is_file():
        raise RuntimeError(f'Not an Oracle installation: {target}')
    if not all((target / item).is_file() for item in ('data/monster_moves.json', 'data/reference_cache.json')):
        raise RuntimeError('Selected Oracle has no imported Excel reference cache. Refusing to modify the wrong folder.')
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = target / 'backups' / ('runtime-stability-' + stamp)
    written = []
    try:
        for name in FILES:
            source = PATCH / 'files' / name
            if not source.is_file():
                raise RuntimeError(f'Patch is incomplete: {source}')
            destination = target / name
            was_present = destination.is_file()
            if was_present:
                original_backup = backup / name
                original_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, original_backup)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + '.installing')
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            written.append((destination, name, was_present))
    except Exception:
        for destination, name, was_present in reversed(written):
            try:
                if was_present:
                    shutil.copy2(backup / name, destination)
                else:
                    destination.unlink(missing_ok=True)
            except OSError:
                print(f'WARNING: automatic rollback failed for {destination}')
        raise
    print('Oracle runtime stability patch installed.')
    print('Oracle directory:', target)
    print('Backup folder:', backup)
    print('Preserved: runtime, config.yaml, data, imported spreadsheet, Claude settings.')
    print('Important: restart Oracle to load the new bridge lock and orb stabilization logic.')


if __name__ == '__main__':
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    try:
        install(destination)
    except Exception as exc:
        print('ERROR:', exc)
        raise SystemExit(1)
