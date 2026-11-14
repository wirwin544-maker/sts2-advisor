"""Public-beta v0.113.0 support without a copy of the proprietary game binary."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from bridge import beta_compat, build_catalog, combat
from bridge.monster_reference import MonsterReference
from bridge.run_memory import RunJournal
from tools.upgrade_sts2mcp_beta import (patch_mode_metadata, patch_beta_source,
                                       steam_build_id, build_and_install)


def state(char='The Fool', mode=None, floor=1):
    r={'act':1,'floor':floor,'ascension':0}
    if mode: r['game_mode']=mode
    return {'state_type':'monster', 'run':r,
            'player':{'character':char,'hand':[{'name':'Foolish Shot','id':'FOOLISH_SHOT','description':'Shoot an Arrow'}]},
            'battle':{'enemies':[{'name':'Infested Prism','entity_id':'infested_prism_0','hp':70}]}}


class Beta113OracleTests(unittest.TestCase):
    def test_fool_identified_in_four_api_shapes(self):
        self.assertEqual(build_catalog.normalize_character('THE_FOOL'), 'Fool')
        self.assertEqual(build_catalog.normalize_character('The Fool'), 'Fool')
        self.assertEqual(build_catalog.from_state({'player':{'character':{'id':'CHARACTER_FOOL'}}}), 'Fool')
        self.assertEqual(build_catalog.normalize_character('Fool'), 'Fool')

    def test_fool_entries_unranked_not_invented_winrates(self):
        choices=build_catalog.entries('Fool')
        self.assertGreaterEqual(len(choices), 4)
        self.assertEqual(choices[0]['tier'], 'Flexible')
        self.assertEqual(choices[1]['tier'], 'Unranked')
        self.assertNotIn('win-rate', choices[1]['source'])

    def test_mode_detects_nested_root_and_override(self):
        self.assertEqual(beta_compat.mode_from_state(state(mode='BlitzRun')), 'blitz')
        self.assertEqual(beta_compat.mode_from_state({'game_mode':'DREAD'}), 'dread')
        self.assertEqual(beta_compat.mode_from_state({'run':{'mode':'standard'}}), 'standard')
        self.assertEqual(beta_compat.mode_from_state(state(), 'dread'), 'dread')
        self.assertEqual(beta_compat.mode_from_state(state()), 'unknown')

    def test_blitz_no_map_no_gold_prompts(self):
        guidance=beta_compat.contextual_advice(state(mode='blitz'))
        self.assertIn('No normal map',guidance)
        self.assertIn('Gold does not matter',guidance)

    def test_dread_prompt_scales_threats(self):
        guidance=beta_compat.contextual_advice(state(mode='dread'))
        self.assertIn('all ascension modifiers',guidance.lower())
        self.assertIn('curses',guidance.lower())

    def test_fool_uses_live_arrow_availability(self):
        guidance=beta_compat.contextual_advice(state())
        self.assertIn('Aim empowers',guidance)
        self.assertIn('without an Arrow',guidance)

    def test_monster_override_discards_obsolete_radiate(self):
        data=MonsterReference([{'name':'Infested Prism','kind':'monster','hp':65,
                                'moves':[{'name':'Radiate','details':['old 20 block']}],
                                'patterns':['Radiate'], 'notes':['Radiate then attack']}], 'v0.111.0')
        text=data.prompt_for_battle(state())
        self.assertIn('Radiate REMOVED',text)
        self.assertNotIn('- Radiate:',text)
        self.assertNotIn('PATTERN: Radiate',text)
        self.assertNotIn('Radiate then attack',text)

    def test_tunneler_and_changed_card_notes(self):
        st=state()
        st['battle']['enemies']=[{'name':'Tunneler'}]
        st['player']['hand']=[{'name':'Memento Mori'}]
        facts=beta_compat.contextual_advice(st)
        self.assertIn('From Below',facts)
        self.assertIn('Cost 3',facts)

    def test_legacy_reference_still_used(self):
        data=MonsterReference([{'name':'Shrinker Beetle','kind':'monster','hp':15,
                                'moves':[{'name':'Bite','details':['9 damage']}]}],'v0.111.0')
        st=state();st['battle']['enemies']=[{'name':'Shrinker Beetle'}]
        self.assertIn('Bite',data.prompt_for_battle(st))

    def test_mode_persisted_in_run_memory(self):
        with tempfile.TemporaryDirectory() as d:
            journal=RunJournal(d)
            st=state(mode='Blitz',floor=1)
            self.assertTrue(journal.observe(st))
            self.assertEqual(journal.active['game_mode'],'blitz')
            self.assertEqual(json.loads(journal.status_path.read_text())['game_mode'],'blitz')
            self.assertFalse(journal.observe(state(mode='Blitz',floor=2)))
            previous=journal.run_id
            self.assertTrue(journal.observe(state(mode='dread',floor=1)))
            self.assertNotEqual(previous,journal.run_id)

    def test_combat_mode_in_summary(self):
        st=state(mode='blitz');st['battle'].update({'round':1,'turn':'player'})
        self.assertEqual(combat.summary(st,'sig','run')['game_mode'],'blitz')

    def test_mode_injection_idempotent(self):
        code='''    result["run"] = new Dictionary<string, object?> { ["act"] = 1 };
        // Always include full player data (relics, potions, deck, etc.) on every screen
'''
        patched,added=patch_mode_metadata(code)
        self.assertTrue(added)
        self.assertIn('GetProperty("GameMode"',patched)
        again,added=patch_mode_metadata(patched)
        self.assertFalse(added)
        self.assertEqual(again,patched)

    def test_refuse_missing_mode_anchor(self):
        from tools.fix_sts2mcp_shop import PatchMismatch
        with self.assertRaises(PatchMismatch):
            patch_mode_metadata('no expected method')

    def test_steam_manifest_build(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'steamapps'/'common'/'Slay the Spire 2'
            folder.mkdir(parents=True)
            (folder.parent.parent/'appmanifest_2868840.acf').write_text('"buildid"  "26625880"')
            self.assertEqual(steam_build_id(folder),'26625880')

    def test_build_failure_does_not_overwrite_dll_and_restores_source(self):
        from tools.fix_sts2mcp_shop import NORMAL_START,NORMAL_CALL,FAKE_START,FAKE_CALL
        raw=(
            'result["run"] = new Dictionary<string, object?> { ["act"] = 1 };\n'
            '        // Always include full player data (relics, potions, deck, etc.) on every screen\n'
            f'                {NORMAL_START}\n'
            '                var merchUI = NMerchantRoom.Instance;\n'
            f'                {NORMAL_CALL}\n'
            '                result["state_type"] = "shop";\n'
            f'        {FAKE_START}\n'
            '            var merchantButton = fakeMerchantNode.MerchantButton;\n'
            f'            {FAKE_CALL}\n'
            '        // Build shop inventory from the FakeMerchant model\n'
        )
        # test without Windows because runner is injectable
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);src=p/'source';game=p/'steamapps'/'common'/'Slay the Spire 2'
            src.mkdir();(game/'mods').mkdir(parents=True)
            (game/'data_sts2_windows_x86_64').mkdir(parents=True)
            (src/'McpMod.StateBuilder.cs').write_text(raw)
            (src/'build.ps1').write_text('')
            (game/'mods'/'STS2_MCP.dll').write_bytes(b'OLD')
            (game/'data_sts2_windows_x86_64'/'sts2.dll').write_bytes(b'beta')
            # No toolchain is run; simulated nonzero code makes sure installed file is untouched
            def fail(*a,**kw):return SimpleNamespace(returncode=1,stdout='error CS0000',stderr='')
            with self.assertRaises(RuntimeError):
                build_and_install(src,game,runner=fail)
            self.assertEqual((src/'McpMod.StateBuilder.cs').read_text(),raw)
            self.assertEqual((game/'mods'/'STS2_MCP.dll').read_bytes(),b'OLD')
            self.assertTrue(list((p/'source-backups').rglob('build.log')))


if __name__=='__main__':unittest.main()
