# Orb flicker follow-up, Spire Oracle / STS2 v0.107.1

The previous filter incorrectly used changing `passive_val` and `evoke_val` values to decide whether the actual orb **identity and placement** had changed. This caused repeated unverified/verified states as a Dark orb charged, Focus changed values, or partial game-state snapshots arrived.

## Changes

* Orb queue identity is confirmed by stable ID and order; orb values (passive/evoke) are confirmed independently.
* At least three polls plus a 1.0-second quiet interval are needed to accept a different orb layout.
* At least two polls plus the quiet interval are needed to accept changed numeric values.
* Last confirmed orb list stays visible while validation is pending, rather than alternating between the orb list and a generic warning. During an unverified reading, no action sequence is presented.
* After three seconds of continuous unstable readings, a rate-limited warning in `runtime/advisor.log` records *orb IDs only* from the last confirmed and currently observed state, with a reason. The warning is at most once every 15 seconds.
* Run startup logs `Orb tracker v2` so you can verify the new code is active.

## Installation

1. Save and close Slay the Spire 2. Stop Spire Oracle completely.
2. Run `INSTALL_ORB_FIX.bat`, or open PowerShell in this extracted folder and run:

   ```powershell
   python .\apply_orb_flicker_fix.py "C:\Users\hunte\OneDrive\Desktop\sts2-oracle-enhanced"
   ```
3. Restart the Oracle program from the same installation folder.

The installer checks for `data/monster_moves.json` and `data/reference_cache.json` to avoid installing in the old non-reference folder. Original source is backed up under `backups/orb-stability-v2-*`. It preserves `config.yaml` and `runtime/`.

## Tuning and diagnostics

Optional `combat` settings in `config.yaml` (defaults apply when absent):

```yaml
combat:
  orb_confirmation_polls: 3
  orb_value_confirmation_polls: 2
  orb_quiet_seconds: 1.0
```

If the orb line is **still wrong or alternating after installing**, send the last 50 lines of `runtime/advisor.log`, especially any `Orb state unstable (...)` entries, and the output of this PowerShell check while the issue is happening:

```powershell
$s = Invoke-RestMethod "http://127.0.0.1:15526/api/v1/singleplayer?format=json"
$s.player.orbs | Select-Object id,name,passive_val,evoke_val
```

That shows what STS2MCP is actually reporting. The patch is read-only and does not modify the game mod.

**Limitations:** The fix is tested offline only. It cannot establish physical screen position if the game-state reader itself returns an incorrect orb order. If the game returns consistently incorrect data, STS2MCP must be addressed separately.
