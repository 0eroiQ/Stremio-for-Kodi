"""MKGA Premium client boundary tests; no real network requests."""
import importlib.util
import io
import json
from pathlib import Path
import time
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
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.responses:
            raise AssertionError("unexpected request")
        return Response(self.responses.pop(0))


class Store:
    def __init__(self, state):
        self.state = dict(state)

    def load(self):
        return dict(self.state)

    def save(self, state):
        self.state = dict(state)


def session_payload(module, *, premium=False):
    return {
        "accessToken": "signed.vortexo.token",
        "expiresAt": int(time.time()) + 600,
        "product": "stremio_for_kodi",
        "premium": premium,
        "entitlements": {
            "trailers": premium,
            "ai_translation": premium,
            "skip_segments": premium
        }
    }


def entitlement_payload(*, premium=False):
    return {
        "product": "stremio_for_kodi",
        "premium": premium,
        "entitlements": {
            "trailers": premium,
            "ai_translation": premium,
            "skip_segments": premium
        }
    }

def purchase_payload(*, already_owned=False):
    return {
        "alreadyOwned": already_owned,
        "purchaseSession": None if already_owned else {
            "id": "purchase-session-123",
            "product": "stremio_for_kodi_premium",
            "status": "pending",
            "expiresAt": int(time.time()) + 900,
            "completedAt": None,
            "createdAt": int(time.time()),
            "checkoutPath": "/account.html?section=shop&kodiPurchase=purchase-session-123"
        },
        "entitlement": entitlement_payload(premium=already_owned)
    }


def translation_payload():
    return {
        "feature": "ai_translation",
        "sourceLanguage": "en",
        "targetLanguage": "bs",
        "segments": [
            {"id": "1", "text": "Zdravo"},
            {"id": "2", "text": "Laku noc"}
        ]
    }



class PremiumTests(unittest.TestCase):
    def test_stremio_auth_is_used_only_to_issue_short_lived_vortexo_token(self):
        module = load_module()
        opener = Opener([session_payload(module)])
        result = module.fetch_session("test-only-auth", opener=opener)
        self.assertEqual(result["access_token"], "signed.vortexo.token")
        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0]
        self.assertEqual(json.loads(request.data), {"authKey": "test-only-auth"})
        self.assertEqual(
            request.full_url,
            "https://mkga.tv/api/stremio-for-kodi/v1/session"
        )
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(opener.timeouts[0], module.TIMEOUT_SECONDS)

    def test_entitlement_check_uses_only_vortexo_bearer_token_and_empty_body(self):
        module = load_module()
        opener = Opener([entitlement_payload(premium=True)])
        result = module.fetch_entitlements("signed.vortexo.token", opener=opener)
        self.assertTrue(result["premium"])
        request = opener.requests[0]
        self.assertEqual(request.data, b"")
        self.assertEqual(
            request.full_url,
            "https://mkga.tv/api/stremio-for-kodi/v1/entitlements"
        )
        self.assertEqual(request.headers.get("Authorization"), "Bearer signed.vortexo.token")
        self.assertNotIn("authKey", (request.data or b"").decode("utf-8"))

    def test_rejects_client_granted_feature_shape(self):
        module = load_module()
        opener = Opener([{
            "product": "stremio_for_kodi",
            "premium": False,
            "entitlements": {"trailers": True, "ai_translation": False, "skip_segments": False}
        }])
        with self.assertRaises(module.PremiumError):
            module.fetch_entitlements("signed.vortexo.token", opener=opener)

    def test_refresh_caches_only_short_lived_vortexo_session_and_bounded_entitlement_state(self):
        module = load_module()
        store = Store({"token": "test-only-auth", "library": [{"id": "keep"}]})
        opener = Opener([
            session_payload(module, premium=True),
            entitlement_payload(premium=True)
        ])
        result = module.refresh(store, opener=opener)
        self.assertTrue(result["premium"])
        self.assertEqual(store.state["library"], [{"id": "keep"}])
        premium_state = store.state["vortexo_premium"]
        premium_session = store.state["vortexo_premium_session"]
        self.assertNotIn("token", premium_state)
        self.assertNotIn("customerId", premium_state)
        self.assertNotIn("stremioUid", premium_state)
        self.assertEqual(premium_session["access_token"], "signed.vortexo.token")
        self.assertNotIn("authKey", premium_session)
        self.assertNotIn("customerId", premium_session)
        self.assertNotIn("stremioUid", premium_session)
        self.assertEqual(len(opener.requests), 2)

    def test_cached_vortexo_token_avoids_reusing_stremio_auth_until_expiry_window(self):
        module = load_module()
        store = Store({
            "token": "test-only-auth",
            "vortexo_premium_session": {
                "access_token": "cached.vortexo.token",
                "expires_at": int(time.time()) + 300
            }
        })
        opener = Opener([entitlement_payload(premium=False)])
        result = module.refresh(store, opener=opener)
        self.assertFalse(result["premium"])
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(
            opener.requests[0].headers.get("Authorization"),
            "Bearer cached.vortexo.token"
        )

    def test_expiring_vortexo_token_is_replaced_from_stremio_auth(self):
        module = load_module()
        store = Store({
            "token": "test-only-auth",
            "vortexo_premium_session": {
                "access_token": "almost.expired.token",
                "expires_at": int(time.time()) + 5
            }
        })
        opener = Opener([
            session_payload(module, premium=False),
            entitlement_payload(premium=False)
        ])
        module.refresh(store, opener=opener)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(
            json.loads(opener.requests[0].data),
            {"authKey": "test-only-auth"}
        )
        self.assertEqual(
            opener.requests[1].headers.get("Authorization"),
            "Bearer signed.vortexo.token"
        )

    def test_ai_translation_uses_only_short_lived_vortexo_token(self):
        module = load_module()
        store = Store({
            "token": "test-only-stremio-auth",
            "vortexo_premium_session": {
                "access_token": "cached.vortexo.token",
                "expires_at": int(time.time()) + 300
            }
        })
        opener = Opener([translation_payload()])
        result = module.translate_segments(
            store,
            [{"id": "1", "text": "Hello"}, {"id": "2", "text": "Good night"}],
            "bs",
            source_language="en",
            opener=opener
        )
        self.assertEqual(result["target_language"], "bs")
        self.assertEqual(result["segments"][0]["text"], "Zdravo")
        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0]
        self.assertEqual(
            request.full_url,
            "https://mkga.tv/api/stremio-for-kodi/v1/features/ai-translation"
        )
        self.assertEqual(request.headers.get("Authorization"), "Bearer cached.vortexo.token")
        body = json.loads(request.data)
        self.assertEqual(body, {
            "sourceLanguage": "en",
            "targetLanguage": "bs",
            "segments": [
                {"id": "1", "text": "Hello"},
                {"id": "2", "text": "Good night"}
            ]
        })
        serialized = json.dumps(body)
        self.assertNotIn("test-only-stremio-auth", serialized)
        self.assertNotIn("apiKey", serialized)
        self.assertNotIn("stremioUid", serialized)

    def test_ai_translation_rejects_unbounded_or_mismatched_response(self):
        module = load_module()
        store = Store({
            "token": "test-only-stremio-auth",
            "vortexo_premium_session": {
                "access_token": "cached.vortexo.token",
                "expires_at": int(time.time()) + 300
            }
        })
        opener = Opener([{
            "feature": "ai_translation",
            "sourceLanguage": "en",
            "targetLanguage": "bs",
            "segments": [{"id": "wrong", "text": "Zdravo"}]
        }])
        with self.assertRaises(module.PremiumError):
            module.translate_segments(
                store,
                [{"id": "1", "text": "Hello"}],
                "bs",
                source_language="en",
                opener=opener
            )

    def test_purchase_session_uses_only_vortexo_bearer_token(self):
        module = load_module()
        opener = Opener([purchase_payload()])
        result = module.create_purchase_session("signed.vortexo.token", opener=opener)
        self.assertFalse(result["already_owned"])
        self.assertEqual(
            result["purchase_session"]["checkout_url"],
            "https://mkga.tv/account.html?section=shop&kodiPurchase=purchase-session-123"
        )
        request = opener.requests[0]
        self.assertEqual(request.data, b"")
        self.assertEqual(
            request.full_url,
            "https://mkga.tv/api/stremio-for-kodi/v1/purchase-sessions"
        )
        self.assertEqual(request.headers.get("Authorization"), "Bearer signed.vortexo.token")
        self.assertNotIn("authKey", (request.data or b"").decode("utf-8"))

    def test_purchase_session_rejects_untrusted_checkout_host_or_shape(self):
        module = load_module()
        bad = purchase_payload()
        bad["purchaseSession"]["checkoutPath"] = "https://evil.example/account.html?section=shop&kodiPurchase=x"
        opener = Opener([bad])
        with self.assertRaises(module.PremiumError):
            module.create_purchase_session("signed.vortexo.token", opener=opener)

    def test_prepare_purchase_reuses_or_refreshes_short_lived_session_without_exposing_stremio_identity(self):
        module = load_module()
        store = Store({
            "token": "test-only-auth",
            "vortexo_premium_session": {
                "access_token": "cached.vortexo.token",
                "expires_at": int(time.time()) + 300
            }
        })
        opener = Opener([purchase_payload()])
        result = module.prepare_purchase(store, opener=opener)
        self.assertFalse(result["already_owned"])
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(opener.requests[0].headers.get("Authorization"), "Bearer cached.vortexo.token")
        serialized = json.dumps(result)
        self.assertNotIn("test-only-auth", serialized)
        self.assertNotIn("stremioUid", serialized)
        self.assertNotIn("customerId", serialized)

    def test_public_kodi_ui_has_no_premium_purchase_handoff(self):
        default_source = (ROOT / "default.py").read_text(encoding="utf-8")
        settings_source = (ROOT / "resources" / "settings.xml").read_text(encoding="utf-8")
        self.assertNotIn("premium_buy", default_source)
        self.assertNotIn("show_purchase", default_source)
        self.assertNotIn("MKGA Premium", settings_source)
        self.assertNotIn("$4.99", settings_source)
        self.assertFalse((ROOT / "resources" / "skins" / "Main" / "1080i" / "script-vortexo-premium.xml").exists())

    def test_cached_state_rejects_unknown_grant(self):
        module = load_module()
        store = Store({
            "vortexo_premium": {
                "checked_at": 1,
                "premium": False,
                "entitlements": {"trailers": True, "ai_translation": False, "skip_segments": False}
            }
        })
        self.assertIsNone(module.cached_state(store))


    def test_stremio_hub_preserves_updated_at_for_background_sync(self):
        payload = {"linked": True, "plan": "basic", "capabilities": {}, "settings": {"preferredLanguages": ["bs"], "updatedAt": 12345}}
        module = load_module()
        result = module._bounded_stremio_hub(payload)
        self.assertEqual(result["settings"]["updatedAt"], 12345)

if __name__ == "__main__":
    unittest.main()
