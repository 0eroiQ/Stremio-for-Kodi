"""Persistent service: startup shell, watch-progress sync and AUTO AI subtitles."""
import hashlib
import sys
import threading
import time
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
from ai_subtitles import CODE_NAMES, local_settings, prepare_embedded_auto, _apply_remote_style
from subtitles import ai_source_candidates, download
from lib.playback_observer import ProgressPlayer, flush_pending
from lib.ui_dialogs import dialog as themed_dialog, progress_bg

ADDON = get_addon()
PROFILE = Path(xbmcvfs.translatePath(ADDON.getAddonInfo("profile")))
SESSION_WINDOW_ID = 10000
STARTUP_LAUNCHED = "stremioforkodi.startup.launched"
APP_RUNNING = "stremioforkodi.running"
PROGRESS_READY = "stremioforkodi.progress.ready"
DELAYS = (0, 1, 2, 3, 5)


def configured_delay():
    try:
        index = int(ADDON.getSetting("startup_delay") or "0")
    except (TypeError, ValueError):
        index = 0
    return DELAYS[index] if 0 <= index < len(DELAYS) else 0


def _notify(message, milliseconds=4000):
    themed_dialog().notification("AI Subtitles", message, time=milliseconds)


def _remember_ai_error(context, error):
    """Capture a sanitized diagnostic without interrupting playback."""
    try:
        from lib.error_report import build_payload
        from lib.last_error import remember_error
        remember_error(build_payload(context, error))
    except Exception:
        pass


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
        target_name = CODE_NAMES.get(target, target)
        progress = progress_bg()

        def update(percent, message):
            if self._matches(digest):
                progress.update(percent, message)

        progress.create("AI Subtitles", "Checking subtitles from the video…")
        progress.update(2, "Checking subtitles from the video…")
        embedded_error = None
        last_fallback_error = None
        try:
            # Fastest path: MKGA resolves the user's own Stremio subtitle addons
            # server-side, translates/caches there, and returns a ready SRT.
            try:
                from lib.signin import account_store
                from lib.vortexo_premium import resolve_subtitle_cloud
                cloud = resolve_subtitle_cloud(account_store(), context["kind"], context["id"], context.get("filename", ""), target)
                if cloud and self._matches(digest):
                    import hashlib as _hashlib
                    path = PROFILE / "subtitles" / ("mkga-cloud-" + _hashlib.sha256(cloud["subtitle"].encode("utf-8")).hexdigest() + ".srt")
                    from setup_profile import atomic_write
                    atomic_write(path, cloud["subtitle"].encode("utf-8"))
                    if self._apply(str(path), digest, "MKGA Cloud", cloud["source_language"], cloud["target_language"]):
                        return
            except Exception as error:
                _remember_ai_error("MKGA subtitle cloud resolver", error)

            # Noiro-style local fallback: ask subtitle addons first. Remote 4K MKV
            # embedded extraction can require reading/seeking the whole stream on
            # LibreELEC, so it must never block a ready text subtitle.
            if settings.get("source") != "1":
                progress.update(8, "Checking Stremio subtitle addons…")
                try:
                    providers = active_addons(Store(PROFILE).load())
                    entries = ai_source_candidates(
                        providers, context["kind"], context["id"],
                        context.get("subtitles"), context.get("filename", "")
                    )
                except Exception as error:
                    _remember_ai_error("AI subtitles Stremio fallback", error)
                    entries = []

                for entry in entries[:3]:
                    if not self._matches(digest):
                        return
                    try:
                        source_language = entry.get("lang")
                        source_name = CODE_NAMES.get(source_language, source_language or "Auto")
                        progress.update(15, "Using {} subtitle from Stremio addon…".format(source_name))
                        def fallback_progress(percent, message):
                            update(18 + int(percent * 0.78), message)
                        path = download(entry, PROFILE / "subtitles", progress_callback=fallback_progress)
                        if self._apply(path, digest, "Stremio addon", source_language, target):
                            return
                    except Exception as error:
                        last_fallback_error = error
                        _remember_ai_error("AI subtitles Stremio translation", error)

            if not self._matches(digest) or settings.get("source") == "2":
                return

            # Embedded is fallback, not the fast path. This preserves support for
            # files with no subtitle addon result without making every playback
            # wait on FFmpeg extraction first.
            progress.update(25, "Checking subtitles embedded in the video…")
            try:
                result = prepare_embedded_auto(current, PROFILE, progress_callback=update)
                if result and self._apply(result["path"], digest, "video", result["source_language"], result["target_language"]):
                    return
            except Exception as error:
                embedded_error = error
                _remember_ai_error("AI subtitles embedded source", error)
                if settings.get("source") == "1":
                    _notify("Video subtitle extraction failed. See Support → Report last error.", 5000)

            if self._matches(digest):
                if not entries and embedded_error is None:
                    from ai_subtitles import AITranslationError
                    _remember_ai_error(
                        "AI subtitles source selection",
                        AITranslationError(
                            "No usable embedded or Stremio subtitle source was available."
                        )
                    )
                elif last_fallback_error is not None:
                    _remember_ai_error(
                        "AI subtitles fallback exhausted", last_fallback_error
                    )
                _notify(
                    "No usable subtitle source found; keeping the original. "
                    "Report last error is available.", 5500
                )
        finally:
            progress.close()


class SubtitleSettingsSync:
    INTERVAL_SECONDS = 30

    def __init__(self):
        self._next_check = 0
        self._last_updated = None

    def tick(self):
        now = time.monotonic()
        if now < self._next_check:
            return
        self._next_check = now + self.INTERVAL_SECONDS
        try:
            from lib.signin import account_store
            from lib.vortexo_premium import hub_state
            hub = hub_state(account_store(), refresh_remote=True, max_age=0)
            remote = hub.get("settings") if isinstance(hub, dict) and hub.get("linked") else None
            if not isinstance(remote, dict):
                return
            updated = int(remote.get("updatedAt") or 0)
            if self._last_updated == updated:
                return
            self._last_updated = updated
            _apply_remote_style({
                "remote": True,
                "subtitle_size": str(remote.get("subtitleSize") or "medium"),
                "subtitle_position": str(remote.get("subtitlePosition") or "bottom"),
                "subtitle_color": str(remote.get("subtitleColor") or "white"),
            })
        except Exception:
            return



class ContinueIndexSync:
    INTERVAL = 900
    def __init__(self):
        self._next = 0
        self._worker = None
        self._lock = threading.Lock()
    def tick(self):
        now = time.time()
        if now < self._next:
            return
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._next = now + self.INTERVAL
            try:
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()
            except RuntimeError:
                self._worker = None
    def _run(self):
        try:
            state = Store(PROFILE).load()
            token = state.get("token")
            if not token:
                return
            from account import pull_library
            from lib import continue_index
            state["library"] = pull_library(token)
            Store(PROFILE).save(state)
            continue_index.seed(PROFILE, state["library"])
            # Never compete with active video playback for provider/network bandwidth.
            if xbmc.Player().isPlayingVideo():
                return
            from lib.stream_index import get as stream_get, put as stream_put, provider_signature, prune
            active = list(active_addons(state))
            signature = provider_signature(active)
            prune(PROFILE)
            refreshed = 0
            for kind, identity, item in continue_index.prefetch_rows(PROFILE, 6):
                cached = stream_get(PROFILE, kind, identity, signature)
                if cached and not cached[4]:
                    continue
                try:
                    from sources import collect
                    result = collect(active, kind, identity)
                    if result and result[0]:
                        stream_put(PROFILE, kind, identity, result, signature)
                except Exception:
                    pass
                refreshed += 1
                if refreshed >= 2:
                    break
        except Exception:
            return


def maybe_autostart(monitor):
    if ADDON.getSetting("startup_autostart") != "true":
        return
    session = xbmcgui.Window(SESSION_WINDOW_ID)
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

    # Unit tests may execute main() with only the historical startup symbols.
    if "PlaybackWatcher" not in globals() or "ProgressPlayer" not in globals():
        maybe_autostart(monitor)
        return

    player = ProgressPlayer()
    watcher = PlaybackWatcher(monitor)
    subtitle_sync = SubtitleSettingsSync()
    continue_sync = ContinueIndexSync()
    session = xbmcgui.Window(SESSION_WINDOW_ID)
    session.setProperty(PROGRESS_READY, "true")
    try:
        maybe_autostart(monitor)
        # Service updates can restart while a video is already playing.
        watcher.schedule()
        subtitle_sync.tick()
        continue_sync.tick()
        while not monitor.waitForAbort(1):
            subtitle_sync.tick()
            continue_sync.tick()
            player.tick()
            while flush_pending(player):
                pass
        while flush_pending(player):
            pass
    finally:
        session.clearProperty(PROGRESS_READY)


if __name__ == "__main__":
    main()
