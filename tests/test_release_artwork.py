"""Release artwork, feed packaging and the final episode focus boundary."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseArtworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.package = load_tool('build-stremio-addon').build(cls.root / 'packages')
        cls.publisher = load_tool('build-kodi-repository')
        cls.before = hashlib.sha256(cls.package.read_bytes()).hexdigest()
        cls.repo_zip = cls.publisher.build(cls.package, cls.root / 'feed')
        cls.feed = ET.parse(cls.root / 'feed/addons.xml')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_both_packages_and_feed_contain_every_declared_asset(self):
        for addon in self.feed.getroot():
            identity = addon.get('id')
            archive_path = self.package if identity == 'script.stremioelec' else self.repo_zip
            assets = addon.find("extension[@point='xbmc.addon.metadata']/assets")
            self.assertEqual(len(assets.findall('screenshot')), 4)
            with zipfile.ZipFile(archive_path) as archive:
                for name in self.publisher.asset_paths(addon):
                    expected = archive.read(identity + '/' + name)
                    actual = (self.root / 'feed' / identity / name).read_bytes()
                    self.assertEqual(actual, expected, name)
                    self.assertGreater(len(actual), 100)
            for screenshot in assets.findall('screenshot'):
                image = self.root / 'feed' / identity / screenshot.text
                self.assertLessEqual(image.stat().st_size, 750 * 1024)
                self.assertTrue(image.read_bytes().startswith(b'\xff\xd8'))

    def test_feed_checksum_and_original_package_are_preserved(self):
        index = (self.root / 'feed/addons.xml').read_bytes()
        expected = (self.root / 'feed/addons.xml.sha256').read_text().strip()
        self.assertEqual(hashlib.sha256(index).hexdigest(), expected)
        published = self.root / 'feed/script.stremioelec' / self.package.name
        self.assertEqual(hashlib.sha256(published.read_bytes()).hexdigest(), self.before)
        self.assertEqual(hashlib.sha256(self.package.read_bytes()).hexdigest(), self.before)

    def test_asset_paths_reject_escape_and_external_urls(self):
        for value in ('../secret.png', '/secret.png', 'https://example.org/x.png', 'a\\b.png'):
            addon = ET.fromstring('<addon><extension point="xbmc.addon.metadata"><assets /></extension></addon>')
            ET.SubElement(addon.find('.//assets'), 'icon').text = value
            with self.assertRaises(ValueError):
                self.publisher.asset_paths(addon)

    def test_package_contains_no_user_state_or_backup_files(self):
        with zipfile.ZipFile(self.package) as archive:
            for name in archive.namelist():
                parts = Path(name).parts
                self.assertNotIn('..', parts)
                self.assertNotIn('addon_data', parts)
                self.assertNotIn('__pycache__', parts)
                self.assertFalse(name.endswith(('.bak', '.pyc', '.tmp', '/account.json')))

    def test_final_episode_focus_never_enters_partial_teaser_slot(self):
        tree = ET.parse(ROOT / 'resources/skins/Main/1080i/script-stremio-info.xml')
        row = tree.find('.//control[@id="501"]')
        width = float(row.findtext('width'))
        slot = float(row.find('focusedlayout').get('width'))
        last_slot = int(row.findtext('focusposition')) + int(row.findtext('movement'))
        self.assertLessEqual((last_slot + 1) * slot, width)
        self.assertEqual(row.find('itemlayout').get('width'), '600')
        self.assertIsNotNone(tree.find('.//control[@id="7001"]//control[@id="501"]'))


if __name__ == '__main__':
    unittest.main()
