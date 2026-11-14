"""Guarded v0.113 STS2MCP source transformations for removed game APIs.

These are source-level edits, NOT a claim of binary compatibility. A local build
against the user's exact game assemblies is required to verify compilation.
A removed shop-purchase API is intentionally disabled rather than guessed.
"""
from __future__ import annotations

from .fix_sts2mcp_shop import PatchMismatch

ACTIONS_HEAD = '    private static Dictionary<string, object?> ExecuteShopPurchase(Player player, Dictionary<string, JsonElement> data)'
ACTIONS_NEXT = '    private static Dictionary<string, object?> ExecuteChooseMapNode('
DISABLED_MARKER = 'Shop buying through STS2MCP is disabled on beta v0.113.0'

LOBBY_READY_START = '            // LoadRunLobby no longer exposes IsAboutToBeginGame'
LOBBY_READY_END = '            // Per-player ready/connected breakdown'
LOBBY_LIST_MARKER = '            info["expected_player_count"] = lobby.Run?.Players?.Count ?? 0;'
LOBBY_COUNT_OLD = '            info["connected_player_count"] = lobby.ConnectedPlayerIds?.Count ?? 0;'

HELPER_FILE = 'McpMod.OracleBetaCompat.cs'
HELPER_MARKER = '// Oracle v0.113 beta compatibility. Avoid deleted compile-time game API members.'

HELPER = r'''using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Multiplayer.Game.Lobby;

namespace STS2_MCP;

public static partial class McpMod
{
    // Oracle v0.113 beta compatibility. Avoid deleted compile-time game API members.
    private const BindingFlags OracleMemberFlags = BindingFlags.Instance |
        BindingFlags.Public | BindingFlags.NonPublic;

    private static object? OracleGetMember(object? target, string name)
    {
        if (target == null) return null;
        try
        {
            var t = target.GetType();
            var prop = t.GetProperty(name, OracleMemberFlags);
            if (prop != null && prop.GetIndexParameters().Length == 0)
                return prop.GetValue(target);
            return t.GetField(name, OracleMemberFlags)?.GetValue(target);
        }
        catch { return null; }
    }

    private static MerchantInventory? OracleUnwrapInventory(object? value, int depth = 0)
    {
        if (value is MerchantInventory inv) return inv;
        if (value == null || depth >= 2) return null;
        // A multi-player collection is ambiguous without a local player key.
        // Only unwrap a container with exactly ONE candidate.
        if (value is IDictionary map && map.Count == 1)
        {
            foreach (DictionaryEntry entry in map)
                return OracleUnwrapInventory(entry.Value, depth + 1);
        }
        foreach (var member in new[] { "Inventory", "_inventory", "MerchantInventory", "Model", "Value" })
        {
            var nested = OracleGetMember(value, member);
            if (nested != null && !ReferenceEquals(nested, value))
            {
                var result = OracleUnwrapInventory(nested, depth + 1);
                if (result != null) return result;
            }
        }
        return null;
    }

    private static MerchantInventory? OracleGetMerchantInventory(MerchantRoom room)
    {
        foreach (var name in new[] { "GetLocalInventory", "GetInventory" })
        {
            try
            {
                var method = room.GetType().GetMethod(name, OracleMemberFlags,
                    binder: null, types: Type.EmptyTypes, modifiers: null);
                if (method != null)
                {
                    var result = OracleUnwrapInventory(method.Invoke(room, null));
                    if (result != null) return result;
                }
            }
            catch { /* Beta members may not be callable. Continue read-only. */ }
        }
        foreach (var name in new[] { "LocalInventory", "_localInventory", "Inventory",
                                      "_inventory", "MerchantInventory", "_merchantInventory",
                                      "Inventories", "_inventories" })
        {
            var result = OracleUnwrapInventory(OracleGetMember(room, name));
            if (result != null) return result;
        }
        // Read the already-open UI's model if available. This never clicks,
        // opens or focuses the shop inventory.
        var uiModel = OracleUnwrapInventory(OracleGetMember(NMerchantRoom.Instance, "Inventory"));
        if (uiModel != null) return uiModel;
        return null;
    }

    private static int? OracleGetMaxPlayers(StartRunLobby lobby)
    {
        foreach (var name in new[] { "MaxPlayers", "MaxPlayerCount", "PlayerLimit", "PlayerCapacity" })
        {
            var v = OracleGetMember(lobby, name);
            if (v == null) continue;
            try { return Convert.ToInt32(v); } catch { }
        }
        return null; // Current player count is NOT the maximum lobby size.
    }

    private static HashSet<ulong>? OracleGetConnectedPlayerIds(LoadRunLobby lobby)
    {
        object? ids = null;
        foreach (var name in new[] { "ConnectedPlayerIds", "_connectedPlayerIds",
                                      "ConnectedIds", "ConnectedPlayers", "_connectedPlayers" })
        {
            ids = OracleGetMember(lobby, name);
            if (ids != null) break;
        }
        if (ids is not IEnumerable seq) return null; // Unknown differs from empty.
        var connected = new HashSet<ulong>();
        try
        {
            foreach (var item in seq)
            {
                var raw = OracleGetMember(item, "NetId") ?? OracleGetMember(item, "id") ?? item;
                if (raw != null) connected.Add(Convert.ToUInt64(raw));
            }
        }
        catch { return null; }
        return connected;
    }
}
'''


def patch_actions(src: str) -> tuple[str, bool]:
    """Disable removed shop purchase entry point rather than guessing a new action."""
    if src.count(ACTIONS_HEAD) != 1 or src.count(ACTIONS_NEXT) != 1:
        raise PatchMismatch('Cannot identify unique shop purchase method boundaries')
    start = src.index(ACTIONS_HEAD)
    end = src.index(ACTIONS_NEXT, start)
    method = src[start:end]
    if DISABLED_MARKER in method:
        if 'OnTryPurchaseWrapper' in method or 'GetLocalInventory()' in method:
            raise PatchMismatch('Partially patched shop buying method')
        return src, False
    if 'OnTryPurchaseWrapper(inventory)' not in method or 'GetLocalInventory()' not in method:
        raise PatchMismatch('Unexpected shop buying source; refusing unsafe replacement')
    replacement = f'''{ACTIONS_HEAD}
    {{
        // Removed beta purchase API. Oracle is read-only and never calls this action.
        // Avoid opening shop windows or guessing a replacement purchase callback.
        return Error("{DISABLED_MARKER}; purchase manually in the game.");
    }}

'''
    return src[:start] + replacement + src[end:], True


def patch_state(src: str) -> tuple[str, dict[str, int]]:
    """Replace beta-removed merchant/lobby APIs with reflection-backed metadata."""
    stats = {'merchant_lookups': 0, 'lobby_max': 0, 'lobby_connections': 0}
    merchant_old = 'var inventory = merchantRoom.GetLocalInventory();'
    merchant_new = 'var inventory = OracleGetMerchantInventory(merchantRoom);'
    if merchant_old in src:
        if src.count(merchant_old) != 1:
            raise PatchMismatch('Unexpected number of merchant inventory reads')
        src = src.replace(merchant_old, merchant_new)
        stats['merchant_lookups'] = 1
    elif merchant_new not in src:
        raise PatchMismatch('Merchant inventory read not found')

    max_old = '["max_players"] = lobby.MaxPlayers,'
    max_new = '["max_players"] = OracleGetMaxPlayers(lobby),'
    if max_old in src:
        if src.count(max_old) != 1: raise PatchMismatch('Multiple max player references')
        src = src.replace(max_old, max_new)
        stats['lobby_max'] = 1
    elif max_new not in src:
        raise PatchMismatch('Lobby max player entry not found')

    # Newer beta LoadRunLobby does not publish ConnectedPlayerIds. Preserve an
    # unknown/null state if reflection cannot recover membership data.
    connected_old = LOBBY_LIST_MARKER + '\n' + LOBBY_COUNT_OLD
    connected_new = ('            var oracleConnected = OracleGetConnectedPlayerIds(lobby);\n'
                     + LOBBY_LIST_MARKER + '\n'
                     + '            info["connected_player_count"] = oracleConnected?.Count;')
    if connected_old in src:
        src = src.replace(connected_old, connected_new, 1)
        stats['lobby_connections'] += 1
    elif connected_new not in src:
        raise PatchMismatch('Load lobby connection counts not found')

    ready_old = '''            bool aboutToBegin = false;
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
    ready_new = '''            bool? aboutToBegin = null;
            try
            {
                var runPlayers = lobby.Run?.Players;
                if (runPlayers != null && oracleConnected != null)
                    aboutToBegin = runPlayers.Count > 0 &&
                        runPlayers.All(player => oracleConnected.Contains(player.NetId) && lobby.IsPlayerReady(player.NetId));
            }
            catch { /* Leave unknown rather than claim player readiness. */ }
            info["all_ready"] = aboutToBegin;
            info["is_about_to_begin"] = aboutToBegin;
'''
    if ready_old in src:
        src = src.replace(ready_old, ready_new, 1)
        stats['lobby_connections'] += 1
    elif ready_new not in src:
        raise PatchMismatch('Load lobby readiness summary not found')

    per_old = 'bool isConnected = lobby.ConnectedPlayerIds?.Contains(sp.NetId) ?? false;'
    per_new = 'bool? isConnected = oracleConnected?.Contains(sp.NetId);'
    if per_old in src:
        src = src.replace(per_old, per_new)
        stats['lobby_connections'] += 1
    elif per_new not in src:
        raise PatchMismatch('Load lobby per-player connection line not found')

    if any(s in src for s in ('merchantRoom.GetLocalInventory()', 'lobby.MaxPlayers', 'lobby.ConnectedPlayerIds')):
        raise PatchMismatch('Removed game API references remain in state builder')
    return src, stats


def patch_all(state: str, actions: str) -> tuple[str, str, dict]:
    a, disabled = patch_actions(actions)
    s, stats = patch_state(state)
    return s, a, {'purchase_disabled': disabled, **stats}
