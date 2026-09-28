"""Vortexo Premium entitlement client.

The Kodi source may be public. Premium authority stays server-side at
https://vortexo.app. The client proves the current Stremio session with its
existing authKey; it never sends or trusts a caller-supplied Stremio UID,
product, price, feature grant, or payment state.
"""
import json
import time
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

BASE_URL = "https://vortexo.app"
ENTITLEMENTS_PATH = "/api/stremio-for-kodi/v1/entitlements"
MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 6
FEATURES = ("trailers", "ai_translation")


class PremiumError(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise PremiumError("Vortexo endpoint redirected; request stopped.")


def _opener():
    return build_opener(_NoRedirect())


def _validated_url(path):
    if path != ENTITLEMENTS_PATH:
        raise PremiumError("Unsupported Vortexo endpoint.")
    url = BASE_URL + path
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "vortexo.app":
        raise PremiumError("Invalid Vortexo endpoint.")
    return url


def _bounded_entitlement(payload):
    if not isinstance(payload, dict) or payload.get("product") != "stremio_for_kodi":
        raise PremiumError("Invalid Premium response.")
    premium = payload.get("premium")
    raw = payload.get("entitlements")
    if not isinstance(premium, bool) or not isinstance(raw, dict):
        raise PremiumError("Invalid Premium response.")
    entitlements = {}
    for feature in FEATURES:
        value = raw.get(feature)
        if not isinstance(value, bool):
            raise PremiumError("Invalid Premium response.")
        entitlements[feature] = value
    if not premium and any(entitlements.values()):
        raise PremiumError("Invalid Premium response.")
    return {"premium": premium, "entitlements": entitlements}


def fetch_entitlements(auth_key, opener=None):
    auth_key = auth_key.strip() if isinstance(auth_key, str) else ""
    if not auth_key or len(auth_key) > 1024:
        raise PremiumError("A valid Stremio session is required.")
    request = Request(
        _validated_url(ENTITLEMENTS_PATH),
        data=json.dumps({"authKey": auth_key}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Stremio-for-Kodi/1"
        },
        method="POST"
    )
    client = opener or _opener()
    try:
        with client.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except PremiumError:
        raise
    except Exception:
        raise PremiumError("Premium status is temporarily unavailable.") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise PremiumError("Premium response was too large.")
    try:
        return _bounded_entitlement(json.loads(body))
    except (ValueError, TypeError):
        raise PremiumError("Invalid Premium response.") from None


def cached_state(store):
    try:
        value = store.load().get("vortexo_premium")
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    try:
        checked_at = int(value.get("checked_at", 0))
    except (TypeError, ValueError):
        return None
    raw = {
        "product": "stremio_for_kodi",
        "premium": value.get("premium"),
        "entitlements": value.get("entitlements")
    }
    try:
        safe = _bounded_entitlement(raw)
    except PremiumError:
        return None
    safe["checked_at"] = checked_at
    return safe


def refresh(store):
    state = store.load()
    token = state.get("token")
    result = fetch_entitlements(token)
    saved = {
        "checked_at": int(time.time()),
        "premium": result["premium"],
        "entitlements": result["entitlements"]
    }
    state["vortexo_premium"] = saved
    store.save(state)
    return dict(saved)


def refresh_quiet(store):
    try:
        return refresh(store)
    except PremiumError:
        return cached_state(store)


def show_status():
    import xbmcgui
    from lib.signin import account_store

    store = account_store()
    state = store.load()
    token = state.get("token")
    if not isinstance(token, str) or not token.strip():
        xbmcgui.Dialog().ok(
            "Stremio for Kodi Premium",
            "Connect a Stremio account first. Premium uses the same Stremio identity; there is no second Vortexo login."
        )
        return

    try:
        result = refresh(store)
    except PremiumError:
        cached = cached_state(store)
        suffix = ""
        if cached:
            suffix = "\n\nLast verified status: " + ("Premium" if cached["premium"] else "Free")
        xbmcgui.Dialog().ok(
            "Stremio for Kodi Premium",
            "Premium status is temporarily unavailable. Your free Stremio for Kodi features continue to work." + suffix
        )
        return

    if result["premium"]:
        enabled = [name.replace("_", " ").title()
                   for name, value in result["entitlements"].items() if value]
        detail = ", ".join(enabled) if enabled else "No Premium features enabled"
        xbmcgui.Dialog().ok("Stremio for Kodi Premium", "Premium is active.\n\n" + detail)
    else:
        xbmcgui.Dialog().ok(
            "Stremio for Kodi Premium",
            "This Stremio account is currently on the free plan. Premium checkout will be enabled separately on vortexo.app."
        )
