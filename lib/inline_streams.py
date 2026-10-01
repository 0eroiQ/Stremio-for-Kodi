"""Addon-owned hero stream panel; Back restores the original cards and focus."""
import threading
import xbmcgui
from lib import backend as api
from lib.stream_presenter import presentation, target_label, playback_meta

LIST, CLOSE, RETRY = 7100, 7101, 7103
BACK = (10, 92, 216, 247)


class InlineStreams:
    def init_streams(self):
        self._streams_lock = threading.RLock()
        self._streams_worker = None
        self._streams_request = None
        self._streams_generation = 0
        self._streams_dead = False
        self._streams_open = False
        self._streams_rows = []
        self._streams_visible = []
        self._streams_positions = {}
        self._streams_launching = False
        self._streams_prefetch_identity = None

    def prefetch_streams(self, identity):
        """Media Info trigger: show cached data later, refresh this title once in background."""
        if not identity or self._streams_dead or self._streams_prefetch_identity == identity:return
        self._streams_prefetch_identity=identity
        cached_state=api.stream_cache_state(self.meta,identity)
        cached=api.cached_source_rows(self.meta,identity) if cached_state else None
        if cached and cached[0]:self.section_cache['streams:'+identity]=cached
        # Fresh cache needs no provider fan-out. Stale/missing cache refreshes once
        # in the background while the user can already open the cached rows.
        if cached_state and not cached_state[4]:return
        def refresh():
            try:
                result=api.source_rows(self.meta,identity)
                if not self._streams_dead and result and result[0]:self.section_cache['streams:'+identity]=result
            except Exception:pass
        try:threading.Thread(target=refresh,daemon=True).start()
        except RuntimeError:pass

    def choose_source(self, identity, resume_ms=0):
        if self._streams_dead or self._streams_open:
            return
        self.cancel_trailer()
        self._streams_previous_preview = self.preview_suspended
        self.preview_suspended = True
        self._streams_origin = self.getFocusId()
        self._streams_card_position = self.getControl(self.active_list).getSelectedPosition()
        self._streams_identity, self._streams_resume = identity, resume_ms
        self._streams_rows, self._streams_visible = [], []
        self._streams_open = True
        self.clearProperty('menu')
        self.menu_mode = None
        self.setProperty('streams_target', target_label(self.meta, identity))
        self.setProperty('streams_open', 'true')
        self._queue_streams()

    def _queue_streams(self, refresh=False):
        with self._streams_lock:
            self._streams_generation += 1
            generation, identity = self._streams_generation, self._streams_identity
            self.clearProperty('streams_ready')
            self.setProperty('streams_loading', 'true')
            self.setProperty('streams_message', 'Finding available sources…')
            self.setProperty('streams_count', '')
            self.setFocusId(CLOSE)
            if not refresh and 'streams:' + identity in self.section_cache:
                self._show_stream_result(generation, self.section_cache['streams:' + identity])
                return
            self._streams_request = (generation, identity)
            if self._streams_worker is not None:
                return
            try:
                self._streams_worker = threading.Thread(target=self._load_streams, daemon=True)
                self._streams_worker.start()
            except RuntimeError:
                self._streams_worker = None
                self._streams_request = None
                self._show_stream_result(generation, None)

    def _load_streams(self):
        while True:
            with self._streams_lock:
                job, self._streams_request = self._streams_request, None
                if self._streams_dead or job is None:
                    self._streams_worker = None
                    return
            generation, identity = job
            try:
                result = api.source_rows(self.meta, identity)
                if not isinstance(result, (tuple, list)) or len(result) != 3:
                    result = None
            except Exception:
                result = None  # Never log provider URLs or raw exceptions.
            with self._streams_lock:
                if not self._streams_dead and result is not None and result[0]:
                    self.section_cache['streams:' + identity] = result
                if not self._streams_dead and self._streams_open and generation == self._streams_generation:
                    try:
                        self._show_stream_result(generation, result)
                    except (RuntimeError, ValueError, TypeError):
                        self.clearProperty('streams_loading')
                        self.setProperty('streams_message', 'Could not show sources. Select Refresh to retry.')

    def _show_stream_result(self, generation, result):
        if self._streams_dead or not self._streams_open or generation != self._streams_generation:
            return
        self.clearProperty('streams_loading')
        self._streams_rows = [row for row in (result[0] if result else []) if isinstance(row, dict)]
        if not self._streams_rows:
            self.clearProperty('streams_ready')
            message = 'Unable to load sources. Select Refresh to try again.' if result is None else (
                'No supported sources. {} unsupported · {} providers unavailable.'.format(result[1], result[2]))
            self.setProperty('streams_message', message)
            self.setFocusId(RETRY)
            return
        self._render_streams(restore=True)
        self.setFocusId(LIST)

    def _render_streams(self, restore=False):
        self._streams_visible = list(self._streams_rows)
        control = self.getControl(LIST)
        control.reset()
        for row in self._streams_visible:
            view = presentation(row)
            entry = xbmcgui.ListItem(view['title'])
            entry.setProperty('stream_detail', view['detail'])
            control.addItem(entry)
        key = self._streams_identity
        pos = self._streams_positions.get(key, 0) if restore else 0
        control.selectItem(max(0, min(pos, len(self._streams_visible) - 1)))
        self.setProperty('streams_count', '{} sources'.format(len(self._streams_visible)))
        self.setProperty('streams_ready', 'true' if self._streams_visible else '')
        self.setProperty('streams_message', '' if self._streams_visible else 'No playable sources were returned.')

    def _remember_stream_position(self):
        if self._streams_visible:
            self._streams_positions[self._streams_identity] = self.getControl(LIST).getSelectedPosition()

    def close_streams(self):
        with self._streams_lock:
            if not self._streams_open:
                return
            self._remember_stream_position()
            self._streams_generation += 1
            self._streams_request = None
            self._streams_open = False
            self.clearProperty('streams_open')
            self.clearProperty('streams_loading')
            self.preview_suspended = self._streams_previous_preview
            listing = self.getControl(self.active_list)
            if listing.getSelectedPosition() != self._streams_card_position:
                listing.selectItem(max(0, self._streams_card_position))
            # Queue focus after Kodi evaluates the restored cards' visibility.
            import xbmc
            xbmc.executebuiltin('SetFocus({})'.format(self._streams_origin))

    def streams_focus(self, cid):
        if self._streams_open and cid not in (LIST, CLOSE, RETRY):
            self.setFocusId(LIST if self.getProperty('streams_ready') else CLOSE)

    def streams_action(self, action):
        if not self._streams_open:
            return False
        if action.getId() in BACK:
            self.close_streams()
        return True  # Do not dispatch panel actions to the hidden episode UI.

    def streams_click(self, cid):
        if not self._streams_open:
            return False
        if cid == CLOSE:
            self.close_streams()
        elif cid == RETRY and not self.getProperty('streams_loading'):
            self._queue_streams(refresh=True)
        elif cid == LIST:
            self._play_selected_stream()
        return True

    def _play_selected_stream(self):
        if self._streams_launching or not self.getProperty('streams_ready'):
            return
        index = self.getControl(LIST).getSelectedPosition()
        if not 0 <= index < len(self._streams_visible):
            return
        self._streams_launching = True
        try:
            meta = playback_meta(self.meta, self._streams_identity)
            api.play(meta, self._streams_identity, self._streams_visible[index], self._streams_resume)
            self.close_streams()
        except Exception:
            self.setProperty('streams_message', 'Playback could not start. Select another source or Refresh.')
        finally:
            self._streams_launching = False

    def stop_streams(self):
        with self._streams_lock:
            self._streams_dead = True
            self._streams_open = False
            self._streams_generation += 1
            self._streams_request = None
