# STS2MCP November 12, 2026 beta compatibility correction

This update addresses the **seven `CS1061` compile errors** reported while rebuilding STS2MCP against the installed *Slay the Spire 2* v0.113.0 beta.

## What failed

The local STS2MCP source (last upstream v0.107-compatible revision) references game APIs removed from the beta:

- `MerchantRoom.GetLocalInventory()` (2 occurrences)
- `MerchantEntry.OnTryPurchaseWrapper()` (1 occurrence)
- `StartRunLobby.MaxPlayers` (1 occurrence)
- `LoadRunLobby.ConnectedPlayerIds` (3 occurrences)

## Changes

The updater rewrites both `McpMod.StateBuilder.cs` and `McpMod.Actions.cs` and adds a `McpMod.OracleBetaCompat.cs` source helper. It uses reflection to retrieve merchant inventory and lobby properties when exposed under a compatible name. Missing lobby information is explicitly unknown (`null`), not guessed. If shop inventory cannot be read it remains unavailable rather than silently inventing data.

**Automated `shop_buy` MCP actions are temporarily disabled.** The replacement returns an explicit error. Oracle's shop coaching is read-only and does not require buying through the API. The previously corrected shop-close behavior remains in place, with no automatic merchant-window opening during game-state reads.

The source and previously installed DLL are backed up under `C:\Users\hunte\STS2MCP-v107-backups\beta113-...`. The new DLL is installed only when local compilation succeeds. If compilation fails, both edited C# sources and the generated helper are restored/removed to their previous states, and the installed DLL remains unchanged.

## Installation

1. Save and quit the game and exit Oracle.
2. Extract this ZIP and double-click **`INSTALL_STS2MCP_BETA_FIX.bat`**.
3. The script checks source markers, builds with the game's installed DLLs, and installs the result only after build success.
4. Launch the game with mods enabled.
5. Double-click **`VERIFY_STS2MCP_API.bat`**. This only reads `/api/v1/singleplayer?format=json`.
6. Enter a shop and verify that inventory information appears and the shop stays closed when you exit it. The reflective inventory fallback has **not** been validated with actual beta game assemblies.

This is an **STS2MCP-only** update. Your active `sts2-oracle-enhanced` installation, Excel reference cache, run history, usage display and build chooser are not modified. Your Oracle v0.113.0 update from the previous ZIP remains in place. The corrected source helper will also be published in the Oracle GitHub fork for future rebuilds.

## Manual PowerShell invocation

From the extracted directory:

```powershell
python -m tools.upgrade_sts2mcp_beta --dry-run
python -m tools.upgrade_sts2mcp_beta
```

If the game path or STS2MCP source path differs, use `--game` or `--source` arguments.

## Source verification

```powershell
python -m unittest discover -s tests -v
```

This tests source transformation and backup/restore logic, not the game's binary API. Successful compile and a live API call are required for confirmation.


### CS0103 follow-up: missing `NMerchantRoom` import
The generated `McpMod.OracleBetaCompat.cs` referenced `NMerchantRoom.Instance` without importing its namespace. The generator now includes `using MegaCrit.Sts2.Core.Nodes.Rooms;`. This is a compile-time namespace fix, not a newly removed game API. Run the corrected beta rebuild after closing the game; its backup logic preserves the previously installed DLL if compilation fails. The actual beta DLL remains unverified until built locally.
