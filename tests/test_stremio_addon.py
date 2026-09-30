"""Packaging and upgrade regressions; actual Kodi smoke is still required."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT
CORE = SOURCE / 'core'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AddonTests(unittest.TestCase):
    def test_single_package_and_extensions(self):
        builder = load('builder', ROOT / 'tools/build-stremio-addon.py')
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(builder.build(directory)) as archive:
                names = archive.namelist()
                self.assertEqual({p.split('/')[0] for p in names}, {'script.stremioelec'})
                addon = ET.fromstring(archive.read('script.stremioelec/addon.xml'))
                self.assertEqual(addon.get('name'), 'Stremio for Kodi')
                self.assertEqual({p.split('/')[3] for p in names if p.startswith('script.stremioelec/resources/skins/')}, {'Main'})
                for window in ('script-stremio-nimbus.xml', 'script-stremio-info.xml', 'script-stremio-welcome.xml'):
                    self.assertIn('script.stremioelec/resources/skins/Main/1080i/' + window, names)
                extensions = addon.findall('extension')
                self.assertEqual(extensions[0].get('point'), 'xbmc.python.script')
                for extension in extensions:
                    if extension.get('library'):
                        self.assertIn('script.stremioelec/' + extension.get('library'), names)
                dependencies = addon.findall('requires/import')
                self.assertEqual([d.get('addon') for d in dependencies if d.get('optional') != 'true'], ['xbmc.python'])
                for name in names:
                    if name.endswith('.py'):
                        ast.parse(archive.read(name), filename=name)
                    if name.endswith('.xml'):
                        ET.fromstring(archive.read(name))
                self.assertFalse(any('__pycache__' in n or '.DS_Store' in n for n in names))

    def test_migration_preserves_current_data_and_does_not_resurrect_login(self):
        with patch.dict(sys.modules, {'xbmcaddon': types.ModuleType('xbmcaddon'), 'xbmcvfs': types.ModuleType('xbmcvfs')}):
            migration = load('addon_state', CORE / 'addon_state.py')
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory)/'old', Path(directory)/'new'
            old.mkdir(); new.mkdir()
            (old/'account.json').write_text(json.dumps({'token': 'test-only'}))
            (old/'settings.xml').write_text('<settings><setting id="manifest">old</setting><setting id="weather_lat">12</setting></settings>')
            (new/'settings.xml').write_text('<settings><setting id="manifest">current</setting></settings>')
            (new/'setup.json').write_text('{"welcome_done":true}')
            (old/'setup.json').write_text('{}')
            settings = {}
            migration.migrate_profile(old, new, settings.__setitem__)
            self.assertEqual(settings, {'weather_lat':'12'})
            self.assertEqual(json.loads((new/'account.json').read_text())['token'], 'test-only')
            self.assertTrue(json.loads((new/'setup.json').read_text())['welcome_done'])
            (new/'account.json').unlink()
            migration.migrate_profile(old, new, settings.__setitem__)
            self.assertFalse((new/'account.json').exists())
            self.assertTrue((old/'account.json').exists())

    def test_get_addon_survives_broken_legacy_profile(self):
        addon = Mock()
        addon.getAddonInfo.return_value = '/current'
        xbmcaddon = types.SimpleNamespace(Addon=Mock(return_value=addon))
        xbmcvfs = types.SimpleNamespace(translatePath=lambda value: value)
        with patch.dict(sys.modules, {'xbmcaddon': xbmcaddon, 'xbmcvfs': xbmcvfs}):
            migration = load('addon_state_fail_safe', CORE / 'addon_state.py')
            with patch.object(migration, 'migrate_profile', side_effect=OSError('read only')):
                self.assertIs(migration.get_addon(), addon)

    def test_migration_survives_malformed_legacy_settings(self):
        addon = Mock()
        addon.getAddonInfo.return_value = '/current'
        xbmcaddon = types.SimpleNamespace(Addon=Mock(return_value=addon))
        xbmcvfs = types.SimpleNamespace(translatePath=lambda value: value)
        with patch.dict(sys.modules, {'xbmcaddon': xbmcaddon, 'xbmcvfs': xbmcvfs}):
            migration = load('addon_state_bad_xml', CORE / 'addon_state.py')
            with patch.object(migration, 'migrate_profile', side_effect=ET.ParseError('bad xml')):
                self.assertIs(migration.get_addon(), addon)

    def test_embedded_texture_paths_exist(self):
        prefix = 'special://home/addons/script.stremioelec/'
        for path in (SOURCE/'resources/skins/Main/1080i').glob('*.xml'):
            for element in ET.parse(path).iter():
                for value in [element.text or '', *element.attrib.values()]:
                    if value.startswith(prefix):
                        self.assertTrue((SOURCE/value[len(prefix):]).is_file(), value)

    def test_ordinary_media_launch_opens_nimbus(self):
        tree = ast.parse((SOURCE / 'plugin.py').read_text())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        kodi, plugin = Mock(), Mock()
        scope = {'xbmc': kodi, 'xbmcplugin': plugin, 'HANDLE': 1}
        exec(compile(ast.Module(body=[run], type_ignores=[]), '<routing>', 'exec'), scope)
        scope['run']({})
        plugin.endOfDirectory.assert_called_once_with(1, cacheToDisc=False)
        kodi.executebuiltin.assert_called_once_with('RunScript(script.stremioelec)')

    def test_no_old_runtime_routes(self):
        for path in SOURCE.rglob('*'):
            if path.relative_to(SOURCE).parts[0] in {'.git', '.github', 'tests', 'tools', 'dist', '.venv'}:
                continue
            if path.suffix in {'.py','.xml','.json'} and path.name != 'addon_state.py':
                self.assertNotIn('plugin.video.stremioelec', path.read_text(), str(path))


if __name__ == '__main__':
    unittest.main()
