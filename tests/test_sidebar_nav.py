import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from lib.sidebar_nav import ENTRIES, menu_action, menu_items, home_index

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / 'resources/skins/Main/1080i/script-stremio-nimbus.xml'

class SidebarTests(unittest.TestCase):
    def test_order_and_routes(self):
        self.assertEqual([x[0] for x in ENTRIES], ['Search','Home','Discover','Library','Addons','Settings'])
        self.assertEqual([menu_action(i) for i in range(6)], [201,202,203,204,205,206])
        for value in (-1,6,100,None,'1',True):
            self.assertEqual(menu_action(value),202)
        self.assertEqual(home_index(),1)

    def test_icons_match_items_and_exist(self):
        gui = Mock()
        gui.ListItem.side_effect = lambda label: Mock(label=label)
        items = menu_items(gui)
        self.assertEqual(len(items),6)
        for item,(label,action,name) in zip(items,ENTRIES):
            self.assertTrue(item.setArt.call_args.args[0]['icon'].endswith('/'+name+'.png'))
            item.setProperty.assert_called_once_with('sidebar_action',str(action))
            icon = ROOT/'resources/skins/Main/media/navigation-local'/(name+'.png')
            self.assertEqual(icon.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')

    def test_narrow_centred_geometry_and_weather_footer(self):
        t=ET.parse(XML)
        parents={c:p for p in t.iter() for c in p}
        menu=t.find('.//control[@id="9000"]');drawer=parents[menu]
        self.assertEqual(drawer.findtext('left'),'-276')
        self.assertEqual(drawer.find('control[@type="image"]').findtext('width'),'276')
        self.assertEqual(int(menu.findtext('top'))+6*72/2,540)
        self.assertEqual(int(menu.findtext('height')),6*72)
        for tag in ('focusedlayout','itemlayout'):
            layout=menu.find(tag)
            self.assertIn('ListItem.Art(icon)',ET.tostring(layout,encoding='unicode'))
            self.assertEqual(len(layout.findall('control[@type="label"]')),1)
        weather=drawer.find('control[@id="9901"]')
        self.assertGreater(int(weather.findtext('top')),900)
        self.assertLessEqual(int(weather.findtext('top'))+int(weather.findtext('height')),1080)
        clock=next(c for c in drawer.findall('control') if c.findtext('label')=='$INFO[System.Time]')
        self.assertLess(int(clock.findtext('top')),150)
        rows=t.find('.//control[@id="2000"]')
        self.assertTrue(any(a.get('end')=='256,0' for a in rows.findall('animation')))

    def function(self,name):
        tree=ast.parse((ROOT/'lib/nimbus.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='HomeWindow')
        return next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)

    def test_each_click_dispatches_to_correct_destination(self):
        for index,target in enumerate(('search','load_home','load_discover','load_library','load_addons','settings')):
            with self.subTest(index=index):
                window=Mock();window.rows={}
                window.getControl.return_value.getSelectedPosition.return_value=index
                dialog=Mock();dialog.input.return_value='';dialog.select.return_value=-1
                gui=Mock();gui.Dialog.return_value=dialog
                scope={'menu_action':menu_action,'xbmcgui':gui,'xbmc':Mock(),'ADDON':Mock(),'api':Mock()}
                code=ast.Module(body=[self.function('onClick')],type_ignores=[])
                exec(compile(code,'<sidebar-click>','exec'),scope)
                scope['onClick'](window,9000)
                if target=='search':
                    scope['ADDON'].getSetting.return_value = 'false'
                    dialog.input.assert_called_once_with('Search movies and series')
                    window.load_home.assert_not_called()
                elif target=='settings':
                    window.open_settings.assert_called_once_with()
                    dialog.select.assert_not_called()
                else:
                    getattr(window,target).assert_called_once_with()
                    dialog.input.assert_not_called()

    def test_search_supports_native_kodi_keyboard_setting(self):
        text=(ROOT/'lib/nimbus.py').read_text()
        self.assertIn("ADDON.getSetting('search_native_keyboard')", text)
        self.assertIn("xbmc.Keyboard('', 'Search movies and series')", text)
        settings=(ROOT/'resources/settings.xml').read_text()
        self.assertIn('id="search_native_keyboard"', settings)

    def test_initialization_keeps_home_selected(self):
        window=Mock();window.initialized=False;window.row_count=2
        scope={'menu_items':menu_items,'home_index':home_index,'xbmcgui':Mock()}
        exec(compile(ast.Module(body=[self.function('onInit')],type_ignores=[]),'<sidebar-init>','exec'),scope)
        # The sidebar test has no Kodi runtime; keep performance reporting
        # isolated from xbmc stubs installed by unrelated test modules.
        with patch('lib.weather_widget.request_refresh'), patch('lib.perf_trace.log'):
            scope['onInit'](window)
        window.getControl.return_value.selectItem.assert_called_once_with(1)
        window.load_home.assert_called_once_with()
