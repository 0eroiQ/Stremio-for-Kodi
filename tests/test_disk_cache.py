import tempfile
import unittest
from unittest.mock import patch
from lib.disk_cache import DiskCache


class DiskCacheTests(unittest.TestCase):
    def test_survives_restart_and_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('lib.disk_cache.time.time', return_value=100):
                DiskCache(directory).put('provider/a', {'meta': {'id': 'a'}}, 10)
                self.assertEqual(DiskCache(directory).get('provider/a')['meta']['id'], 'a')
                self.assertIsNone(DiskCache(directory).get('provider/b'))
            with patch('lib.disk_cache.time.time', return_value=111):
                self.assertIsNone(DiskCache(directory).get('provider/a'))

    def test_eviction_retains_newest_and_does_not_store_url(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = DiskCache(directory, max_bytes=40)
            cache.put('secret-provider-url/a', {'data': 'a'*15}, 100)
            cache.put('secret-provider-url/b', {'data': 'b'*15}, 100)
            self.assertIsNone(cache.get('secret-provider-url/a'))
            self.assertEqual(cache.get('secret-provider-url/b'), {'data': 'b'*15})
            with cache.connect() as db:
                self.assertTrue(all(len(r[0]) == 64 for r in db.execute('SELECT key FROM responses')))

    def test_protocol_second_fetch_avoids_network(self):
        import io
        from lib import memory_cache
        memory_cache.clear()
        import protocol
        with tempfile.TemporaryDirectory() as directory:
            cache = DiskCache(directory)
            with patch('protocol._browse_cache', return_value=(cache, 900)), patch('protocol.urlopen', return_value=io.BytesIO(b'{"metas":[{"id":"a"}]}')) as network:
                self.assertEqual(protocol.fetch('https://provider/catalog/movie/top.json')['metas'][0]['id'], 'a')
                self.assertEqual(protocol.fetch('https://provider/catalog/movie/top.json')['metas'][0]['id'], 'a')
                self.assertEqual(network.call_count, 1)

    def test_streams_and_subtitles_are_not_cached(self):
        import protocol
        for resource in ('stream', 'subtitles'):
            self.assertEqual(protocol._browse_cache('https://provider/' + resource + '/movie/a.json'), (None, 0))
