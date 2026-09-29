"""Persistent Stremio for Kodi service: startup launch + AUTO AI subtitles."""
import hashlib
import sys
import threading
from pathlib import Path

_CORE = Path(__file__).resolve().parent / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import xbmc
import xbmcgui
import xbmcvfs

from account import Store
from addon_state import get_addon
from addons_core import active_addons
from ai_subtitles import CODE_NAMES, local_settings, prepare_embedded_auto
from subtitles import ai_source_candidates, download

ADDON = get_addon()
PROFILE = Path(xbmcvfs.translatePath(ADDON.getAddonInfo("profile")))
SESSION_WINDOW_ID = 10000
STARTUP_LAUNCHED = "stremioforkodi.startup.launched"
APP_RUNNING = "stremioforkodi.running"
DELAYS = (0, 1, 2, 3, 5)


def configured_delay():
    try:
        index = int(ADDON.getSetting("startup_delay") or "0")
    except (TypeError, ValueError):
        index = 0
    return DELAYS[index] if 0 <= index < len(DELAYS) else 0
def _notify(message, milliseconds=4000):
    xbmcgui.Dialog().notification("AI Subtitles", message, time=milliseconds)


class PlaybackWatcher(xbmc.Player):
    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor
        self._worker = None
        self._lock = threading.Lock()
        self._last_hash = None

    def onAVStarted(self):
        self.schedule()

    def schedule(self):
        try:
            settings = local_settings()
            if not self.isPlayingVideo() or not settings["enabled"] or settings["provider"] != "0":
                return
            if not settings["api_key"]:
                return
            current = self.getPlayingFile()
            digest = hashlib.sha256(current.encode()).hexdigest()
        except Exception:
            return
        with self._lock:
            if digest == self._last_hash:
                return
            if self._worker is not None and self._worker.is_alive():
                return
            self._last_hash = digest
            self._worker = threading.Thread(
                target=self._prepare, args=(current, digest), daemon=True
            )
            self._worker.start()

    def _matches(self, digest):
        try:
            return self.isPlayingVideo() and hashlib.sha256(
                self.getPlayingFile().encode()
            ).hexdigest() == digest
        except Exception:
            return False
    def _context(self, digest):
        context = Store(PROFILE / "playback").load()
        if context.get("url_hash") != digest:
            return None
        return context

    def _apply(self, path, digest, source, source_language, target_language):
        if not path or not self._matches(digest):
            return False
        self.setSubtitles(str(path))
        self.showSubtitles(True)
        source_name = CODE_NAMES.get(source_language, source_language or "Auto")
        target_name = CODE_NAMES.get(target_language, target_language)
        _notify("{} → {} ready ({})".format(source_name, target_name, source))
        return True

    def _prepare(self, current, digest):
        context = self._context(digest)
        if not context:
            return
        settings = local_settings()
        target = settings["target"]
        _notify("Auto: checking subtitles from the video first…", 3000)

        # Priority 1: embedded text subtitle from the exact video/stream.
        if settings.get("source") != "2":
            try:
                result = prepare_embedded_auto(current, PROFILE)
                if result and self._apply(
                    result["path"], digest, "video",
                    result["source_language"], result["target_language"]
                ):
                    return
            except Exception:
                pass

        if not self._matches(digest) or settings.get("source") == "1":
            return

        # Priority 2: best subtitle returned by the user's Stremio addons.
        try:
            providers = active_addons(Store(PROFILE).load())
            entries = ai_source_candidates(
                providers, context["kind"], context["id"],
                context.get("subtitles"), context.get("filename", "")
            )
        except Exception:
            entries = []
        for entry in entries[:3]:
            if not self._matches(digest):
                return
            try:
                path = download(entry, PROFILE / "subtitles")
                source_language = entry.get("lang")
                if self._apply(path, digest, "Stremio addon", source_language, target):
                    return
            except Exception:
                continue

        if self._matches(digest):
            _notify("No usable subtitle source found; keeping the original.", 4500)


def _maybe_launch_startup(monitor, session):
    if ADDON.getSetting("startup_autostart") != "true":
        return
    if session.getProperty(STARTUP_LAUNCHED) == "true":
        return
    session.setProperty(STARTUP_LAUNCHED, "true")
    delay = configured_delay()
    if delay and monitor.waitForAbort(delay):
        return
    if not monitor.abortRequested() and session.getProperty(APP_RUNNING) != "true":
        xbmc.executebuiltin("RunScript(script.stremioelec,startup)")


def main():
    monitor = xbmc.Monitor()

    # Keep the historical startup-launch behavior, but the service itself now
    # remains alive even when autostart is disabled so AI subtitles can watch playback.
    if ADDON.getSetting("startup_autostart") == "true":
        session = xbmcgui.Window(SESSION_WINDOW_ID)
        if session.getProperty(STARTUP_LAUNCHED) != "true":
            session.setProperty(STARTUP_LAUNCHED, "true")
            delay = configured_delay()
            if delay and monitor.waitForAbort(delay):
                return
            if not monitor.abortRequested() and session.getProperty(APP_RUNNING) != "true":
                xbmc.executebuiltin("RunScript(script.stremioelec,startup)")

    # Unit tests execute main() in isolation without the runtime watcher class.
    if "PlaybackWatcher" not in globals():
        return
    watcher = PlaybackWatcher(monitor)
    watcher.schedule()
    while not monitor.waitForAbort(1):
        pass


if __name__ == "__main__":
    main()
