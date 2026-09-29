"""Kodi playback observer for Stremio watch-progress write-back."""
import time
import xbmc

from account import Store
from core.playback_progress import playback_context, sync_progress

KEY_PROPERTY = 'StremioPlaybackKey'


def _account_store():
    from lib import backend as api
    return api.STORE


class ProgressPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self._context = None
        self._key = None
        self._position_ms = 0
        self._duration_ms = 0
        self._last_position_ms = None
        self._last_clock = None
        self._watched_ms = 0
        self._counting = True
        self._resume_target_ms = 0
        self._resume_attempts = 0
        self._pending = []

    def _stream_for_key(self, key):
        if not key:
            return None
        cache = Store(_account_store().directory / 'streams').load()
        row = (cache.get('urls') or {}).get(key)
        return row if isinstance(row, dict) else None

    def _current_key(self):
        try:
            item = self.getPlayingItem()
            value = item.getProperty(KEY_PROPERTY)
            if value:
                return value
        except Exception:
            pass
        try:
            pending = Store(_account_store().directory / 'playback-context').load()
            if time.time() - float(pending.get('created') or 0) <= 120:
                return pending.get('key')
        except Exception:
            pass
        return None
    def _sample(self, force=False):
        if self._context is None:
            return
        try:
            if not force and not self.isPlayingVideo():
                return
            position = max(0, int(float(self.getTime()) * 1000))
            duration = max(0, int(float(self.getTotalTime()) * 1000))
        except Exception:
            return
        now = time.monotonic()
        if self._last_position_ms is not None and self._last_clock is not None and self._counting:
            delta = position - self._last_position_ms
            wall_ms = max(0, int((now - self._last_clock) * 1000))
            # Count ordinary playback, never seek jumps or fast-forward as watched time.
            if 0 <= delta <= max(5000, wall_ms * 2 + 1500):
                self._watched_ms += delta
        self._position_ms = position
        if duration:
            self._duration_ms = duration
        self._last_position_ms = position
        self._last_clock = now

    def _start_session(self):
        if not self.isPlayingVideo():
            return
        key = self._current_key()
        stream = self._stream_for_key(key)
        if stream is None:
            return
        meta = stream.get('meta') if isinstance(stream.get('meta'), dict) else {}
        context = playback_context(meta, stream.get('kind'), stream.get('id'))
        if not context.get('meta_id') or not context.get('video_id'):
            return
        self._key, self._context = key, context
        self._watched_ms = 0
        self._last_position_ms = None
        self._last_clock = None
        self._counting = True
        try:
            from continue_playback import resume_seconds
            self._resume_target_ms = int(resume_seconds(stream.get('resume_ms')) * 1000)
        except Exception:
            self._resume_target_ms = 0
        self._resume_attempts = 0
        self._sample()
    def _finish(self, ended=False):
        if self._context is None:
            return
        self._sample(force=True)
        self._pending.append({
            'context': self._context,
            'position_ms': self._position_ms,
            'duration_ms': self._duration_ms,
            'watched_ms': self._watched_ms,
            'ended': bool(ended),
        })
        self._context = None
        self._key = None
        self._last_position_ms = None
        self._last_clock = None
        self._watched_ms = 0
        self._resume_target_ms = 0
        self._resume_attempts = 0

    def _apply_resume(self):
        target = self._resume_target_ms
        if not target or self._context is None:
            return
        # Kodi normally honors StartOffset. Some direct/plugin playback paths do
        # not, so seek once after AV start only when the player is still near 0.
        if self._position_ms >= max(1000, target - 3000):
            self._resume_target_ms = 0
            return
        if self._duration_ms and target >= self._duration_ms:
            self._resume_target_ms = 0
            return
        if self._resume_attempts >= 5:
            self._resume_target_ms = 0
            return
        self._resume_attempts += 1
        try:
            self.seekTime(target / 1000.0)
            self._position_ms = target
            self._last_position_ms = target
            self._last_clock = time.monotonic()
            self._resume_target_ms = 0
        except Exception:
            pass

    def tick(self):
        if self._context is None:
            try:
                if self.isPlayingVideo():
                    self._start_session()
            except Exception:
                return
        else:
            self._sample()
            self._apply_resume()

    def pop_pending(self):
        if not self._pending:
            return None
        return self._pending.pop(0)

    def onAVStarted(self):
        self._start_session()

    def onPlayBackStopped(self):
        self._finish(False)

    def onPlayBackEnded(self):
        self._finish(True)

    def onPlayBackError(self):
        self._finish(False)
    def onPlayBackPaused(self):
        self._sample()
        self._counting = False

    def onPlayBackResumed(self):
        self._counting = True
        try:
            self._last_position_ms = max(0, int(float(self.getTime()) * 1000))
            self._last_clock = time.monotonic()
        except Exception:
            self._last_position_ms = None
            self._last_clock = None

    def onPlayBackSeek(self, time_ms, seek_offset):
        del seek_offset
        self._last_position_ms = max(0, int(time_ms or 0))
        self._last_clock = time.monotonic()

    def onPlayBackSpeedChanged(self, speed):
        self._sample()
        self._counting = int(speed) == 1
        self._last_clock = time.monotonic()


def flush_pending(player):
    pending = player.pop_pending()
    if pending is None:
        return False
    try:
        sync_progress(
            _account_store(), pending['context'], pending['position_ms'],
            pending['duration_ms'], pending['watched_ms'],
            ended=pending['ended'])
    except Exception:
        # Playback must never fail because account progress could not be synced.
        return False
    return True
