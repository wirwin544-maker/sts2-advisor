# Build chooser: clickable ranked archetypes for StS2 v0.107.1

This addresses the former `Unknown | Act 1` dialog that showed only a flexible build and could wait indefinitely for Claude.

## Behavior

- The chooser now presents **five ranked archetypes plus Flexible** for each of Ironclad, Silent, Defect, Regent, and Necrobinder.
- Every row is clickable. It shows a version-labelled editorial tier and short archetype description. Selecting a row and clicking **Use selected build** saves it immediately to the active run. It does not require Claude to be installed or responding.
- **View build guide** opens the character-specific v0.107.1 guide. **Compare other site** opens the independent STS2.GG database; other sites may use different patches and ranking criteria.
- If STS2MCP does not report a character at the first reward screen, the chooser offers a **manual character selector**. When the game later reports a different actual character, Oracle corrects the identity and clears an incompatible manually selected build rather than silently switching runs.
- **Ask Claude (optional)** remains supported. It receives the tiered candidate list, source descriptions, and available game state. The selection is never forced: the player can pick a build while Claude works.
- A visible timeout appears within 60 seconds, including if the game/bridge heartbeat stops. A backend timeout after 55 seconds ends the blocking request. **Not now** cancels an outstanding request and releases normal advice.
- Previous run memory and the separate `runtime` folder are preserved. The build catalogue is static and available offline. It is **not** a live site scraper; updates to the source rankings require an explicit catalogue update.

## Sources and version

The primary **editorial** S-C rankings are from [slaythespire2.net builds](https://slaythespire2.net/build), which lists the live v0.107.1 card pool separately from beta v0.111.0. These are not independently verified run win rates. See also [Spire Codex community archetypes](https://spire-codex.com/guides/builds-guide) and [STS2.GG build database](https://sts2.gg/builds), which may rank the same archetypes differently and may reflect other patch versions.

Snapshot checked: November 11, 2026. After game updates, reassess tier labels and actual available cards. Continue prioritizing current live rewards, deck and enemy state over the guide.

## Installation over existing Oracle

Stop Oracle and Slay the Spire 2. Back up your installed `sts2-advisor-main` folder, including `runtime`. Use the companion patch archive's `apply_update.py` script to copy the changed modules and build catalogue. It backs up files before replacing them and will not change `config.yaml`, `runtime`, the game mods, the local moveset spreadsheet cache or Claude settings.

Run from the directory containing `apply_update.py`:

```powershell
python .\apply_update.py "C:\Users\hunte\OneDrive\Desktop\sts2-advisor-main"
```

The local Claude usage-statusLine installer, `python .\tools\install_usage_statusline.py`, is **one-time setup**, not an action required each Oracle restart. Usage readings become stale until an interactive Claude Code session refreshes them.

## Diagnostics

If the chooser still displays `Unknown`, pick the character manually and select a build. If Claude fails to return, the UI now shows a timeout and Oracle continues. Inspect `runtime/advisor.log` and run `python -m bridge.model_client --selftest` separately to diagnose Claude Code execution.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Unit tests run without Claude or the game. GUI smoke testing was performed under a virtual display, with `Unknown` character recovery and the 60-second UI timeout. Live Windows gameplay on v0.107.1 has not yet been verified.
