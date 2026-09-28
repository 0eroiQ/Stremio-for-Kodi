"""Vortexo Premium client boundary tests; no real network requests."""
import importlib.util
import io
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("vortexo_premium", ROOT / "lib/vortexo_premium.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, payload):
        self.body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body.read(size)


class Opener:
    def __init__(self, payload):
        self.payload = payload
        self.request = None
        self.timeout = None

    def open(self, request, timeout=None):
        self.request = request
        self.timeout = timeout
        return Response(self.payload)


class Store:
    def __init__(self, state):
        self.state = dict(state)

    def load(self):
        return dict(self.state)

    def save(self, state):
        self.state = dict(state)


class PremiumTests(unittest.TestCase):
    def test_request_sends_only_stremio_auth_proof(self):
        module = load_module()
        opener = Opener({
            "product": "stremio_for_kodi",
            "premium": False,
            "entitlements": {"trailers": False, "ai_translation": False}
        })
        result = module.fetch_entitlements("test-only-auth", opener=opener)
        self.assertFalse(result["premium"])
        self.assertEqual(json.loads(opener.request.data), {"authKey": "test-only-auth"})
        self.assertEqual(opener.request.full_url, "https://vortexo.app/api/stremio-for-kodi/v1/entitlements")
        self.assertEqual(opener.timeout, module.TIMEOUT_SECONDS)

    def test_rejects_client_granted_feature_shape(self):
        module = load_module()
        opener = Opener({
            "product": "stremio_for_kodi",
            "premium": False,
            "entitlements": {"trailers": True, "ai_translation": False}
        })
        with self.assertRaises(module.PremiumError):
            module.fetch_entitlements("test-only-auth", opener=opener)

    def test_refresh_caches_only_bounded_entitlement_state(self):
        module = load_module()
        store = Store({"token": "test-only-auth", "library": [{"id": "keep"}]})
        original = module.fetch_entitlements
        module.fetch_entitlements = lambda token: {
            "premium": True,
            "entitlements": {"trailers": True, "ai_translation": True}
        }
        try:
            result = module.refresh(store)
        finally:
            module.fetch_entitlements = original
        self.assertTrue(result["premium"])
        self.assertEqual(store.state["library"], [{"id": "keep"}])
        self.assertNotIn("token", store.state["vortexo_premium"])
        self.assertNotIn("customerId", store.state["vortexo_premium"])
        self.assertNotIn("stremioUid", store.state["vortexo_premium"])

    def test_cached_state_rejects_unknown_grant(self):
        module = load_module()
        store = Store({
            "vortexo_premium": {
                "checked_at": 1,
                "premium": False,
                "entitlements": {"trailers": True, "ai_translation": False}
            }
        })
        self.assertIsNone(module.cached_state(store))


if __name__ == "__main__":
    unittest.main()
