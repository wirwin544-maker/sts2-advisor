# Spire Oracle: Combat, Pause/Resume and STS2 reference integration

This is a community modification of [Spire Oracle](https://github.com/bnipper-creator/sts2-advisor). It extends the existing read-only advisor, not the game itself.

## Added functionality

* **Pause / Resume button** on the overlay. A pause hides advice and suppresses new Claude requests. The backend continues collecting the deck and recording run state. Resuming invalidates old advice and requests a new answer for the live game state. A request already executing when Pause is clicked may still consume Claude usage, but its result is discarded.
* **Combat coaching** with ordered, conditional card actions and legal-first-action checks. The plan disappears immediately if the live hand, enemy intent, HP, block, relics, energy or other tracked state changes, then can be recalculated. Claude does not execute cards. This is not a deterministic combat solver, and only the first step is checked against live card playability.
* **Persistent per-run journal and build selector**, including strategy and Claude decision history across advisor restarts (from the earlier combat patch).
* **Spreadsheet reference importer** for *Slay the Spire 2 Reference.xlsx*. It processes all 12 worksheets, preserving populated cell values, cached formulas, hyperlinks, and 31 embedded image assets. It constructs a dedicated moveset index for Monsters, Elites and Bosses. Other worksheet data is searchable and selected relevant rows are added to strategy prompts when needed. Graphic assets are preserved locally, not interpreted by Claude.
* **Fight-start reference lookup**: reads the actual enemy names from STS2MCP, matches them to unambiguous spreadsheet entries and sends their moves, attack patterns, special effects and notes to the combat model. The current game's observed intent and powers always override the sheet.

## Game/version caution

The supplied workbook says **v0.111.0**. The user's current game version is **v0.107.1**. The reference is not guaranteed to match older game versions. Use live enemy intents as authoritative. Test compatibility with the installed STS2MCP build before depending on a recommendation.

## Installation / update

1. Back up your installed `sts2-advisor-main` directory and its `runtime` directory. Back up Slay the Spire 2 saves separately.
2. Download this branch as a ZIP and extract it **into a separate directory** or use Git on a branch. Preserve your existing `config.yaml` changes, especially custom Claude settings.
3. Copy the Python modules, overlay, prompts and configuration updates into your installation, or use the full checkout after retaining your runtime and configuration.
4. **Import the workbook locally** from a PowerShell window in the repository root:

   ```powershell
   python .\data\import_reference.py "C:\path\to\Slay the Spire 2 Reference.xlsx"
   ```

   This produces `data/reference_cache.json`, `data/monster_moves.json`, and `data/reference_media/`.
5. Restart the game and the advisor. Verify `runtime/advisor.log` prints the reference dataset version and entry count. The overlay's combat section displays how many encountered enemies matched the sheet.
6. Use **Pause** in the overlay to suspend suggestions; use **Resume** to request fresh advice. The pause state lives in `runtime/control.json` and survives application restarts.

### Imported data distribution

The source spreadsheet is user-supplied. No redistribution license was established, so this public fork **does not contain** the workbook, its extracted texts, or embedded images. Those files are generated locally and ignored by Git. Reimporting an updated spreadsheet refreshes the local cache. Keep the workbook in a location you control.

### Performance / Claude cost

The full reference index is read once on startup. Only the matched combat enemies and bounded snippets from other sheets are included in individual prompts. Combat requests are debounced and limited by `combat.max_requests_per_fight` and `combat.min_request_interval_s`. Pausing stops new requests but cannot retroactively cancel billing for a request already sent.

## Testing

```powershell
python -m unittest discover -s tests -v
python -m bridge.model_client --selftest
```

Unit tests run without the game or a Claude account. The Claude CLI selftest needs a signed-in Claude Code installation. **Live Windows gameplay, full turn sequencing, and STS2MCP compatibility on v0.107.1 still require user testing.**

## Data file formats

* `data/reference_cache.json`: `sheets -> rows -> cells`, with source sheet, original row number, column, text or numeric values, formulas and hyperlink targets.
* `data/monster_moves.json`: combat entries keyed conservatively by the exact normalized enemy name and monster type, with move columns C-H, notes I, attack patterns J and original row details.
* `data/reference_media/`: preserved source image assets (not used for combat decisions).
