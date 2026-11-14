# Spire Oracle support for Slay the Spire 2 public-beta v0.113.0

## Scope and limits

The November 12, 2026 public-beta is v0.113.0, Steam build **26625880**. It includes The Fool, Blitz and Dread; changes to cards, events, monsters and relics. The existing Excel workbook remains a **v0.111.0 historical reference**.

The Python Oracle changes are source/test verified offline. **STS2MCP game compatibility can only be established by rebuilding against your installed beta `sts2.dll` and actually calling its `/api/v1/singleplayer` endpoint.** No beta game assemblies or executable are bundled or redistributed.

Official patch notes: https://store.steampowered.com/news/app/2868840/view/708914333639245837

## Windows install, maintaining your local files

1. Save and quit the game and stop all Oracle processes (`stop.bat` in your active Oracle directory).
2. Extract the update ZIP and run `INSTALL_BETA_ORACLE.bat`. Select your **active `sts2-oracle-enhanced`** directory. The updater requires `data/monster_moves.json` and `data/reference_cache.json` and retains `runtime/`, `config.yaml`, and the original spreadsheet data. It makes a backup outside the installation directory.
3. Run `INSTALL_BETA_STS2MCP.bat` to compile your source against the current Steam beta assemblies. The helper relocates older in-project C# backups before compilation, retains the shop read-only fix, adds best-effort run-mode reflection and **does not replace the existing DLL if the build fails**.
4. Launch the game and check that mods are enabled. Run `python -m tools.upgrade_sts2mcp_beta --verify-connection` in your updated Oracle folder to test the API without making game actions. Start Oracle normally.
5. For Blitz or Dread, if STS2MCP does not expose the mode, set `game.mode_override: blitz` or `dread` in `config.yaml`. Leave `auto` for ordinary runs.

### Troubleshooting

If the rebuild fails, send the printed compiler errors or the diagnostics log, not the game executable or copyrighted assemblies. Do not copy the old v0.107.1 DLL over your updated game merely because the version string differs. If the API reports `MissingMethodException`, `TypeLoadException`, or related errors, further C# source updates based on the local build are necessary.

The reference workbook describes v0.111.0. Infested Prism's removed Radiate move, changed Tunneler/ Axebot parameters, new event choices and revised cards are grounded in the new patch notes. Live card text and enemy intents take precedence. The Fool's archetype choices are **unranked early-beta directions**, not statistical win-rate rankings.

## Features retained

Pause/Resume, Claude usage snapshots, local 12-sheet reference cache, run journals, conditional combat advice, one-based enemy labels, rightmost orb validation, file-lock handling, and orb stability are preserved.

## Validating

`python -m unittest discover -s tests -q`

`python -m tools.upgrade_sts2mcp_beta --verify-connection`

Look for the beta version banner and `Orb tracker v2` in `runtime/advisor.log`.
