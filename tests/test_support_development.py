"""Live support branding: local assets, verified link and a close-only UI."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
LINK = 'https://donate.stripe.com/dRm28t1sm7MQ6dnaUs7kc00'
spec = importlib.util.spec_from_file_location('support_under_test', ROOT / 'support_development.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)

class SupportTests(unittest.TestCase):
    def test_live_link_and_qr_integrity(self):
        url, test, qr = support.load_config(ROOT)
        self.assertEqual(url, LINK)
        self.assertFalse(test)
        config = json.loads((ROOT/'resources/branding/support.json').read_text())
        self.assertEqual(config['qr_sha256'], hashlib.sha256(qr.read_bytes()).hexdigest())

    def test_icons_and_background_geometry(self):
        for name, ratio in (('icon.png', (1, 1)), ('fanart.png', (16, 9))):
            data = (ROOT/name).read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            width, height = struct.unpack('>II', data[16:24])
            self.assertEqual(width * ratio[1], height * ratio[0])
            self.assertGreaterEqual(width, 512)

    def test_assets_and_optional_settings_entry(self):
        addon = ET.parse(ROOT/'addon.xml')
        self.assertEqual(addon.findtext('.//assets/icon'), 'icon.png')
        self.assertEqual(addon.findtext('.//assets/fanart'), 'fanart.png')
        entries = [n for n in ET.parse(ROOT/'resources/settings.xml').iter('setting')
                   if 'support_development.py' in n.get('action', '')]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].get('label'), 'Support development')
        self.assertEqual(entries[0].get('type'), 'action')
        self.assertIsNone(entries[0].get('default'))

    def test_xml_assets_are_self_contained(self):
        tree = ET.parse(ROOT/'resources/skins/Main/1080i/stremio-support-development.xml')
        for node in tree.iter():
            if node.tag in ('texture', 'texturefocus', 'texturenofocus') and node.text:
                relative = node.text.split('script.stremioelec/', 1)[-1]
                self.assertTrue((ROOT/relative).is_file(), relative)
        self.assertEqual(len(tree.findall('.//control[@type="button"]')), 1)

    def test_mismatched_mode_and_untrusted_url_are_rejected(self):
        for change in ({'mode':'test'}, {'url':'https://donate.stripe.com.evil.test/x'},
                       {'url':LINK+'?customer=private'}, {'schemaVersion':2}):
            with tempfile.TemporaryDirectory() as temp:
                dest=Path(temp)
                shutil.copytree(ROOT/'resources/branding', dest/'resources/branding')
                p=dest/'resources/branding/support.json'
                data=json.loads(p.read_text()); data.update(change)
                p.write_text(json.dumps(data))
                with self.assertRaises(ValueError): support.load_config(dest)

    def test_dialog_only_displays_and_closes(self):
        class Window:
            def __init__(self): self.props={}; self.closed=False
            def getControl(self, cid): return types.SimpleNamespace(setImage=lambda *args: None)
            def setProperty(self, key, value): self.props[key]=value
            def setFocusId(self, cid): self.focus=cid
            def close(self): self.closed=True
        win=support.dialog_class(types.SimpleNamespace(WindowXMLDialog=Window))()
        win.onInit()
        self.assertEqual(win.props['support_url'], LINK)
        self.assertEqual(win.props['support_mode'], 'Optional one-time developer tip')
        self.assertNotIn('TEST', win.props['support_mode'])
        win.onClick(99); self.assertFalse(win.closed)
        win.onAction(types.SimpleNamespace(getId=lambda:92)); self.assertTrue(win.closed)

    def test_python38_and_no_account_or_payment_operations(self):
        text=(ROOT/'support_development.py').read_text()
        ast.parse(text, feature_version=(3, 8))
        for forbidden in ('api.STORE', 'urlopen(', 'requests.', 'setSetting(', 'sk_live_', 'pk_live_'):
            self.assertNotIn(forbidden, text)

if __name__ == '__main__':
    unittest.main()
