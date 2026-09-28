"""Premium entitlement foundation tests without Kodi runtime."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_premium():
    spec = importlib.util.spec_from_file_location('premium', ROOT / 'lib' / 'premium.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MemoryStore:
    def __init__(self, state=None):
        self.state = dict(state or {})

    def load(self):
        return dict(self.state)

    def save(self, state):
        self.state = dict(state)


class PremiumTests(unittest.TestCase):
    def test_free_is_default_and_features_are_off(self):
        premium = load_premium()
        value = premium.normalize_entitlements({}, now=123)
        self.assertEqual(value['plan'], 'free')
        self.assertFalse(value['active'])
        self.assertFalse(value['features']['trailers'])
        self.assertFalse(value['features']['ai_translation'])
        self.assertEqual(value['checkedAt'], 123)

    def test_active_plan_only_enables_server_granted_features(self):
        premium = load_premium()
        value = premium.normalize_entitlements({
            'active': True,
            'features': {'trailers': True, 'ai_translation': False, 'unknown': True},
        }, now=456)
        self.assertTrue(value['active'])
        self.assertTrue(value['features']['trailers'])
        self.assertFalse(value['features']['ai_translation'])
        self.assertNotIn('unknown', value['features'])

    def test_inactive_payload_cannot_enable_feature(self):
        premium = load_premium()
        value = premium.normalize_entitlements({
            'active': False,
            'features': {'trailers': True, 'ai_translation': True},
        }, now=789)
        self.assertFalse(value['features']['trailers'])
        self.assertFalse(value['features']['ai_translation'])

    def test_save_and_cached_round_trip(self):
        premium = load_premium()
        store = MemoryStore({'token': 'kept'})
        saved = premium.save(store, {
            'plan': 'premium',
            'features': ['trailers', 'ai_translation'],
            'expiresAt': '2030-01-01T00:00:00Z',
        }, now=1000)
        cached = premium.cached(store)
        self.assertEqual(store.state['token'], 'kept')
        self.assertEqual(saved, cached)
        self.assertTrue(premium.entitled(store, 'trailers'))
        self.assertTrue(premium.entitled(store, 'ai_translation'))

    def test_existing_uid_needs_no_network_backfill(self):
        premium = load_premium()
        store = MemoryStore({'uid': ' existing-user ', 'token': 'test-only'})
        self.assertEqual(premium.ensure_stremio_uid(store), 'existing-user')


if __name__ == '__main__':
    unittest.main()
