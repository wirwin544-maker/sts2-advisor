"""Update the active STS2 Oracle v0.113 Excel-reference installation.

Makes battle-only pause persistent across encounters and enforces it inside the model worker.
Preserves runtime state, reference data, configuration, and the STS2MCP mod.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

BASE = Path(__file__).resolve().parent
UPDATES = (
    'bridge/control.py',
    'bridge/main.py',
    'bridge/worker.py',
    'overlay/overlay.py',
    'tests/test_battle_pause_persistence.py',
)


def choose_folder() -> Path:
    default = Path.home() / 'OneDrive' / 'Desktop' / 'sts2-oracle-enhanced'
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        result = filedialog.askdirectory(
            title='Select the active Excel-reference Spire Oracle installation',
            initialdir=str(default if default.is_dir() else Path.home()))
        root.destroy()
        if result:
            return Path(result)
    except (ImportError, RuntimeError, OSError):
        pass
    value = input('Active sts2-oracle-enhanced folder: ').strip().strip('"')
    if not value:
        raise ValueError('No installation selected.')
    return Path(value)


def verify_target(target: Path) -> None:
    required = (
        'config.yaml', 'bridge/main.py', 'bridge/control.py',
        'bridge/screens.py', 'bridge/beta_compat.py', 'bridge/run_memory.py',
        'overlay/overlay.py', 'data/monster_moves.json',
        'data/reference_cache.json',
    )
    missing = [p for p in required if not (target/p).is_file()]
    if missing:
        raise ValueError('Wrong Oracle folder or incomplete installation. Missing: '
                         + ', '.join(missing))
    try:
        cache = json.loads((target/'data/reference_cache.json').read_text(encoding='utf-8'))
        if len(cache.get('sheets') or {}) < 10:
            raise ValueError('The selected reference cache does not contain the imported sheets.')
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Unable to validate Excel reference cache: ' + str(exc)) from exc
    # Avoid accidentally applying beta-only bridge code to the pre-beta fork.
    main_source = (target/'bridge/main.py').read_text(encoding='utf-8')
    overlay_source = (target/'overlay/overlay.py').read_text(encoding='utf-8')
    if 'beta_compat' not in main_source:
        raise ValueError('This Oracle installation does not contain the v0.113 beta update.')
    if 'battle_paused' not in main_source or '_toggle_battle_pause' not in overlay_source:
        raise ValueError('Install the Pause All / Pause Battle update first; this is its follow-up fix.')


def atomic_install(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.oracle-battle-pause-', suffix='.tmp',
                               dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as dst, source.open('rb') as src:
            shutil.copyfileobj(src, dst)
        os.replace(name, destination)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def install(target: Path, dry_run: bool = False) -> Path | None:
    target = target.expanduser().resolve()
    verify_target(target)
    sources = BASE/'files'
    missing = [p for p in UPDATES if not (sources/p).is_file()]
    if missing:
        raise ValueError('Patch archive is missing: ' + ', '.join(missing))
    changed = [p for p in UPDATES if not (target/p).is_file()
               or (target/p).read_bytes() != (sources/p).read_bytes()]
    print('Active Oracle:', target)
    print(f'{len(changed)} of {len(UPDATES)} patch files require updating.')
    if dry_run:
        for p in changed:
            print('WOULD UPDATE:', p)
        print('Dry-run complete. Nothing changed.')
        return None
    if not changed:
        print('Already installed; no changes needed.')
        return None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup = target.parent / (target.name + '-battle-pause-backups') / stamp
    backup.mkdir(parents=True, exist_ok=False)
    completed: list[tuple[str, bool]] = []
    try:
        for p in changed:
            dest = target/p
            existed = dest.is_file()
            if existed:
                old = backup/p
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, old)
            # Record before replacement so even a failed replacement rolls back.
            completed.append((p, existed))
            atomic_install(sources/p, dest)
            print('UPDATED:', p)
    except BaseException:
        print('Installation error. Restoring prior files.', file=sys.stderr)
        for p, existed in reversed(completed):
            dest = target/p
            try:
                if existed:
                    atomic_install(backup/p, dest)
                else:
                    dest.unlink(missing_ok=True)
            except OSError as exc:
                print('Manual restore may be needed:', p, exc, file=sys.stderr)
        raise
    print('Installed. Previous code backed up at:', backup)
    print('Unchanged: runtime/control.json (your pause choices), all run histories, config, XLSX data, and STS2MCP.')
    return backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        install(args.target or choose_folder(), args.dry_run)
        return 0
    except (ValueError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
