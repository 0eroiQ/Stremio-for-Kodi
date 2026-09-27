import unittest
from lib.hero_metadata import prepare


class HeroMetadataTests(unittest.TestCase):
    def test_catalog_reuse_and_missing_details_preserve_account_state(self):
        rows = [{'id': 'a', 'type': 'movie', 'state': {'timeOffset': 42}},
                {'id': 'b', 'type': 'series', 'name': 'Preview'}]
        catalogs = [{'items': [{'id': 'a', 'type': 'movie', 'description': 'Plot A',
                                'background': 'Backdrop A', 'logo': 'Logo A'}]}]
        calls = []
        def fetch(row):
            calls.append(row['id'])
            return dict(row, description='Plot B', background='Backdrop B', logo='Logo B')
        result = prepare(rows, catalogs, fetch)
        self.assertEqual(calls, ['b'])
        self.assertEqual([r['id'] for r in result], ['a', 'b'])
        self.assertEqual(result[0]['state'], {'timeOffset': 42})
        self.assertEqual(result[1]['description'], 'Plot B')
        self.assertNotIn('description', rows[0])

    def test_provider_failure_keeps_title_available(self):
        row = {'id': 'a', 'type': 'movie', 'name': 'Offline'}
        def fail(row):
            raise ValueError('unavailable')
        self.assertEqual(prepare([row], [], fail), [row])
