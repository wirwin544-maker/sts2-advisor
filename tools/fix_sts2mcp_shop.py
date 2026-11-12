"""Patch STS2MCP v0.107.1 source so GET game-state reads never reopen shops.

This intentionally patches the local C# mod source, *not* the Oracle advisor.
It recompiles with the installed game assemblies and replaces only the mod DLL
when build succeeds. It keeps backups of both the source and the old DLL.
"""
from __future__ import annotations

import argparse
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

NORMAL_START = "// Auto-open the shopkeeper's inventory if not already open."
NORMAL_END = 'result["state_type"] = "shop";'
NORMAL_CALL = 'merchUI.OpenInventory();'
NORMAL_REPLACEMENT = '// Read-only shop state: never open the inventory from GET.'

FAKE_START = '// Auto-open the inventory if the merchant button is still available'
FAKE_END = '// Build shop inventory from the FakeMerchant model'
FAKE_CALL = 'merchantButton.ForceClick();'
FAKE_REPLACEMENT = '// Read-only fake merchant state: never click the merchant from GET.'


class PatchMismatch(RuntimeError):
    """The installed C# source isn't the revision this patch was written for."""


def _remove_block(source: str, start_mark: str, end_mark: str,
                  required_call: str, replacement: str) -> tuple[str, bool]:
    if start_mark not in source:
        if replacement in source and required_call not in source:
            return source, False
        raise PatchMismatch(f'Missing expected source marker: {start_mark}')
    if source.count(start_mark) != 1:
        raise PatchMismatch(f'Expected exactly one occurrence of: {start_mark}')
    start = source.index(start_mark)
    end = source.find(end_mark, start)
    if end == -1:
        raise PatchMismatch(f'Missing terminating marker: {end_mark}')
    block = source[start:end]
    if required_call not in block or len(block.splitlines()) > 25:
        raise PatchMismatch(f'Unexpected code in block for: {start_mark}')
    # Remove complete lines from the auto-open comment to the line BEFORE
    # result assignment / inventory model construction, preserving that code.
    line_start = source.rfind('\n', 0, start) + 1
    line_end = source.rfind('\n', 0, end) + 1
    indent = source[line_start:start]
    if indent.strip():
        raise PatchMismatch(f'Unexpected indentation for: {start_mark}')
    newline = '\r\n' if '\r\n' in source else '\n'
    return (source[:line_start] + indent + replacement + newline
            + source[line_end:]), True


def patch_source(source: str) -> tuple[str, int]:
    """Return patched C# source and number of automatic UI actions removed."""
    result, normal = _remove_block(source, NORMAL_START, NORMAL_END,
                                   NORMAL_CALL, NORMAL_REPLACEMENT)
    result, fake = _remove_block(result, FAKE_START, FAKE_END,
                                 FAKE_CALL, FAKE_REPLACEMENT)
    return result, int(normal) + int(fake)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.home() / 'STS2MCP-v107',
                        help='Local STS2MCP source directory from the v0.107.1 build')
    parser.add_argument('--game', type=Path,
                        default=Path(r'C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2'),
                        help='Slay the Spire 2 installation directory')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate markers and print a diff without modifying anything')
    args = parser.parse_args(argv)

    source_root = args.source.expanduser().resolve()
    game_dir = args.game.expanduser().resolve()
    source_file = source_root / 'McpMod.StateBuilder.cs'
    build_script = source_root / 'build.ps1'
    game_dll = game_dir / 'data_sts2_windows_x86_64' / 'sts2.dll'
    mod_dll = game_dir / 'mods' / 'STS2_MCP.dll'
    built_dll = source_root / 'out' / 'STS2_MCP' / 'STS2_MCP.dll'

    for item, label in [(source_file, 'STS2MCP source'), (build_script, 'build.ps1'),
                        (game_dll, 'installed game DLL'), (mod_dll, 'installed STS2MCP DLL')]:
        if not item.is_file():
            parser.error(f'{label} was not found: {item}')

    original = source_file.read_text(encoding='utf-8')
    patched, count = patch_source(original)
    print(f'Removed {count} automatic shop-opening block(s).')
    if args.dry_run:
        print(''.join(difflib.unified_diff(original.splitlines(keepends=True),
                                          patched.splitlines(keepends=True),
                                          fromfile='before', tofile='after')))
        print('DRY RUN: No files changed.')
        return 0
    if count == 0:
        print('This source is already patched. No rebuild necessary.')
        return 0

    if os.name != 'nt':
        parser.error('Building and installing the mod requires Windows. Use --dry-run elsewhere.')

    # Preserve source and installed DLL before any changes, in a timestamped
    # directory outside the game mods folder. Runtime/save data is untouched.
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-UTC')
    backup = source_root / 'backups' / f'shop-readonly-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_file, backup / source_file.name)
    shutil.copy2(mod_dll, backup / mod_dll.name)
    source_file.write_text(patched, encoding='utf-8', newline='')
    print(f'Backups: {backup}')
    print('Building the corrected STS2MCP DLL against your installed game...')
    try:
        completed = subprocess.run([
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(build_script), '-GameDir', str(game_dir),
        ], check=False)
        if completed.returncode != 0 or not built_dll.is_file():
            raise RuntimeError('Mod build did not succeed; installed DLL has not changed.')
    except BaseException:
        shutil.copy2(backup / source_file.name, source_file)
        print('Source restored from backup; your installed mod was not changed.', file=sys.stderr)
        raise

    # Don't copy into a running game. The user must Save & Quit first.
    try:
        shutil.copy2(built_dll, mod_dll)
    except OSError:
        print('Build succeeded but installation failed. Close the game and manually copy:',
              built_dll, '\ninto', mod_dll, file=sys.stderr)
        raise
    print('Patched STS2MCP installed. Your game saves and Oracle files were not altered.')
    print('Start Slay the Spire 2, then Oracle. Check that the shop closes normally.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
