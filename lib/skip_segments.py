"""Supporter skip buttons backed by IntroDB's free read API.

Read-only integration: one lookup per playback identity with a 24h local cache.
No IntroDB API key or MKGA/Stremio credential is sent to IntroDB.
"""
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

import xbmc
import xbmcgui

from account import Store
from lib.theme import window as themed_window

INTRODB_ORIGIN = "https://api.introdb.app"
CACHE_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 6
ROOT = str(Path(__file__).resolve().parents[1])
SEGMENT_ORDER = ("recap", "intro", "outro", "post_credits")
LABELS = {
    "intro": "Skip Intro",
    "recap": "Skip Recap",
    "outro": "Skip Outro",
    "post_credits": "Skip Post-Credits",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _preferences():
    defaults = {"intro": True, "recap": True, "outro": True, "post_credits": True}
    try:
        from lib.signin import account_store
        from lib.vortexo_premium import hub_state
        hub = hub_state(account_store(), refresh_remote=False, max_age=300)
        settings = hub.get("mkgaSettings") if isinstance(hub, dict) else None
        if not isinstance(settings, dict):
            return defaults
        return {
            "intro": bool(settings.get("skipIntro", True)),
            "recap": bool(settings.get("skipRecap", True)),
            "outro": bool(settings.get("skipOutro", True)),
            "post_credits": bool(settings.get("skipPostCredits", True)),
        }
    except Exception:
        return defaults


def _supporter_enabled():
    try:
        from lib.signin import account_store
        from lib.vortexo_premium import cached_state, refresh_quiet
        store = account_store()
        state = cached_state(store)
        if not state or int(time.time()) - int(state.get("checked_at") or 0) > 300:
            state = refresh_quiet(store)
        return bool(state and state.get("entitlements", {}).get("skip_segments"))
    except Exception:
        return False


def _identity(kind, value):
    raw = str(value or "").strip()
    if kind == "series":
        parts = raw.split(":")
        if len(parts) != 3 or not parts[0].startswith("tt"):
            return None
        try:
            season, episode = int(parts[1]), int(parts[2])
        except (TypeError, ValueError):
            return None
        if season < 0 or episode < 1:
            return None
        return {"imdb_id": parts[0], "season": season, "episode": episode}
    if kind == "movie" and raw.startswith("tt"):
        return {"imdb_id": raw, "is_movie": "true"}
    return None


def _cache_key(identity):
    if identity.get("is_movie") == "true":
        return "movie:" + identity["imdb_id"]
    return "series:{}:{}:{}".format(identity["imdb_id"], identity["season"], identity["episode"])


def _clean_segment(name, row):
    if not isinstance(row, dict):
        return None
    try:
        start = float(row.get("start_sec"))
        end = float(row.get("end_sec"))
    except (TypeError, ValueError):
        return None
    if start < 0 or end <= start or end - start > 1800:
        return None
    return {
        "type": name,
        "label": LABELS.get(name, "Skip"),
        "start": start,
        "end": end,
        "confidence": float(row.get("confidence") or 0),
    }


def fetch_segments(profile, kind, value, opener=None, now=None):
    identity = _identity(kind, value)
    if not identity:
        return []
    now = int(time.time()) if now is None else int(now)
    store = Store(Path(profile) / "introdb-cache")
    key = _cache_key(identity)
    try:
        cache = store.load()
    except Exception:
        cache = {}
    row = cache.get(key) if isinstance(cache, dict) else None
    if isinstance(row, dict) and now - int(row.get("checked_at") or 0) < CACHE_SECONDS:
        return row.get("segments") if isinstance(row.get("segments"), list) else []
    query = urlencode(identity)
    url = INTRODB_ORIGIN + "/segments?" + query
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.introdb.app" or parsed.path != "/segments":
        return []
    client = opener or build_opener(_NoRedirect())
    try:
        with client.open(Request(url, headers={"Accept": "application/json", "User-Agent": "Stremio-for-Kodi/1"}), timeout=TIMEOUT_SECONDS) as response:
            data = response.read(128 * 1024 + 1)
        if len(data) > 128 * 1024:
            return []
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        return []
    segments = []
    for name in SEGMENT_ORDER:
        item = _clean_segment(name, payload.get(name) if isinstance(payload, dict) else None)
        if item:
            segments.append(item)
    cache[key] = {"checked_at": now, "segments": segments}
    # Keep cache bounded to recent lookups only.
    if len(cache) > 100:
        cache = dict(sorted(cache.items(), key=lambda kv: int(kv[1].get("checked_at") or 0), reverse=True)[:100])
    try:
        store.save(cache)
    except Exception:
        pass
    return segments


class SkipWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.label = str(kwargs.pop("label", "Skip"))
        self.on_skip = kwargs.pop("on_skip", None)
        super().__init__(*args, **kwargs)

    def onInit(self):
        self.setProperty("skip_label", self.label)
        self.setFocusId(201)

    def onClick(self, control_id):
        if control_id == 201:
            callback = self.on_skip
            self.close()
            if callable(callback):
                try:
                    callback()
                except Exception:
                    pass

    def onAction(self, action):
        if action.getId() in (10, 92, 216, 247):
            self.close()


class SkipSegmentWatcher:
    def __init__(self, profile):
        self.profile = Path(profile)
        self.player = xbmc.Player()
        self.current_hash = None
        self.segments = []
        self.dismissed = set()
        self.loading = False
        self.window = None
        self.visible_type = None
        self.lock = threading.Lock()

    def close(self, dismiss=False):
        if dismiss and self.visible_type:
            self.dismissed.add(self.visible_type)
        if self.window:
            try:
                self.window.close()
            except Exception:
                pass
        self.window = None
        self.visible_type = None

    def _current_hash(self):
        try:
            if not self.player.isPlayingVideo():
                return None
            import hashlib
            return hashlib.sha256(self.player.getPlayingFile().encode()).hexdigest()
        except Exception:
            return None

    def _context(self, digest):
        try:
            context = Store(self.profile / "playback").load()
            return context if context.get("url_hash") == digest else None
        except Exception:
            return None

    def _load(self, digest):
        try:
            context = self._context(digest)
            segments = []
            if context and _supporter_enabled():
                enabled = _preferences()
                segments = [segment for segment in fetch_segments(self.profile, context.get("kind"), context.get("id")) if enabled.get(segment.get("type"), True)]
            with self.lock:
                if self.current_hash == digest:
                    self.segments = segments
        finally:
            self.loading = False

    def _start(self, digest):
        self.close()
        self.current_hash = digest
        self.segments = []
        self.dismissed = set()
        if not digest or self.loading:
            return
        self.loading = True
        threading.Thread(target=self._load, args=(digest,), daemon=True).start()

    def _seek(self, segment):
        try:
            self.player.seekTime(float(segment["end"]) + 0.15)
        finally:
            self.dismissed.add(segment["type"])

    def _show(self, segment):
        if self.window or segment["type"] in self.dismissed:
            return
        self.visible_type = segment["type"]
        try:
            self.window = themed_window(
                SkipWindow, "script-stremio-skip.xml", ROOT, "Main", "1080i",
                label=segment["label"], on_skip=lambda: self._seek(segment)
            )
            self.window.show()
        except Exception:
            self.window = None
            self.visible_type = None

    def tick(self):
        digest = self._current_hash()
        if digest != self.current_hash:
            self._start(digest)
        if not digest:
            self.close()
            return
        try:
            position = float(self.player.getTime())
        except Exception:
            return
        active = None
        with self.lock:
            for segment in self.segments:
                # Give the button a brief lead-in and keep it through the segment.
                if segment["start"] - 1.5 <= position < segment["end"] - 0.25:
                    active = segment
                    break
        if active:
            if self.visible_type != active["type"]:
                self.close()
            self._show(active)
        elif self.window:
            self.close()
