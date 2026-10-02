import re
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'core'))


class ThemedDialogLayerTests(unittest.TestCase):
    def runtime_python(self):
        for p in ROOT.rglob('*.py'):
            if any(part in p.parts for part in ('tests','tools','vendor','build-local','.git','service.mkga.connector')):
                continue
            yield p

    def test_runtime_has_no_direct_native_dialog_construction(self):
        violations=[]
        for p in self.runtime_python():
            if p.name=='ui_dialogs.py':
                continue
            text=p.read_text()
            if 'xbmcgui.Dialog()' in text or 'xbmcgui.DialogProgress()' in text or 'xbmcgui.DialogProgressBG()' in text:
                violations.append(str(p.relative_to(ROOT)))
        self.assertEqual(violations,[])

    def test_all_popup_families_have_addon_owned_xml(self):
        names=('message','confirm','select','text','input','progress','progress-bg','toast')
        for name in names:
            p=ROOT/'resources/skins/Main/1080i'/('script-stremio-dialog-'+name+'.xml')
            self.assertTrue(p.is_file(),name)
            ET.parse(p)

    def test_facade_covers_every_native_dialog_family_used_by_addon(self):
        text=(ROOT/'lib/ui_dialogs.py').read_text()
        for method in ('def ok(','def yesno(','def select(','def multiselect(',
                       'def textviewer(','def input(','def notification('):
            self.assertIn(method,text)
        self.assertIn('class ThemedProgress',text)
        self.assertIn('class InputWindow',text)

    def test_confirmation_defaults_to_cancel_and_ok_defaults_to_ok(self):
        message=ET.parse(ROOT/'resources/skins/Main/1080i/script-stremio-dialog-message.xml')
        confirm=ET.parse(ROOT/'resources/skins/Main/1080i/script-stremio-dialog-confirm.xml')
        self.assertEqual(message.findtext('.//defaultcontrol'),'201')
        self.assertEqual(confirm.findtext('.//defaultcontrol'),'202')
        source=(ROOT/'lib/ui_dialogs.py').read_text()
        self.assertIn("'script-stremio-dialog-confirm.xml'",source)

    def test_dialog_focus_tracks_every_theme(self):
        import copy
        from lib.theme import apply, PALETTES
        for filename in ('script-stremio-dialog-message.xml',
                         'script-stremio-dialog-select.xml',
                         'script-stremio-dialog-input.xml',
                         'script-stremio-dialog-progress.xml'):
            source=ET.parse(ROOT/'resources/skins/Main/1080i'/filename)
            for index,palette in enumerate(PALETTES):
                tree=copy.deepcopy(source)
                apply(tree,index)
                focus=tree.find('.//texturefocus')
                if focus is not None:
                    self.assertEqual(focus.get('colordiffuse'),palette[5],(filename,index))

    def test_more_info_uses_themed_textviewer(self):
        text=(ROOT/'lib/nimbus.py').read_text()
        self.assertIn("themed_dialog().textviewer(title, plot)",text)
        self.assertNotIn("xbmcgui.Dialog().textviewer",text)

    def test_toast_and_background_progress_are_modeless(self):
        for name in ('toast','progress-bg'):
            tree=ET.parse(ROOT/'resources/skins/Main/1080i'/('script-stremio-dialog-'+name+'.xml'))
            self.assertEqual(tree.getroot().findtext('visible'),'true')

    def test_input_is_addon_keyboard_not_native_keyboard(self):
        source=(ROOT/'lib/ui_dialogs.py').read_text()
        self.assertNotIn('xbmcgui.Keyboard',source)
        tree=ET.parse(ROOT/'resources/skins/Main/1080i/script-stremio-dialog-input.xml')
        self.assertIsNotNone(tree.find('.//control[@type="panel"][@id="600"]'))
        for cid in ('201','202','203','204','205'):
            self.assertIsNotNone(tree.find('.//control[@id="'+cid+'"]'))


if __name__=='__main__':
    unittest.main()
