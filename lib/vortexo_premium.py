"""MKGA Premium entitlement client.

The Kodi source may be public. Premium authority stays server-side at
https://mkga.tv. The client exchanges its existing Stremio authKey for a
short-lived MKGA access token; Premium APIs receive only that MKGA token.
The client never sends or trusts a caller-supplied Stremio UID, product, price,
feature grant, or payment state.
"""
from lib.ui_dialogs import dialog as themed_dialog
import json
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

BASE_URL = "https://mkga.tv"
SESSION_PATH = "/api/stremio-for-kodi/v1/session"
ENTITLEMENTS_PATH = "/api/stremio-for-kodi/v1/entitlements"
PURCHASE_PATH = "/api/stremio-for-kodi/v1/purchase-sessions"
AI_TRANSLATION_PATH = "/api/stremio-for-kodi/v1/features/ai-translation"
STREMIO_HUB_PATH = "/api/stremio-for-kodi/v1/stremio-hub"
MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 6
TOKEN_REFRESH_SKEW_SECONDS = 30
FEATURES = ("trailers", "ai_translation")
_ALLOWED_PATHS = (SESSION_PATH, ENTITLEMENTS_PATH, PURCHASE_PATH, AI_TRANSLATION_PATH, STREMIO_HUB_PATH)


from lib.theme import window as themed_window


class PremiumError(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise PremiumError("MKGA endpoint redirected; request stopped.")


def _opener():
    return build_opener(_NoRedirect())


def _validated_url(path):
    if path not in _ALLOWED_PATHS:
        raise PremiumError("Unsupported MKGA endpoint.")
    url = BASE_URL + path
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "mkga.tv":
        raise PremiumError("Invalid MKGA endpoint.")
    return url


def _read_json(request, opener=None):
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
        return json.loads(body)
    except (ValueError, TypeError):
        raise PremiumError("Invalid Premium response.") from None


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


def _bounded_session(payload):
    safe = _bounded_entitlement(payload)
    token = payload.get("accessToken") if isinstance(payload, dict) else None
    expires_at = payload.get("expiresAt") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip() or len(token) > 4096:
        raise PremiumError("Invalid Premium session.")
    if not isinstance(expires_at, int) or expires_at <= 0:
        raise PremiumError("Invalid Premium session.")
    return {
        "access_token": token.strip(),
        "expires_at": expires_at,
        "premium": safe["premium"],
        "entitlements": safe["entitlements"]
    }


def _checkout_url(path):
    if not isinstance(path, str) or not path.startswith("/account.html?"):
        raise PremiumError("Invalid Premium checkout address.")
    parsed = urlsplit(BASE_URL + path)
    if parsed.scheme != "https" or parsed.netloc != "mkga.tv" or parsed.path != "/account.html":
        raise PremiumError("Invalid Premium checkout address.")
    query = parse_qs(parsed.query, keep_blank_values=False)
    purchase_ids = query.get("kodiPurchase", [])
    if query.get("section") != ["shop"] or len(purchase_ids) != 1:
        raise PremiumError("Invalid Premium checkout address.")
    purchase_id = purchase_ids[0]
    if not purchase_id or len(purchase_id) > 128 or any(ch.isspace() for ch in purchase_id):
        raise PremiumError("Invalid Premium checkout address.")
    return parsed.geturl()


def _bounded_purchase(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("alreadyOwned"), bool):
        raise PremiumError("Invalid Premium purchase response.")
    entitlement_raw = payload.get("entitlement")
    if not isinstance(entitlement_raw, dict):
        raise PremiumError("Invalid Premium purchase response.")
    entitlement = _bounded_entitlement(entitlement_raw)
    session = payload.get("purchaseSession")
    if payload["alreadyOwned"]:
        if session is not None or not entitlement["premium"]:
            raise PremiumError("Invalid Premium purchase response.")
        return {
            "already_owned": True,
            "purchase_session": None,
            "entitlement": entitlement
        }
    if not isinstance(session, dict):
        raise PremiumError("Invalid Premium purchase response.")
    session_id = session.get("id")
    status = session.get("status")
    product = session.get("product")
    expires_at = session.get("expiresAt")
    checkout_path = session.get("checkoutPath")
    if (not isinstance(session_id, str) or not session_id or len(session_id) > 128 or
            product != "stremio_for_kodi_premium" or
            status not in ("pending", "completed", "expired", "cancelled") or
            not isinstance(expires_at, int) or expires_at <= 0):
        raise PremiumError("Invalid Premium purchase response.")
    return {
        "already_owned": False,
        "purchase_session": {
            "id": session_id,
            "status": status,
            "expires_at": expires_at,
            "checkout_url": _checkout_url(checkout_path)
        },
        "entitlement": entitlement
    }


def fetch_session(auth_key, opener=None):
    auth_key = auth_key.strip() if isinstance(auth_key, str) else ""
    if not auth_key or len(auth_key) > 1024:
        raise PremiumError("A valid Stremio session is required.")
    request = Request(
        _validated_url(SESSION_PATH),
        data=json.dumps({"authKey": auth_key}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Stremio-for-Kodi/1"
        },
        method="POST"
    )
    return _bounded_session(_read_json(request, opener=opener))


def fetch_entitlements(access_token, opener=None):
    access_token = access_token.strip() if isinstance(access_token, str) else ""
    if not access_token or len(access_token) > 4096:
        raise PremiumError("A valid MKGA Premium session is required.")
    request = Request(
        _validated_url(ENTITLEMENTS_PATH),
        data=b"",
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + access_token,
            "User-Agent": "Stremio-for-Kodi/1"
        },
        method="POST"
    )
    return _bounded_entitlement(_read_json(request, opener=opener))



def _bounded_stremio_hub(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("linked"), bool):
        raise PremiumError("Invalid MKGA Stremio settings response.")
    if not payload["linked"]:
        return {"linked": False, "plan": "basic", "capabilities": {}, "settings": None}
    plan = payload.get("plan")
    capabilities = payload.get("capabilities")
    settings = payload.get("settings")
    if plan not in ("basic", "supporter", "lifetime"):
        raise PremiumError("Invalid MKGA Stremio settings response.")
    if not isinstance(capabilities, dict) or not isinstance(settings, dict):
        raise PremiumError("Invalid MKGA Stremio settings response.")
    languages = settings.get("preferredLanguages")
    if not isinstance(languages, list) or not languages or len(languages) > 5:
        raise PremiumError("Invalid MKGA Stremio settings response.")
    clean_languages = []
    for language in languages:
        if not isinstance(language, str) or not language or len(language) > 20:
            raise PremiumError("Invalid MKGA Stremio settings response.")
        clean_languages.append(language)
    safe = {
        "preferredLanguages": clean_languages,
        "smartSubtitles": bool(settings.get("smartSubtitles")),
        "autoTranslate": bool(settings.get("autoTranslate")),
        "generateFromAudio": bool(settings.get("generateFromAudio")),
        "finishFullTitle": bool(settings.get("finishFullTitle")),
        "communityCache": bool(settings.get("communityCache")),
        "autoTiming": bool(settings.get("autoTiming")),
        "subtitleSize": str(settings.get("subtitleSize") or "medium")[:20],
        "subtitlePosition": str(settings.get("subtitlePosition") or "bottom")[:20],
        "subtitleColor": str(settings.get("subtitleColor") or "white")[:20],
    }
    return {"linked": True, "plan": plan, "capabilities": capabilities, "settings": safe}


def fetch_stremio_hub(access_token, opener=None):
    access_token = access_token.strip() if isinstance(access_token, str) else ""
    if not access_token or len(access_token) > 4096:
        raise PremiumError("A valid MKGA session is required.")
    request = Request(
        _validated_url(STREMIO_HUB_PATH),
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + access_token,
            "User-Agent": "Stremio-for-Kodi/1"
        },
        method="GET"
    )
    return _bounded_stremio_hub(_read_json(request, opener=opener))


def _bounded_translation(payload, expected_ids):
    if not isinstance(payload, dict) or payload.get("feature") != "ai_translation":
        raise PremiumError("Invalid AI translation response.")
    target = payload.get("targetLanguage")
    source = payload.get("sourceLanguage")
    rows = payload.get("segments")
    if not isinstance(target, str) or not target or not isinstance(rows, list):
        raise PremiumError("Invalid AI translation response.")
    if source is not None and not isinstance(source, str):
        raise PremiumError("Invalid AI translation response.")
    if len(rows) != len(expected_ids):
        raise PremiumError("Invalid AI translation response.")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PremiumError("Invalid AI translation response.")
        item_id = row.get("id")
        text = row.get("text")
        if (not isinstance(item_id, str) or item_id not in expected_ids or
                item_id in seen or not isinstance(text, str) or not text or len(text) > 2400):
            raise PremiumError("Invalid AI translation response.")
        seen.add(item_id)
        result.append({"id": item_id, "text": text})
    return {
        "source_language": source,
        "target_language": target,
        "segments": result
    }


def translate_segments(store, segments, target_language, source_language=None, opener=None):
    if not isinstance(segments, list) or not segments or len(segments) > 120:
        raise PremiumError("Invalid AI translation request.")
    normalized = []
    expected_ids = set()
    total = 0
    for row in segments:
        if not isinstance(row, dict):
            raise PremiumError("Invalid AI translation request.")
        item_id = row.get("id")
        text = row.get("text")
        if (not isinstance(item_id, str) or not item_id or len(item_id) > 80 or
                item_id in expected_ids or not isinstance(text, str) or not text or len(text) > 1200):
            raise PremiumError("Invalid AI translation request.")
        total += len(text)
        if total > 32 * 1024:
            raise PremiumError("Invalid AI translation request.")
        expected_ids.add(item_id)
        normalized.append({"id": item_id, "text": text})
    if not isinstance(target_language, str) or not target_language.strip():
        raise PremiumError("A target language is required.")

    state = store.load()
    session = _premium_session(state, opener=opener)
    body = {
        "targetLanguage": target_language.strip(),
        "segments": normalized
    }
    if isinstance(source_language, str) and source_language.strip():
        body["sourceLanguage"] = source_language.strip()
    request = Request(
        _validated_url(AI_TRANSLATION_PATH),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + session["access_token"],
            "User-Agent": "Stremio-for-Kodi/1"
        },
        method="POST"
    )
    result = _bounded_translation(_read_json(request, opener=opener), expected_ids)
    state["vortexo_premium_session"] = session
    store.save(state)
    return result


def create_purchase_session(access_token, opener=None):
    access_token = access_token.strip() if isinstance(access_token, str) else ""
    if not access_token or len(access_token) > 4096:
        raise PremiumError("A valid MKGA Premium session is required.")
    request = Request(
        _validated_url(PURCHASE_PATH),
        data=b"",
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + access_token,
            "User-Agent": "Stremio-for-Kodi/1"
        },
        method="POST"
    )
    return _bounded_purchase(_read_json(request, opener=opener))


def prepare_purchase(store, opener=None):
    state = store.load()
    session = _premium_session(state, opener=opener)
    result = create_purchase_session(session["access_token"], opener=opener)
    state["vortexo_premium_session"] = session
    store.save(state)
    return result


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


def _cached_access_token(state, now=None):
    value = state.get("vortexo_premium_session") if isinstance(state, dict) else None
    if not isinstance(value, dict):
        return None
    token = value.get("access_token")
    expires_at = value.get("expires_at")
    if not isinstance(token, str) or not token.strip() or len(token) > 4096:
        return None
    if not isinstance(expires_at, int):
        return None
    current = int(time.time()) if now is None else int(now)
    if expires_at <= current + TOKEN_REFRESH_SKEW_SECONDS:
        return None
    return {"access_token": token.strip(), "expires_at": expires_at}


def _premium_session(state, opener=None):
    cached = _cached_access_token(state)
    if cached:
        return cached
    auth_key = state.get("token") if isinstance(state, dict) else None
    issued = fetch_session(auth_key, opener=opener)
    return {
        "access_token": issued["access_token"],
        "expires_at": issued["expires_at"]
    }


def refresh(store, opener=None):
    state = store.load()
    session = _premium_session(state, opener=opener)
    result = fetch_entitlements(session["access_token"], opener=opener)
    saved = {
        "checked_at": int(time.time()),
        "premium": result["premium"],
        "entitlements": result["entitlements"]
    }
    state["vortexo_premium_session"] = session
    state["vortexo_premium"] = saved
    store.save(state)
    return dict(saved)


def hub_state(store, opener=None, refresh_remote=False):
    state = store.load()
    if refresh_remote:
        try:
            session = _premium_session(state, opener=opener)
            hub = fetch_stremio_hub(session["access_token"], opener=opener)
            state["vortexo_premium_session"] = session
            state["mkga_stremio_hub"] = hub
            store.save(state)
            return hub
        except PremiumError:
            pass
    cached = state.get("mkga_stremio_hub") if isinstance(state, dict) else None
    try:
        return _bounded_stremio_hub(cached)
    except PremiumError:
        return {"linked": False, "plan": "basic", "capabilities": {}, "settings": None}


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
        themed_dialog().ok(
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
        themed_dialog().ok(
            "Stremio for Kodi Premium",
            "Premium status is temporarily unavailable. Your free Stremio for Kodi features continue to work." + suffix
        )
        return

    if result["premium"]:
        enabled = [name.replace("_", " ").title()
                   for name, value in result["entitlements"].items() if value]
        detail = ", ".join(enabled) if enabled else "No Premium features enabled"
        themed_dialog().ok("Stremio for Kodi Premium", "Premium is active.\n\n" + detail)
    else:
        themed_dialog().ok(
            "Stremio for Kodi Premium",
            "This Stremio account is currently on the free plan. Premium checkout will be enabled separately on mkga.tv."
        )



def _purchase_window_class():
    import xbmcgui
    from addon_state import get_addon

    class PremiumPurchaseWindow(xbmcgui.WindowXMLDialog):
        store = None
        purchase = None
        qr_path = ""

        def onInit(self):
            checkout_url = self.purchase["purchase_session"]["checkout_url"]
            self.getControl(120).setImage(self.qr_path or "")
            self.getControl(110).setLabel(checkout_url)
            self.getControl(112).setText(
                "Scan the QR code with your phone, sign in to the same MKGA customer, "
                "and complete Premium checkout on mkga.tv."
            )
            self.getControl(111).setLabel("Waiting for Premium activation…")
            self.setFocusId(103)

        def onClick(self, control_id):
            if control_id == 103:
                self.getControl(111).setLabel("Checking Premium status…")
                try:
                    result = refresh(self.store)
                    if result["premium"]:
                        self.getControl(111).setLabel("Premium is active.")
                        themed_dialog().notification(
                            "Stremio for Kodi Premium",
                            "Premium activated.",
                            time=5000
                        )
                        self.close()
                    else:
                        self.getControl(111).setLabel("Not active yet. Finish checkout, then refresh.")
                except PremiumError:
                    self.getControl(111).setLabel("Could not check status. Free features still work.")
            elif control_id == 104:
                self.close()

        def onAction(self, action):
            if action.getId() in (10, 92, 216, 247):
                self.close()

    return PremiumPurchaseWindow, get_addon


def show_purchase():
    import xbmcgui
    from lib.signin import account_store

    store = account_store()
    state = store.load()
    auth_key = state.get("token")
    if not isinstance(auth_key, str) or not auth_key.strip():
        themed_dialog().ok(
            "Stremio for Kodi Premium",
            "Connect a Stremio account first. Premium uses the same verified Stremio identity."
        )
        return False

    try:
        result = prepare_purchase(store)
    except PremiumError:
        themed_dialog().ok(
            "Stremio for Kodi Premium",
            "Premium checkout is not available yet. Your free Stremio for Kodi features continue to work."
        )
        return False

    if result["already_owned"] or result["entitlement"]["premium"]:
        themed_dialog().ok("Stremio for Kodi Premium", "Premium is already active for this Stremio account.")
        return True

    checkout_url = result["purchase_session"]["checkout_url"]
    qr_path = ""
    try:
        import qrcode
        import xbmcvfs
        from pathlib import Path
        from addon_state import get_addon
        profile = Path(xbmcvfs.translatePath(get_addon().getAddonInfo("profile")))
        profile.mkdir(parents=True, exist_ok=True)
        qr_file = profile / "vortexo-premium-checkout-qr.png"
        qrcode.make(checkout_url).save(str(qr_file))
        qr_path = str(qr_file)
    except Exception:
        pass

    try:
        PremiumPurchaseWindow, get_addon = _purchase_window_class()
        window = themed_window(PremiumPurchaseWindow,
            "script-vortexo-premium.xml",
            get_addon().getAddonInfo("path"),
            "Main",
            "1080i"
        )
        window.store = store
        window.purchase = result
        window.qr_path = qr_path
        window.doModal()
        return True
    except Exception:
        themed_dialog().ok(
            "Stremio for Kodi Premium",
            "Open this address on your phone or computer:\n\n" + checkout_url
        )
        return True
