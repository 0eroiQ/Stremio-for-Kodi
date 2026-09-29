"""Configure QR, account-pull safety, theme layout and return navigation."""
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from lib.addon_config import (ConfigureError, configure_target, public_site, write_qr,
                              remove_qr, find_updated_entry, sync_addons)
ROOT = Path(__file__).resolve().parents[1]


def entry(url='https://addon.example/old/manifest.json', name='Example', account=True):
    return {'id': hashlib.sha256(url.encode()).hexdigest(), 'transportUrl': url,
            'account': account, 'manifest': {'id': name, 'name': name, 'version': '1',
            'types': ['movie'], 'resources': ['stream']}}


class Store:
    def __init__(self, value): self.value, self.writes = copy.deepcopy(value), 0
    def load(self): return copy.deepcopy(self.value)
    def save(self, value): self.value = copy.deepcopy(value); self.writes += 1


class ConfigureTests(unittest.TestCase):
    def test_target_preserves_configuration_without_exposing_it_in_label(self):
        e = entry('https://addon.example/private-settings/manifest.json')
        self.assertEqual(configure_target(e), 'https://addon.example/private-settings/configure')
        self.assertEqual(public_site(e), 'https://addon.example')

    def test_invalid_targets_are_rejected_without_echoing_secrets(self):
        for url in ('http://x/private/manifest.json', 'https://u:secret@x/manifest.json',
                    'javascript:secret', 'https://x/manifest.json?secret=yes',
                    'https://x/secret\n/manifest.json', ''):
            with self.assertRaises(ConfigureError) as error: configure_target(entry(url))
            self.assertNotIn('secret', str(error.exception))

    def test_offline_qr_works_without_pillow_or_installed_qrcode(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('sys.modules', {'PIL':None,'qrcode':None}):
            path = write_qr(entry(), directory)
            data = path.read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            width, height = struct.unpack('>II', data[16:24])
            self.assertEqual(width, height); self.assertGreater(width, 200)
            if os.name == 'posix': self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            second = write_qr(entry(), directory); self.assertNotEqual(path, second)
            remove_qr(path); remove_qr(second); self.assertFalse(path.exists())

    def test_qr_write_failure_is_safe(self):
        with patch('lib.addon_config.tempfile.mkstemp', side_effect=PermissionError('private-path')):
            with self.assertRaises(ConfigureError) as error: write_qr(entry(), tempfile.gettempdir())
        self.assertNotIn('private-path', str(error.exception))
    def test_sync_preserves_local_installs_credentials_library_and_disable(self):
        old = entry(); local = entry('https://local.example/manifest.json', 'Local', False)
        new = entry('https://addon.example/new/manifest.json')
        store = Store({'token':'synthetic-token','library':[{'id':'keep'}],
                       'addons':[local,old],'disabledAddons':[old['id']], 'premium':'keep'})
        network = Mock(return_value=([new],0))
        result = sync_addons(store, old, network)
        network.assert_called_once_with('synthetic-token')
        self.assertEqual(store.value['addons'], [local,new])
        self.assertEqual(store.value['library'], [{'id':'keep'}])
        self.assertEqual(store.value['token'], 'synthetic-token')
        self.assertEqual(store.value['premium'], 'keep')
        self.assertIn(new['id'],store.value['disabledAddons'])
        self.assertEqual(result['entry']['id'],new['id']); self.assertTrue(result['changed'])

    def test_sync_reads_fresh_local_state_after_network(self):
        e=entry(); store=Store({'token':'t','addons':[e], 'library':[]})
        def network(token):
            store.value['library']=['new-progress']; return [e],0
        result=sync_addons(store,e,network)
        self.assertFalse(result['changed']); self.assertEqual(store.writes,0)
        self.assertEqual(store.value['library'],['new-progress'])

    def test_missing_account_sends_nothing(self):
        store=Store({}); network=Mock()
        with self.assertRaises(ConfigureError): sync_addons(store,entry(),network)
        network.assert_not_called(); self.assertEqual(store.writes,0)
    def test_partial_or_failed_sync_never_replaces_state(self):
        e=entry(); store=Store({'token':'t','addons':[e]}); before=store.load()
        for network in (Mock(return_value=([],1)),Mock(side_effect=OSError('secret-url'))):
            with self.assertRaises(ConfigureError): sync_addons(store,e,network)
            self.assertEqual(store.load(),before); self.assertEqual(store.writes,0)

    def test_cancelled_result_does_not_write(self):
        e=entry(); store=Store({'token':'t','addons':[e]}); stopped=[False]
        def network(token): stopped[0]=True; return [],0
        with self.assertRaises(ConfigureError):
            sync_addons(store,e,network,cancelled=lambda:stopped[0])
        self.assertEqual(store.writes,0)

    def test_changed_account_does_not_accept_old_response(self):
        e=entry(); store=Store({'token':'old','addons':[e]})
        def network(token): store.value['token']='new'; return [],0
        with self.assertRaises(ConfigureError): sync_addons(store,e,network)
        self.assertEqual(store.value['addons'],[e]); self.assertEqual(store.writes,0)

    def test_ambiguous_addon_match_is_not_guessed(self):
        old=entry(); other=[entry('https://elsewhere.example/a/manifest.json'),
                           entry('https://elsewhere.example/b/manifest.json')]
        self.assertIsNone(find_updated_entry(other,old))

    def test_successful_empty_collection_keeps_local_only_addons(self):
        old=entry(); local=entry('https://local.example/manifest.json','Local',False)
        store=Store({'token':'t','addons':[old,local]})
        sync_addons(store,old,Mock(return_value=([],0)))
        self.assertEqual(store.value['addons'],[local])
    def test_dialog_has_opaque_panel_and_all_actions_in_every_theme(self):
        from lib.theme import apply, PALETTES
        for theme,palette in enumerate(PALETTES):
            tree=ET.parse(ROOT/'resources/skins/Main/1080i/stremio-addon-config.xml')
            apply(tree,theme)
            self.assertEqual({n.get('id') for n in tree.findall('.//control[@type="button"]')}, {'1','2','3','4'})
            for node in tree.findall('.//control[@type="button"]'):
                self.assertIn('local-pill-',node.findtext('texturefocus'))
                self.assertIsNotNone(tree.find('.//control[@id="'+node.findtext('onleft')+'"]'))
                self.assertIsNotNone(tree.find('.//control[@id="'+node.findtext('onright')+'"]'))
            images=tree.findall('./controls/control[@type="image"]')
            self.assertEqual(images[0].find('texture').get('colordiffuse'),'D9000000')
            self.assertEqual(images[2].find('texture').get('colordiffuse'),palette[2])
            self.assertIsNotNone(tree.find('.//control[@id="101"]'))

    def test_existing_configure_callsite_preserves_selection_and_cleans_up(self):
        source=(ROOT/'lib/addons_page.py').read_text()
        self.assertIn('from lib.addon_config_dialog import ConfigureWindow',source)
        self.assertIn('self.load_addons(selected_identity)',source)
        self.assertIn('window.dispose()',source)
        self.assertNotIn('import qrcode',source)


if __name__ == '__main__':
    unittest.main()
