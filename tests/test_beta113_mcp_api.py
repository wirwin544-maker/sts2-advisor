"""Regression checks for seven v0.113.0 CS1061 API removals.

Fixtures mirror the upstream v0.107.1 source around the exact removed members.
These tests validate source rewrites and transaction safety, not actual C# builds.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from tools.beta113_mcp_api import (patch_all, patch_actions, patch_state,
                                   HELPER, HELPER_FILE, DISABLED_MARKER)
from tools.fix_sts2mcp_shop import PatchMismatch, NORMAL_START, NORMAL_CALL, FAKE_START, FAKE_CALL
from tools.upgrade_sts2mcp_beta import build_and_install, patch_beta_source

LOBBY_READY = '''            bool aboutToBegin = false;
            try
            {
                var runPlayers = lobby.Run?.Players;
                var connectedPlayerIds = lobby.ConnectedPlayerIds;
                aboutToBegin = runPlayers != null
                    && connectedPlayerIds != null
                    && runPlayers.Count > 0
                    && runPlayers.All(player => connectedPlayerIds.Contains(player.NetId) && lobby.IsPlayerReady(player.NetId));
            }
            catch { }
            info["all_ready"] = aboutToBegin;
            info["is_about_to_begin"] = aboutToBegin;
'''

STATE = '''    result["run"] = new Dictionary<string, object?> { ["act"] = 1 };
        // Always include full player data (relics, potions, deck, etc.) on every screen
''' + f'''                {NORMAL_START}
                var merchUI = NMerchantRoom.Instance;
                {NORMAL_CALL}
                result["state_type"] = "shop";
        {FAKE_START}
            var merchantButton = fakeMerchantNode.MerchantButton;
            {FAKE_CALL}
        // Build shop inventory from the FakeMerchant model
''' + '''    private static void SerializeShop(MerchantRoom merchantRoom) {
        var inventory = merchantRoom.GetLocalInventory();
    }
    private static void SerializeLobby(StartRunLobby lobby) {
        var obj = new Dictionary<string, object?> {
            ["max_players"] = lobby.MaxPlayers,
        };
    }
    private static void SerializeLoadLobby(LoadRunLobby lobby) {
        var info = new Dictionary<string, object?>();
            info["expected_player_count"] = lobby.Run?.Players?.Count ?? 0;
            info["connected_player_count"] = lobby.ConnectedPlayerIds?.Count ?? 0;
''' + LOBBY_READY + '''            // Per-player ready/connected breakdown
            try {
                bool isConnected = lobby.ConnectedPlayerIds?.Contains(sp.NetId) ?? false;
            } catch {}
    }
'''

ACTIONS = '''    private static Dictionary<string, object?> ExecuteShopPurchase(Player player, Dictionary<string, JsonElement> data)
    {
        var inventory = merchantRoom.GetLocalInventory();
        if (inventory == null) return Error("missing");
        _ = entry.OnTryPurchaseWrapper(inventory);
        return new Dictionary<string, object?> { ["status"] = "ok" };
    }

    private static Dictionary<string, object?> ExecuteChooseMapNode(Dictionary<string, JsonElement> data)
    {
        return Error("not in map");
    }
'''

class RemovedGameApis(unittest.TestCase):
    def test_exact_seven_compilation_errors_avoided(self):
        s, a, stats = patch_all(STATE, ACTIONS)
        self.assertNotIn('merchantRoom.GetLocalInventory()', s+a)
        self.assertNotIn('OnTryPurchaseWrapper(', a)
        self.assertNotIn('lobby.MaxPlayers', s)
        self.assertNotIn('lobby.ConnectedPlayerIds', s)
        self.assertIn('OracleGetMerchantInventory(merchantRoom)', s)
        self.assertIn('OracleGetMaxPlayers(lobby)', s)
        self.assertIn('OracleGetConnectedPlayerIds(lobby)', s)
        self.assertIn(DISABLED_MARKER, a)
        self.assertTrue(stats['purchase_disabled'])
        self.assertEqual(stats['lobby_connections'], 3)

    def test_not_inventing_unknown_lobby_connections(self):
        s, _, _ = patch_all(STATE, ACTIONS)
        self.assertIn('bool? aboutToBegin = null', s)
        self.assertIn('bool? isConnected = oracleConnected?.Contains(sp.NetId);', s)
        self.assertIn('info["connected_player_count"] = oracleConnected?.Count', s)
        self.assertIn('return null; // Current player count is NOT the maximum', HELPER)

    def test_shop_state_does_not_open_window(self):
        state, _ = patch_beta_source(STATE)
        s, a, _ = patch_all(state, ACTIONS)
        self.assertNotIn('merchUI.OpenInventory()', s)
        self.assertNotIn('merchantButton.ForceClick()', s)
        self.assertNotIn('merchUI.OpenInventory()', a)
        self.assertIn('Never open the merchant UI', HELPER) if 'Never open the merchant UI' in HELPER else self.assertIn('never clicks', HELPER)

    def test_second_patch_noop(self):
        s, a, _ = patch_all(STATE, ACTIONS)
        s2, a2, d = patch_all(s, a)
        self.assertEqual((s2,a2), (s,a))
        self.assertFalse(d['purchase_disabled'])
        self.assertFalse(d['merchant_lookups'])

    def test_unexpected_source_rejected(self):
        with self.assertRaises(PatchMismatch):patch_actions('different source')
        with self.assertRaises(PatchMismatch):patch_state('different source')

    def test_compile_failure_restores_both_sources_and_preserves_dll(self):
        with TemporaryDirectory() as td:
            base=Path(td); src=base/'source'; game=base/'steamapps'/'common'/'Slay the Spire 2'
            src.mkdir();(game/'mods').mkdir(parents=True)
            (game/'data_sts2_windows_x86_64').mkdir(parents=True)
            (src/'McpMod.StateBuilder.cs').write_text(STATE)
            (src/'McpMod.Actions.cs').write_text(ACTIONS)
            (src/'STS2_MCP.csproj').write_text('<Project />')
            (src/'build.ps1').write_text('')
            (game/'mods'/'STS2_MCP.dll').write_bytes(b'OLD_DLL')
            (game/'data_sts2_windows_x86_64'/'sts2.dll').write_bytes(b'BETA_DLL')
            def failing(*args, **kwargs):
                self.assertIn('OracleGetMerchantInventory', (src/'McpMod.StateBuilder.cs').read_text())
                self.assertNotIn('OnTryPurchaseWrapper', (src/'McpMod.Actions.cs').read_text())
                self.assertTrue((src/HELPER_FILE).is_file())
                return SimpleNamespace(returncode=1, stdout='simulated CS1061', stderr='')
            with self.assertRaises(RuntimeError):
                build_and_install(src, game, runner=failing)
            self.assertEqual((src/'McpMod.StateBuilder.cs').read_text(), STATE)
            self.assertEqual((src/'McpMod.Actions.cs').read_text(), ACTIONS)
            self.assertFalse((src/HELPER_FILE).exists())
            self.assertEqual((game/'mods'/'STS2_MCP.dll').read_bytes(), b'OLD_DLL')
            self.assertTrue(list((base/'source-backups').rglob('build.log')))

    def test_simulated_success_leaves_patched_source_and_installs_new_dll(self):
        with TemporaryDirectory() as td:
            base=Path(td); src=base/'source';game=base/'game'
            src.mkdir();(game/'mods').mkdir(parents=True)
            (game/'data_sts2_windows_x86_64').mkdir()
            (src/'McpMod.StateBuilder.cs').write_text(STATE)
            (src/'McpMod.Actions.cs').write_text(ACTIONS)
            (src/'STS2_MCP.csproj').write_text('<Project />')
            (src/'build.ps1').write_text('')
            (game/'mods'/'STS2_MCP.dll').write_bytes(b'OLD_DLL')
            (game/'data_sts2_windows_x86_64'/'sts2.dll').write_bytes(b'BETA_DLL')
            def successful(*args, **kwargs):
                out=src/'out'/'STS2_MCP'/'STS2_MCP.dll'; out.parent.mkdir(parents=True,exist_ok=True)
                out.write_bytes(b'NEW_DLL')
                return SimpleNamespace(returncode=0, stdout='BUILD SUCCEEDED (simulated)', stderr='')
            self.assertEqual(build_and_install(src,game,runner=successful),0)
            self.assertEqual((game/'mods'/'STS2_MCP.dll').read_bytes(),b'NEW_DLL')
            self.assertIn('OracleGetMerchantInventory', (src/'McpMod.StateBuilder.cs').read_text())
            self.assertIn(DISABLED_MARKER, (src/'McpMod.Actions.cs').read_text())
            self.assertTrue((src/HELPER_FILE).exists())
            self.assertEqual(build_and_install(src,game,dry_run=True,runner=successful),0)

if __name__=='__main__': unittest.main()
