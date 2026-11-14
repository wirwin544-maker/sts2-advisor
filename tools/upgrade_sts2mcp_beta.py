"""Guarded STS2MCP rebuild for Slay the Spire 2 v0.113.0 public-beta.

The upstream mod last published a v0.107.1 compatibility fix. This helper
applies local read-only shop + mode field corrections and rebuilds against
THE USER'S installed game assemblies. It never ships a compiled DLL.

Installed DLL is replaced only after a successful build. The game and Oracle
must be closed. If the beta changed APIs, a compiler log is kept for follow-up.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .fix_sts2mcp_shop import (patch_source, migrate_legacy_backups,
                               assert_single_state_builder, PatchMismatch)

GAME_DIR = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2')
BASE_SOURCE = Path.home() / 'STS2MCP-v107'
EXPECTED_BUILD = '26625880'
START = '        // Oracle v0.113.0: best-effort read-only game mode metadata.'
ANCHOR = '        // Always include full player data (relics, potions, deck, etc.) on every screen'

# This is optional metadata. Reflection avoids creating a compile-time dependency
# on a property that may have changed or disappeared from the beta game DLL.
MODE_CSHARP = '''        // Oracle v0.113.0: best-effort read-only game mode metadata.
        try
        {
            var flags = System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic;
            var typ = runState.GetType();
            var modeProperty = typ.GetProperty("GameMode", flags)
                ?? typ.GetProperty("RunMode", flags)
                ?? typ.GetProperty("Mode", flags);
            var modeText = modeProperty?.GetValue(runState)?.ToString();
            if (!string.IsNullOrWhiteSpace(modeText)
                && result["run"] is Dictionary<string, object?> modeRun)
            {
                modeRun["game_mode"] = modeText.ToLowerInvariant();
            }
        }
        catch (System.Exception) { /* optional mode metadata unavailable */ }

'''


def patch_mode_metadata(source: str) -> tuple[str, bool]:
    """Add a mode field without changing existing combat/shop model logic."""
    if START in source:
        return source, False
    if source.count(ANCHOR) != 1 or 'result["run"] = new Dictionary' not in source:
        raise PatchMismatch('Unexpected STS2MCP run state structure. Skipping unsafe mode patch.')
    return source.replace(ANCHOR, MODE_CSHARP + ANCHOR, 1), True


def patch_beta_source(source: str) -> tuple[str, dict]:
    code, shops = patch_source(source)
    code, mode = patch_mode_metadata(code)
    return code, {'shop_blocks_removed': shops, 'mode_metadata_added': mode}


def steam_build_id(game: Path) -> str | None:
    """Read Steam's appmanifest if present; absence is not a failure."""
    path = game.parent.parent / 'appmanifest_2868840.acf'
    try:
        text = path.read_text(encoding='utf-8-sig')
    except OSError:
        return None
    m = re.search(r'"buildid"\s+"(\d+)"', text)
    return m.group(1) if m else None


def check_api(base_url: str = 'http://127.0.0.1:15526') -> int:
    try:
        with urlopen(base_url.rstrip('/') + '/api/v1/singleplayer?format=json', timeout=5) as response:
            state = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, OSError, ValueError) as exc:
        print(f'STS2MCP state request FAILED: {type(exc).__name__}: {exc}')
        print('Check the game, mods consent, STS2MCP DLL and beta compatibility.')
        return 2
    print('STS2MCP GET /api/v1/singleplayer succeeded.')
    print('Screen:', state.get('state_type'))
    print('Run:', json.dumps(state.get('run', {}), ensure_ascii=False))
    print('Character:', (state.get('player') or {}).get('character'))
    print('No game actions were performed.')
    return 0


def validate_source(source: Path, game: Path, require_dll: bool = True) -> None:
    expected = [source / 'McpMod.StateBuilder.cs', source / 'build.ps1',
                game / 'data_sts2_windows_x86_64' / 'sts2.dll']
    if require_dll:
        expected.append(game / 'mods' / 'STS2_MCP.dll')
    missing = [str(f) for f in expected if not f.is_file()]
    if missing:
        raise FileNotFoundError('Missing required files:\n  ' + '\n  '.join(missing))


def build_and_install(source: Path, game: Path, *, dry_run: bool = False,
                      build_only: bool = False, runner=None) -> int:
    """Safely patch, compile and install. A failed compile retains installed DLL."""
    source = source.expanduser().resolve()
    game = game.expanduser().resolve()
    validate_source(source, game)
    src = source / 'McpMod.StateBuilder.cs'
    old_source = src.read_text(encoding='utf-8')
    patched, changes = patch_beta_source(old_source)
    ver = steam_build_id(game)
    print('Steam build:', ver or 'appmanifest unavailable',
          '| Expected Nov 12 beta:', EXPECTED_BUILD)
    if ver and ver != EXPECTED_BUILD:
        print('WARNING: Installed game is not Steam build 26625880. Beta may have received another patch.')
    print('Code changes:', changes)
    if dry_run:
        print('Dry run completed. No files modified, no build started.')
        return 0
    if os.name != 'nt' and runner is None:
        raise RuntimeError('Installation requires Windows. Use --dry-run to inspect on other systems.')

    backup_root = source.parent / f'{source.name}-backups'
    migrate_legacy_backups(source, backup_root)
    assert_single_state_builder(source)
    backup = backup_root / ('beta113-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True, exist_ok=False)
    previous_dll = game / 'mods' / 'STS2_MCP.dll'
    shutil.copy2(src, backup / 'McpMod.StateBuilder.cs')
    shutil.copy2(previous_dll, backup / 'STS2_MCP.dll')
    build_file = backup / 'build.log'
    result_dll = source / 'out' / 'STS2_MCP' / 'STS2_MCP.dll'
    if result_dll.exists():
        result_dll.unlink()  # Never install a stale output after a failed build.
    src.write_text(patched, encoding='utf-8', newline='')
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
               '-File', str(source / 'build.ps1'), '-GameDir', str(game)]
    print('Building against current local beta assemblies:', game)
    success = False
    try:
        run = runner or subprocess.run
        outcome = run(command, cwd=source, capture_output=True, text=True, errors='replace', check=False)
        log = (outcome.stdout or '') + '\n' + (outcome.stderr or '')
        build_file.write_text(log, encoding='utf-8')
        print(log[-10000:])
        if outcome.returncode != 0 or not result_dll.is_file():
            raise RuntimeError(f'Build failed (exit {outcome.returncode}). Diagnostics: {build_file}. Installed DLL unchanged.')
        if build_only:
            success = True
            print('Build succeeded; --build-only left installed DLL untouched:', result_dll)
            return 0
        # Last operation changes the mod; all prerequisites and diagnostics must pass first.
        shutil.copy2(result_dll, previous_dll)
        success = True
        print('Installed rebuilt STS2MCP DLL. Previous version backed up at:', backup)
        print('Restart game and use --verify-connection to test the updated API.')
        return 0
    except BaseException:
        print('Build/install failed. Restoring original C# source; keeping existing DLL.', file=sys.stderr)
        # In case copy failure partially replaced DLL, restore it to known prior bytes.
        if not build_only:
            try: shutil.copy2(backup / 'STS2_MCP.dll', previous_dll)
            except OSError: pass
        raise
    finally:
        if not success:
            shutil.copy2(backup / 'McpMod.StateBuilder.cs', src)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=BASE_SOURCE)
    parser.add_argument('--game', type=Path, default=GAME_DIR)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--verify-connection', action='store_true')
    args = parser.parse_args(argv)
    if args.verify_connection:
        return check_api()
    try:
        return build_and_install(args.source, args.game, dry_run=args.dry_run,
                                 build_only=args.build_only)
    except (OSError, RuntimeError, PatchMismatch) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
