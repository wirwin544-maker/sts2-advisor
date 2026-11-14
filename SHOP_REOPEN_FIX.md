# Fix: Shop inventory immediately reopens after closing

## Cause

In the v0.107-compatible STS2MCP source, `McpMod.StateBuilder.cs` calls `NMerchantRoom.Instance.OpenInventory()` whenever the shop UI is closed while the active room remains `MerchantRoom`. `BuildGameState()` is invoked by every `GET /api/v1/singleplayer`. Spire Oracle polls that endpoint repeatedly, so reading the game state reopens the inventory before the player can click Proceed.

A second auto-open block under `BuildFakeMerchantState()` calls `merchantButton.ForceClick()` for the Fake Merchant event.

The patch removes **both UI-modifying operations from GET state processing**. It does not change how the merchant inventory entries, gold, shop options, or Proceed status are read.

## Instructions for STS2 v0.107.1

1. **Save & Quit** the game and close Spire Oracle.
2. You must still have the STS2MCP source checkout you compiled for this version, typically `C:\Users\hunte\STS2MCP-v107`.
3. Put `fix_sts2mcp_shop.py` in any folder. In PowerShell, navigate there.
4. Preview the exact edits:

   ```powershell
   python .\fix_sts2mcp_shop.py --dry-run
   ```

5. Apply, compile, and install the DLL:

   ```powershell
   python .\fix_sts2mcp_shop.py
   ```

   If Steam or the source checkout is in a different directory, use `--game "..." --source "..."`.

The script creates a timestamped backup under `STS2MCP-v107\backups\shop-readonly-*`, patches only `McpMod.StateBuilder.cs`, compiles using the existing `build.ps1` and installed game assemblies, and replaces only the installed `mods\STS2_MCP.dll` after successful compilation. The manifest, saves, Oracle run journal, and spreadsheet reference remain unchanged.

A failed build restores the original C# source and leaves the installed DLL unchanged. If the source has an unexpected shape, it refuses to patch anything.

## Verification

Restart the game and Oracle and enter a merchant room. Open the inventory normally, close with Escape, then click Proceed. The inventory should remain closed. Also test the Fake Merchant event if one occurs.

The script is **specific to the v0.107-compatible revision**. It does not include a compiled DLL and cannot be validated against your Windows game installation remotely.

### Temporary workaround

Before applying the patch, exit the Oracle **bridge** completely to stop repeated game-state reads. The overlay's Pause button suppresses model requests but continues to poll STS2MCP, so Pause alone does not prevent the shop reopening.

### Regression risk

The patched mod will no longer auto-open the shop as a side effect of a state read. You must interact with the merchant as normal to open it. External automation that relied on read-time auto-opening may require an explicit shop-open action.
