"""Apply orb-order and one-based enemy UI fixes to the active Oracle install.

Preserves the reference workbook cache, run journal, settings and other modules.
If no path is provided on Windows, prompts for the Oracle folder.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import sys

FILES = (
    'bridge/combat.py',
    'overlay/overlay.py',
    'prompts/combat_prompt.md',
    'tests/test_coaching.py',
)
REQUIRED = ('start.bat', 'bridge/main.py', 'overlay/overlay.py',
            'data/reference_cache.json', 'data/monster_moves.json')


def select_folder() -> Path:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    chosen = filedialog.askdirectory(
        title='Select ACTIVE Oracle folder containing imported Excel data',
        mustexist=True)
    root.destroy()
    if not chosen:
        raise ValueError('No folder was selected. Nothing changed.')
    return Path(chosen)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(target: Path, package: Path, dry_run: bool = False) -> tuple[int, Path | None]:
    target = target.expanduser().resolve()
    missing = [p for p in REQUIRED if not (target / p).is_file()]
    if missing:
        raise ValueError('This does not look like the active Excel-reference Oracle folder: '
                         + str(target) + '. Missing: ' + ', '.join(missing))
    changes = []
    for p in FILES:
        src = package / 'files' / p
        if not src.is_file():
            raise ValueError('Incomplete patch archive: '+str(src))
        dest = target / p
        if not dest.is_file() or sha(src) != sha(dest):
            changes.append((p,src,dest))
    print('Target:',target)
    print('Reference data and runtime journal will NOT be modified.')
    print('Files to update:',len(changes))
    for p,_,_ in changes: print('  '+p)
    if dry_run:
        print('Dry run. Nothing changed.')
        return len(changes),None
    if not changes:
        print('Already up to date.')
        return 0,None
    backup = target / 'backups' / ('orb_target_fix_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    staged = backup / '_staging'
    for p,src,dest in changes:
        staged_src = staged / p
        staged_src.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,staged_src)
        if dest.is_file():
            original = backup / p
            original.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dest,original)
    applied=[]
    try:
        for p,src,dest in changes:
            dest.parent.mkdir(parents=True,exist_ok=True)
            tmp = dest.with_name(dest.name+'.oracle_fix_tmp')
            try:
                shutil.copy2(staged/p,tmp)
                tmp.replace(dest)
            finally:
                tmp.unlink(missing_ok=True)
            applied.append((p,dest))
    except Exception:
        print('Error during installation. Rolling files back.',file=sys.stderr)
        for p,dest in reversed(applied):
            original=backup / p
            if original.is_file(): shutil.copy2(original,dest)
            else: dest.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staged,ignore_errors=True)
    print('Oracle update complete. Backups:',backup)
    print('No changes to Claude usage display, selected build, reference cache, settings, or run history.')
    return len(changes),backup


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('oracle_dir',type=Path,nargs='?')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:
        apply(args.oracle_dir or select_folder(),Path(__file__).resolve().parent,args.dry_run)
        return 0
    except (ValueError, OSError, RuntimeError) as ex:
        print('ORACLE FIX NOT INSTALLED:',ex,file=sys.stderr)
        return 1
if __name__=='__main__':
    raise SystemExit(main())