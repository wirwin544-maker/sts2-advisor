# Spire Oracle v0.113 beta: independent pause controls and forced-map skip

## Changes

The overlay has two independent toggles:

- **Pause All / Resume All** stops all new Claude advice requests, including combat, map, shop, events, rewards, and build suggestions. Game-state tracking and journaling continue. This preserves the historical `runtime/control.json` key `paused`.
- **Pause Battle / Resume Battle** stops combat advice requests, including during combat card selections, but leaves non-combat advice available. The overlay retains live HP, enemy, and orb information and displays `BATTLE SUGGESTIONS PAUSED`. The second key is `battle_paused`.

If both are paused, resuming All does not automatically resume Battle. You can switch combat advice back on independently. An in-flight battle result is invalidated when Battle is paused.

When the map reports **exactly one reachable `next_options` entry**, Oracle displays that one available route without requesting a model response. A zero-option transitional map similarly makes no model call. Multiple routes continue through normal route advice. This does not click or move anything in the game.

## Install on Windows

1. Close Oracle, preferably through `stop.bat` in the *active* `sts2-oracle-enhanced` folder. You may leave the game open, but stopping Oracle during file replacement is necessary.
2. Extract this ZIP and double-click `INSTALL_PAUSE_MAP.bat`.
3. Select your active `sts2-oracle-enhanced` folder. It must contain the v0.113 beta bridge and the imported Excel reference cache.
4. Restart Oracle. The new `Pause All` and `Pause Battle` buttons are in a separate row under the title bar.

Advanced preview from PowerShell: `python .\install_pause_map.py --target "C:\Users\hunte\OneDrive\Desktop\sts2-oracle-enhanced" --dry-run`

The installer copies four Python source files and two test files, backs up replaced files next to your Oracle installation, checks the beta/reference installation, and leaves `runtime/`, the reference cache, `config.yaml`, and STS2MCP unchanged. It is safe to rerun.

## Check

`python -m unittest tests.test_pause_and_map -v`

Verify that `Pause Battle` allows a map with two choices to receive advice, but suppresses combat recommendations. With `Pause All`, both remain suppressed. With only one reachable map route, Oracle should show the forced route and no `Firing advice: map` log event for that decision.

This update is Python-side only. It has not been validated with a live Windows game session.
