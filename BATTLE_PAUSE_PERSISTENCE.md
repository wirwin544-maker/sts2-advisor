# Persistent Pause Battle correction (STS2 beta v0.113.0)

The earlier Pause Battle implementation blocked normal combat calls in the main polling loop but had no independent guard at the asynchronous model worker. Temporary errors reading control.json could also clear the displayed pause setting.

This update creates one shared `PauseGate` used by the bridge and worker. A valid `battle_paused: true` applies across all encounters until explicitly resumed. Bad/missing reads keep the last valid pause state. It rechecks before accepting late model results. Battle screens received without battle details cannot trigger normal decision advice. The overlay prioritizes paused state over an old combat-plan file. Noncombat Claude advice still works when only battle is paused.

## Install

1. Exit the game and close Oracle completely (run `stop.bat` or `stop.ps1` in the active installation).
2. Extract this ZIP. Double-click **INSTALL_BATTLE_PAUSE_FIX.bat**, and choose the `sts2-oracle-enhanced` folder you actually run.
3. The installer backs up changed code under a sibling `sts2-oracle-enhanced-battle-pause-backups` directory. It does not touch `runtime/control.json`, your run history, Claude settings, Excel caches or STS2MCP.
4. Restart Oracle. Click **Pause Battle** so the button reads **Resume Battle**. Play into another fight. There should be no new combat model calls.

## Validate and troubleshoot

From the active Oracle folder:

```powershell
Get-Content .\runtime\control.json
Select-String .\runtime\advisor.log -Pattern 'Battle suggestions paused|New encounter: battle pause remains ON|Combat plan' | Select-Object -Last 30
python -m unittest discover -s tests -p test_battle_pause_persistence.py -v
```

Expected JSON includes `"battle_paused": true` while battle advice is paused, even after new combats begin.

You can preview installation without writing:

```powershell
python .\install_battle_pause_fix.py --target "C:\Users\hunte\OneDrive\Desktop\sts2-oracle-enhanced" --dry-run
```

*Note:* This is an offline-reviewed patch. Live Windows beta gameplay has not been tested in this environment.
