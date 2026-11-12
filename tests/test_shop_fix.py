"""Pure-source safety checks (no Windows, game or API required)."""
import unittest
from tools.fix_sts2mcp_shop import patch_source, PatchMismatch

NORMAL = '''        else if (currentRoom is MerchantRoom merchantRoom)
        {
            if (IsMapScreenOpenOrVisible())
            {
                result["state_type"] = "map";
                result["map"] = BuildMapState(runState);
            }
            else
            {
                // Auto-open the shopkeeper's inventory if not already open.
                // NMerchantRoom.Inventory (UI node) can be null before the scene is fully ready;
                // OpenInventory() itself accesses Inventory.IsOpen, so guard against null.
                var merchUI = NMerchantRoom.Instance;
                if (merchUI?.Inventory != null && !merchUI.Inventory.IsOpen)
                {
                    merchUI.OpenInventory();
                }
                result["state_type"] = "shop";
                result["shop"] = BuildShopState(merchantRoom, runState);
            }
        }
'''
FAKE = '''        // Auto-open the inventory if the merchant button is still available
        if (fakeMerchantNode != null)
        {
            var inventoryUI = FindFirst<NMerchantInventory>(fakeMerchantNode);
            if (inventoryUI != null && !inventoryUI.IsOpen)
            {
                // ForceClick the merchant button to go through the proper signal chain
                // (disables proceed button, wires InventoryClosed callback, etc.)
                var merchantButton = fakeMerchantNode.MerchantButton;
                if (merchantButton != null && merchantButton.Visible && merchantButton.IsEnabled)
                    merchantButton.ForceClick();
            }
        }

        // Build shop inventory from the FakeMerchant model
        var shopState = BuildFakeMerchantShopItems(fakeMerchant.Inventory);
'''

class FixShopTests(unittest.TestCase):
    def test_both_ui_actions_removed_but_state_still_read(self):
        patched, count = patch_source(NORMAL + FAKE)
        self.assertEqual(count, 2)
        self.assertNotIn('merchUI.OpenInventory();', patched)
        self.assertNotIn('merchantButton.ForceClick();', patched)
        self.assertIn('result["shop"] = BuildShopState(merchantRoom, runState);', patched)
        self.assertIn('BuildFakeMerchantShopItems(fakeMerchant.Inventory)', patched)

    def test_idempotent(self):
        once, _ = patch_source(NORMAL + FAKE)
        twice, count = patch_source(once)
        self.assertEqual(count, 0)
        self.assertEqual(twice, once)

    def test_rejects_unrecognized_source(self):
        with self.assertRaises(PatchMismatch):
            patch_source('class Unknown {}')

    def test_crlf_supported(self):
        source = (NORMAL + FAKE).replace('\n', '\r\n')
        patched, count = patch_source(source)
        self.assertEqual(count, 2)
        self.assertIn('\r\n', patched)

if __name__ == '__main__':
    unittest.main()
