import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kodi_repo_build', ROOT / 'tools/build-kodi-repository.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class KodiRepositoryTests(unittest.TestCase):
    def test_feed_preserves_release_package_and_valid_installer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / 'script.stremioelec-1.2.3.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr('script.stremioelec/addon.xml',
                                 '<addon id="script.stremioelec" version="1.2.3"/>')
            before = package.read_bytes()
            target = root / 'feed'
            installer = builder.build(package, target)
            self.assertEqual(before, (target / 'script.stremioelec' / package.name).read_bytes())
            data = (target / 'addons.xml').read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), (target / 'addons.xml.sha256').read_text().strip())
            self.assertEqual([a.get('id') for a in ET.fromstring(data)],
                             ['script.stremioelec', 'repository.stremioforkodi'])
            with zipfile.ZipFile(installer) as archive:
                repo = ET.fromstring(archive.read('repository.stremioforkodi/addon.xml'))
                directory = repo.find("extension[@point='xbmc.addon.repository']/dir")
                self.assertIsNotNone(directory)
                for field in ('info', 'checksum', 'datadir'):
                    self.assertTrue(directory.findtext(field).startswith('https://'))
                self.assertEqual(directory.find('info').get('compressed'), 'false')
                self.assertEqual(directory.find('datadir').get('zip'), 'true')
                self.assertEqual(repo.get('version'), '1.0.2')
            wrong = root / 'script.stremioelec-9.9.9.zip'
            wrong.write_bytes(before)
            with self.assertRaises(ValueError):
                builder.build(wrong, target)
