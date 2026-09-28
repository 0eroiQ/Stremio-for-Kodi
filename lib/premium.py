"""Premium entitlement foundation for Stremio for Kodi.

This module intentionally does not contact the billing backend yet. It defines the
local contract that the Vortexo website/backend can fill later. Existing free
features are not gated by this module until the server side is ready.
"""
import time

FEATURES = ('trailers', 'ai_translation')
CACHE_KEY = 'premium_entitlements'
CACHE_VERSION = 1


def _bool(value):
    return value is True or str(value).strip().lower() in ('true', '1', 'yes', 'on')


def normalize_entitlements(payload, now=None):
    """Keep only the small server-owned entitlement state the addon needs."""
    payload = payload if isinstance(payload, dict) else {}
    active = _bool(payload.get('active')) or str(payload.get('plan', '')).lower() == 'premium'
    incoming = payload.get('features', {})
    if isinstance(incoming, (list, tuple, set)):
        incoming = {name: True for name in incoming}
    if not isinstance(incoming, dict):
        incoming = {}
    features = {name: bool(active and _bool(incoming.get(name))) for name in FEATURES}
    expires = payload.get('expiresAt')
    if not isinstance(expires, str):
        expires = ''
    return {
        'version': CACHE_VERSION,
        'plan': 'premium' if active else 'free',
        'active': bool(active),
        'features': features,
        'expiresAt': expires[:80],
        'checkedAt': int(time.time() if now is None else now),
    }


def cached(store):
    state = store.load()
    value = state.get(CACHE_KEY)
    if not isinstance(value, dict) or value.get('version') != CACHE_VERSION:
        return normalize_entitlements({}, now=0)
    return normalize_entitlements(value, now=value.get('checkedAt', 0))


def save(store, payload, now=None):
    state = store.load()
    value = normalize_entitlements(payload, now=now)
    state[CACHE_KEY] = value
    store.save(state)
    return value


def entitled(store, feature):
    return bool(cached(store).get('features', {}).get(feature))


def ensure_stremio_uid(store):
    """Backfill UID for users who were already signed in before Premium existed."""
    state = store.load()
    uid = state.get('uid')
    if isinstance(uid, str) and uid.strip():
        return uid.strip()
    token = state.get('token')
    if not isinstance(token, str) or not token.strip():
        return ''
    from account import pull_user_id
    uid = pull_user_id(token)
    state['uid'] = uid
    store.save(state)
    return uid


def show_status():
    """Kodi-facing status screen. Billing/QR activation is wired in a later phase."""
    import xbmcgui
    import xbmcvfs
    from addon_state import get_addon
    from account import Store

    store = Store(xbmcvfs.translatePath(get_addon().getAddonInfo('profile')))
    state = store.load()
    if not state.get('token'):
        xbmcgui.Dialog().ok(
            'Stremio for Kodi Premium',
            'Sign in to your Stremio account first. Premium will use the same Stremio account on Kodi and the website.')
        return

    identity_ready = True
    try:
        identity_ready = bool(ensure_stremio_uid(store))
    except Exception:
        identity_ready = False

    status = cached(store)
    lines = [
        'Plan: ' + ('Premium' if status['active'] else 'Free'),
        'Stremio identity: ' + ('Ready' if identity_ready else 'Will retry automatically'),
        '',
        'Premium features:',
        '• Trailers',
        '• AI subtitle translation',
        '',
    ]
    if status['active']:
        lines.append('Your cached Premium entitlement is active.')
    else:
        lines.append('Premium billing is not connected yet. Nothing is locked in this build.')
        lines.append('When the website is ready, Get Premium will open the Vortexo purchase flow and unlock here automatically.')
    xbmcgui.Dialog().ok('Stremio for Kodi Premium', '\n'.join(lines))
