"""Cache policy, persistence, migration, real-fetch and UI regressions; no network."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'core') not in sys.path:
    sys.path.insert(0, str(ROOT / 'core'))
from lib import cache_policy as policy
from lib import maintenance
from lib.disk_cache import DiskCache
import protocol


class PolicyTests(unittest.TestCase):
    def test_units_and_unlimited_are_explicit(self):
        for raw, expected in [('90', 5400), ('15m', 900), ('1.5h', 5400), ('2 hours', 7200),
                              ('7d', 604800), ('30 seconds', 30), ('1w', 604800),
                              (' unlimited ', None), ('off', 0), ('0', 0)]:
            with self.subTest(raw=raw):
                self.assertEqual(policy.parse_duration(raw), expected)
        for raw in ('', 'abc', '-1', 'nan', 'inf', '1month', '0.001s', '999999999999d'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                policy.parse_duration(raw)

    def test_size_and_defaults(self):
        self.assertEqual(policy.parse_size('128'), 128 * 1048576)
        self.assertEqual(policy.parse_size('2 GB'), 2 * 1024 ** 3)
        self.assertIsNone(policy.parse_size('unlimited'))
        self.assertEqual(policy.parse_size('off'), 0)
        result = policy.read_policy(lambda _: '')
        self.assertEqual([result[key] for key in policy.DEFAULTS], [900, 900, 86400, 86400])
        self.assertEqual(result['max_bytes'], 64 * 1048576)
        self.assertEqual(result['errors'], [])

    def test_invalid_values_fall_back_without_silent_unlimited(self):
        result = policy.read_policy(lambda _: 'invalid')
        self.assertEqual(len(result['errors']), 5)
        self.assertEqual(result['metadata'], 86400)
        self.assertEqual(result['max_bytes'], 64 * 1048576)

    def test_resource_classification(self):
        cases = {'https://provider/catalog/movie/top.json': 'catalog',
                 'https://provider/config/catalog/series/top/genre=Drama.json': 'catalog',
                 'https://provider/catalog/movie/top/search=Matrix.json': 'search',
                 'https://provider/catalog/movie/top/skip=0&search=Matrix.json': 'search',
                 'https://provider/catalog/movie/top/search=One%2FTwo.json': 'search',
                 'https://provider/catalog/movie/top/search=.json': 'search',
                 'https://provider/meta/series/tt123.json': 'metadata',
                 'https://provider/stream/movie/tt1.json': None,
                 'https://provider/subtitles/movie/tt1.json': None,
                 'https://provider/manifest.json': None,
                 'https://api.strem.io/api/datastoreGet': None,
                 'https://mkga.tv/api/stremio-for-kodi/v1/entitlements': None,
                 'https://provider/meta/private/config/stream/movie/tt1.json': None,
                 'https://api.mdblist.com/imdb/movie/tt1/?apikey=synthetic': None}
        for url, group in cases.items():
            with self.subTest(url=url):
                self.assertEqual(policy.resource_category(url), group)

    def test_disabled_category_or_size_does_not_open_a_database(self):
        values = policy.read_policy(lambda _: '')
        values['catalog'] = 0
        self.assertIsNone(policy.open_cache('catalog', values))
        values['metadata'] = None
        values['max_bytes'] = 0
        self.assertIsNone(policy.open_cache('metadata', values))


class PersistenceTests(unittest.TestCase):
    def test_unlimited_ttl_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('lib.disk_cache.time.time', return_value=100):
                DiskCache(directory, category='metadata', ttl=None).put('secret-url', {'id': 'a'}, None)
            with patch('lib.disk_cache.time.time', return_value=10 ** 10):
                cache = DiskCache(directory, category='metadata', ttl=None)
                self.assertEqual(cache.get('secret-url'), {'id': 'a'})
                with cache.connect() as db:
                    row = db.execute('SELECT key,expires,category FROM responses').fetchone()
                self.assertEqual(row, (hashlib.sha256(b'secret-url').hexdigest(), None, 'metadata'))

    def test_unlimited_time_still_respects_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = DiskCache(directory, max_bytes=35, category='metadata', ttl=None)
            with patch('lib.disk_cache.time.time', return_value=100):
                cache.put('a', {'text': 'a' * 12}, None)
            with patch('lib.disk_cache.time.time', return_value=101):
                cache.put('b', {'text': 'b' * 12}, None)
            self.assertIsNone(cache.get('a'))
            self.assertIsNotNone(cache.get('b'))

    def test_unlimited_size_does_not_disable_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = DiskCache(directory, max_bytes=None)
            with patch('lib.disk_cache.time.time', return_value=100):
                for i in range(10):
                    cache.put(str(i), {'text': 'x' * 100}, 60)
                self.assertEqual(cache.stats()['count'], 10)
            with patch('lib.disk_cache.time.time', return_value=161):
                self.assertIsNone(cache.get('1'))

    def test_zero_ttl_and_zero_limit_are_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = DiskCache(directory)
            cache.put('a', {'a': 1}, None)
            self.assertIsNone(DiskCache(directory, ttl=0).get('a'))
            cache.put('a', {'a': 2}, 0)
            self.assertIsNone(cache.get('a'))
            disabled = DiskCache(directory, max_bytes=0)
            disabled.put('b', {'b': 1}, None)
            self.assertEqual(disabled.stats()['count'], 0)

    def test_lower_lifetime_applies_to_existing_unlimited_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('lib.disk_cache.time.time', return_value=100):
                DiskCache(directory, category='catalog', ttl=None).put('a', {'id': 'a'}, None)
            with patch('lib.disk_cache.time.time', return_value=161):
                self.assertIsNone(DiskCache(directory, category='catalog', ttl=60).get('a'))

    def test_extend_unexpired_entry_but_never_resurrect_expired_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('lib.disk_cache.time.time', return_value=100):
                cache = DiskCache(directory, category='catalog', ttl=60)
                cache.put('alive', {'id': 'a'}, 60)
                cache.put('old', {'id': 'b'}, 5)
            with patch('lib.disk_cache.time.time', return_value=110):
                updated = DiskCache(directory, category='catalog', ttl=None)
                self.assertEqual(updated.get('alive'), {'id': 'a'})
                self.assertIsNone(updated.get('old'))

    def test_legacy_schema_migrates_without_losing_valid_data(self):
        with tempfile.TemporaryDirectory() as directory:
            db = sqlite3.connect(str(Path(directory) / 'browse.sqlite'))
            db.execute('CREATE TABLE responses (key TEXT PRIMARY KEY,expires REAL,used REAL,value TEXT)')
            db.execute('INSERT INTO responses VALUES (?,?,?,?)',
                       (hashlib.sha256(b'a').hexdigest(), 1000, 100, '{"id":"a"}'))
            db.commit(); db.close()
            with patch('lib.disk_cache.time.time', return_value=101):
                cache = DiskCache(directory, category='catalog', ttl=None, legacy_ttl=900)
                self.assertEqual(cache.get('a'), {'id': 'a'})
                self.assertEqual(cache.stats()['categories']['catalog']['count'], 1)

    def test_concurrent_schema_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            def run(i):
                cache = DiskCache(directory, category='catalog', ttl=600)
                cache.put(str(i), {'id': str(i)}, 600)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(run, range(8)))
            self.assertEqual(DiskCache(directory).stats()['count'], 8)

    def test_category_clear_preserves_other_data_and_account(self):
        with tempfile.TemporaryDirectory() as directory:
            account = Path(directory) / 'account.json'
            account.write_text('{"token":"synthetic"}')
            DiskCache(directory, category='catalog').put('a', {'id': 'a'}, None)
            DiskCache(directory, category='ratings').put('b', {'id': 'b'}, None)
            cache = DiskCache(directory)
            cache.clear('catalog')
            self.assertIsNone(cache.get('a'))
            self.assertIsNotNone(cache.get('b'))
            self.assertEqual(account.read_text(), '{"token":"synthetic"}')
            cache.clear()
            self.assertEqual(cache.stats()['count'], 0)
            self.assertTrue(account.exists())

    def test_corrupt_entry_is_a_miss_not_a_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = DiskCache(directory)
            cache.put('a', {'id': 'a'}, None)
            with cache.connect() as db:
                db.execute("UPDATE responses SET value='broken'")
            self.assertIsNone(cache.get('a'))

    def test_apply_policy_changes_expiry_and_size_together(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('lib.disk_cache.time.time', return_value=100):
                DiskCache(directory, category='catalog').put('a', {'id': 'a'}, None)
                DiskCache(directory, category='metadata').put('b', {'id': 'b'}, None)
            with patch('lib.disk_cache.time.time', return_value=200):
                cache = DiskCache(directory)
                cache.apply_policy({'catalog': 0, 'metadata': 500})
                self.assertIsNone(cache.get('a'))
                self.assertIsNotNone(cache.get('b'))
            with patch('lib.disk_cache.time.time', return_value=601):
                self.assertIsNone(cache.get('b'))


class IntegrationTests(unittest.TestCase):
    def test_real_protocol_uses_configured_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            values = policy.read_policy(lambda key: 'unlimited' if key == 'cache_catalog_ttl' else '')
            cache = DiskCache(directory, category='catalog', ttl=None)
            with patch('lib.cache_policy.read_policy', return_value=values), \
                 patch('lib.cache_policy.open_cache', return_value=cache) as opener, \
                 patch('protocol.urlopen', side_effect=lambda *a, **k: io.BytesIO(b'{"metas":[{"id":"a"}]}')) as network:
                for _ in range(2):
                    self.assertEqual(protocol.fetch('https://provider/catalog/movie/top.json')['metas'][0]['id'], 'a')
                self.assertEqual(network.call_count, 1)
                self.assertEqual(opener.call_args.args[0], 'catalog')
                with cache.connect() as db:
                    self.assertIsNone(db.execute('SELECT expires FROM responses').fetchone()[0])

    def test_disabled_cache_fetches_again(self):
        values = policy.read_policy(lambda key: 'off' if key == 'cache_search_ttl' else '')
        with patch('lib.cache_policy.read_policy', return_value=values), \
             patch('protocol.urlopen', side_effect=lambda *a, **k: io.BytesIO(b'{"metas":[{"id":"a"}]}')) as network:
            for _ in range(2):
                protocol.fetch('https://provider/catalog/movie/top/search=Example.json')
            self.assertEqual(network.call_count, 2)

    def test_mdblist_uses_separate_policy_and_survives_cache_failure(self):
        from lib import mdblist
        addon = Mock()
        values = {'mdblist_api_key': 'synthetic-key', 'cache_ratings_ttl': 'off', 'rating_imdb': 'true'}
        addon.getSetting.side_effect = lambda key: values.get(key, '')
        modules = {'addon_state': types.SimpleNamespace(get_addon=lambda: addon),
                   'xbmcvfs': types.SimpleNamespace(translatePath=lambda path: path)}
        with patch.dict(sys.modules, modules), \
             patch('protocol.fetch', return_value={'ratings': [{'source': 'imdb', 'value': 8.2}]}), \
             patch('lib.cache_policy.open_cache', return_value=None) as opener:
            result = mdblist.enrich({'id': 'tt123', 'type': 'movie'})
            self.assertIn('8.2', result['rating_text'])
            self.assertEqual(opener.call_args.args[0], 'ratings')
            self.assertEqual(opener.call_args.args[1]['ratings'], 0)

    def test_information_reads_real_policy_not_old_fixed_text(self):
        cache = Mock()
        cache.stats.return_value = {'count': 1, 'bytes': 1024, 'categories': {}, 'database_bytes': 4096}
        values = policy.read_policy(lambda _: 'unlimited')
        info = maintenance.information(cache, values)
        self.assertIn('Unlimited (no time expiry)', info)
        self.assertIn('Unlimited (no data-size cap)', info)
        self.assertNotIn('limit: 64 MB', info)

    def test_custom_duration_and_size(self):
        dialog = Mock()
        dialog.select.side_effect = [len(maintenance.PRESETS), 1]
        dialog.input.return_value = '2.5'
        self.assertEqual(maintenance._choose_duration(dialog, 'Catalog', '15m'), '2.5h')
        dialog.select.side_effect = [len(maintenance.SIZES)]
        dialog.input.return_value = '250'
        self.assertEqual(maintenance._choose_size(dialog), '250')

    def test_custom_cancel_and_invalid_input_do_not_save(self):
        dialog = Mock()
        dialog.select.side_effect = [len(maintenance.PRESETS), -1]
        self.assertIsNone(maintenance._choose_duration(dialog, 'Catalog', '15m'))
        dialog.input.assert_not_called()
        dialog.select.side_effect = [len(maintenance.PRESETS), 0]
        dialog.input.return_value = '-2'
        self.assertIsNone(maintenance._choose_duration(dialog, 'Catalog', '15m'))
        dialog.ok.assert_called_once()

    def test_unlimited_requires_confirmation_in_manager(self):
        dialog = Mock()
        dialog.select.return_value = maintenance.PRESETS.index('unlimited')
        dialog.yesno.return_value = False
        self.assertIsNone(maintenance._choose_duration(dialog, 'Metadata', '24h'))

    def test_manager_saves_only_selected_setting(self):
        dialog, addon = Mock(), Mock()
        addon.getSetting.return_value = ''
        dialog.select.side_effect = [0, maintenance.PRESETS.index('6h'), len(policy.GROUPS) + 2]
        with patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Dialog=lambda: dialog),
                                    'addon_state': types.SimpleNamespace(get_addon=lambda: addon)}), \
             patch.object(maintenance, 'apply_settings') as apply:
            maintenance.configure_cache()
        addon.setSetting.assert_called_once_with('cache_catalog_ttl', '6h')
        apply.assert_called_once()

    def test_settings_defaults_and_support_are_preserved(self):
        root = ET.parse(ROOT / 'resources/settings.xml')
        for group, _, default in policy.GROUPS:
            item = root.find(".//setting[@id='{}']".format(policy.setting_id(group)))
            self.assertEqual(item.get('default'), default)
        self.assertIn('Report a bug / request a feature', (ROOT / 'resources/settings.xml').read_text())
        self.assertIn('cache_configure', (ROOT / 'default.py').read_text())


if __name__ == '__main__':
    unittest.main()
