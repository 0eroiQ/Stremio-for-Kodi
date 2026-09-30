"""Embedded Nimbus program windows. All navigation stays inside this addon."""
from lib.ui_dialogs import progress_bg as themed_progress_bg, dialog as themed_dialog
import re
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcgui

from lib import backend as api
from lib import mdblist
from lib.trailer_options import imdb_id, autoplay_delay, autoplay_enabled
from lib.sidebar_nav import menu_items, menu_action, home_index

ADDON = get_addon()
PATH = ADDON.getAddonInfo('path')
BACK = (10, 92, 216, 247)


from lib.theme import window as themed_window


def clean(value):
    return re.sub(r'<[^>]+>', '', str(value or ''))


_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def episode_runtime(value):
    """Return compact TV-card runtime text without inventing missing metadata."""
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > 10000:
            minutes = int(round(value / 60000.0))
        elif value > 300:
            minutes = int(round(value / 60.0))
        else:
            minutes = int(round(value))
    else:
        text = str(value).strip()
        iso = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?', text, re.I)
        if iso:
            minutes = int(iso.group(1) or 0) * 60 + int(iso.group(2) or 0)
        else:
            hm = re.fullmatch(r'(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?', text, re.I)
            if hm and (hm.group(1) or hm.group(2)):
                minutes = int(hm.group(1) or 0) * 60 + int(hm.group(2) or 0)
            else:
                plain = re.fullmatch(r'(\d+)\s*(?:m|min|mins|minutes)?', text, re.I)
                if not plain:
                    return text[:16]
                minutes = int(plain.group(1))
    if minutes <= 0:
        return ''
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return '{}h {}m'.format(hours, mins)
    if hours:
        return '{}h'.format(hours)
    return '{}m'.format(mins)


def episode_rating(row):
    """Use only provider-supplied episode rating metadata."""
    value = row.get('imdbRating')
    if value in (None, ''):
        value = row.get('rating')
    if value in (None, ''):
        return ''
    match = re.search(r'\d+(?:\.\d+)?', str(value))
    if not match:
        return ''
    try:
        rating = float(match.group(0))
    except ValueError:
        return ''
    if not 0 < rating <= 10:
        return ''
    return '{:.1f}'.format(rating)


def episode_date(row):
    """Format provider release dates like '20 Dec 2019'."""
    value = str(row.get('released') or row.get('releaseInfo') or '').strip()
    match = re.match(r'^(\d{4})-(\d{2})-(\d{2})(?:T|$)', value)
    if not match:
        return value[:16] if re.fullmatch(r'\d{4}', value) else ''
    year, month, day = map(int, match.groups())
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return ''
    return '{} {} {}'.format(day, _MONTHS[month - 1], year)


def item(row):
    li = xbmcgui.ListItem(clean(row.get('name') or row.get('title') or ''))
    li.setArt({'poster': row.get('poster', ''), 'thumb': row.get('thumbnail') or row.get('poster', ''),
               'fanart': row.get('background') or row.get('poster', '')})
    li.setProperty('id', str(row.get('id', '')))
    li.setProperty('type', str(row.get('type', 'movie')))
    li.setProperty('plot', clean(row.get('description')))
    state = row.get('state') if isinstance(row.get('state'), dict) else {}
    try:
        offset = max(0.0, float(state.get('timeOffset') or 0) / 1000.0)
        duration = max(0.0, float(state.get('duration') or 0) / 1000.0)
    except (TypeError, ValueError):
        offset, duration = 0.0, 0.0
    if duration > 0 and offset >= 1 and offset < duration:
        progress = max(1, min(99, int(round(offset * 100.0 / duration))))
        li.setProperty('WatchedProgress', str(progress))
        try:
            li.getVideoInfoTag().setResumePoint(offset, duration)
        except Exception:
            pass
    else:
        li.setProperty('WatchedProgress', '0')
    return li


class NimbusWindow(xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailer_timer = None
        self.preview_generation = 0
        self.preview_url = None
        self.preview_lock = threading.Lock()
        self.preview_suspended = False

    def play_hero_trailer(self, window_id, meta=None, generation=None, deadline=0):
        from lib.trailer_options import resolve
        generation = self.preview_generation if generation is None else generation
        meta = meta or self.meta
        try:
            if generation != self.preview_generation:
                return
            stream = resolve(imdb_id(meta),
                             getattr(self, 'season', -1) if meta.get('type') == 'series' else -1,
                             ADDON.getSetting('trailers_quality'))
            # Resolve during the selected delay, not after it. Navigation cancels
            # the pending preview without waiting for the network request.
            while time.monotonic() < deadline:
                if generation != self.preview_generation:
                    return
                xbmc.sleep(50)
            with self.preview_lock:
                if (self.preview_suspended or not stream or generation != self.preview_generation or
                        xbmcgui.getCurrentWindowId() != window_id or xbmc.Player().isPlaying()):
                    return
                entry = xbmcgui.ListItem(label=stream['title'], path=stream['url'])
                entry.setMimeType(stream['mime'])
                entry.setContentLookup(False)
                entry.setProperty('StartOffset', '0')
                entry.setProperty('script.trakt.exclude', '1')
                self.getControl(9102).setPosition(0, 0)
                self.getControl(9101).setHeight(731)
                self.preview_url = stream['url']
                self.setProperty('hero_trailer', 'true')
                xbmc.Player().play(stream['url'], entry, windowed=True)
            # Kodi centers wide video within its native video rectangle. Move
            # that rectangle up by the letterbox inset, leaving fullscreen alone.
            for _ in range(80):
                if generation != self.preview_generation:
                    return
                if xbmc.Player().isPlayingVideo():
                    result = json.loads(xbmc.executeJSONRPC(json.dumps({
                        'jsonrpc': '2.0', 'id': 1, 'method': 'Player.GetProperties',
                        'params': {'playerid': 1, 'properties': ['currentvideostream']}})))
                    aspect = float(((result.get('result') or {}).get('currentvideostream') or {}).get('aspect') or 0)
                    if aspect > 0:
                        height = min(731, round(1300 / aspect))
                        with self.preview_lock:
                            if generation != self.preview_generation:
                                return
                            self.getControl(9102).setPosition(0, -round((731 - height) / 2))
                            self.getControl(9101).setHeight(height)
                        return
                xbmc.sleep(100)
        except Exception:
            # An unavailable preview must leave the static hero usable.
            pass

    def cancel_trailer(self):
        if self.trailer_timer:
            self.trailer_timer.cancel()
            self.trailer_timer = None
        with self.preview_lock:
            self.preview_generation += 1
            self.clearProperty('hero_trailer')
            if self.preview_url:
                player = xbmc.Player()
                try:
                    # play() is asynchronous: also stop a queued preview before
                    # clearing its ownership, even if isPlaying() is still false.
                    player.stop()
                except RuntimeError:
                    pass
                self.preview_url = None

    def report(self, text):
        self.setProperty('status', text)

    def busy(self, label, fn):
        progress = themed_progress_bg()
        progress.create('Stremio for Kodi', label)
        try:
            return fn()
        except Exception:
            # Provider exception strings can contain credentials.
            xbmc.log('Stremio for Kodi Nimbus: request failed (' + label + ')', xbmc.LOGWARNING)
            self.report('Unable to load this section. Please try again.')
            return None
        finally:
            progress.close()

    def set_hero(self, row):
        row = dict(row)
        if mdblist.enabled() and ADDON.getSetting('rating_imdb') != 'true' and not row.get('rating_text'):
            row.pop('imdbRating', None)
        for setting, fields in {
            'ui_show_logo': ('logo',), 'ui_show_plot': ('description',),
            'ui_show_genres': ('genres',), 'ui_show_rating': ('rating_text', 'imdbRating'),
            'ui_show_runtime': ('runtime',),
        }.items():
            if ADDON.getSetting(setting) == 'false':
                for field in fields:
                    row.pop(field, None)
        values = {'title': clean(row.get('name')), 'plot': clean(row.get('description')),
                  'fanart': (row.get('background') or '') if row.get('background') != row.get('poster') else '',
                  'logo': row.get('logo') or '',
                  'genres': ' · '.join(row.get('genres') or []),
                  'facts': '  ·  '.join(str(v) for v in (
                      row.get('releaseInfo') or row.get('year'),
                      row.get('runtime'), {'series':'Series', 'movie':'Movie'}.get(row.get('type'), str(row.get('type') or '').title())) if v)}
        from lib.hero_tags import tags
        values.update(tags(row))
        ratings = row.get('rating_badges', [])
        if not ratings and row.get('imdbRating') and (not mdblist.enabled() or ADDON.getSetting('rating_imdb') == 'true'):
            ratings = [{'value': str(row['imdbRating']), 'icon': 'imdb.png'}]
        if ADDON.getSetting('ui_show_rating') == 'false':
            ratings = []
        for index in range(10):
            badge = ratings[index] if index < len(ratings) else {}
            self.setProperty('rating%d_value' % index, badge.get('value', ''))
            self.setProperty('rating%d_icon' % index, (PATH + '/resources/skins/Main/media/ratings/' + badge['icon']) if badge.get('icon') else '')
            self.setProperty('rating%d_label' % index, badge.get('label', ''))
        for key, value in values.items():
            self.setProperty(key, value)

    def details(self, row, auto_source=None, focus_video_id=None):
        from lib.launch_guard import mark_window, unmark_window
        self.preview_suspended = True
        self.cancel_trailer()
        window = None
        try:
            window = themed_window(InfoWindow, 'script-stremio-info.xml', PATH, 'Main', '1080i',
                                   meta=row, auto_source=auto_source,
                                   focus_video_id=focus_video_id)
            mark_window(window, 'info')
            window.doModal()
        finally:
            unmark_window(window)
            self.preview_suspended = False
            if hasattr(self, 'account_rows') and self.getProperty('page') == 'Home':
                try:
                    fresh = api.account_home(False)
                    if fresh != self.account_rows:
                        self.account_rows = fresh
                        self.load_home()
                except Exception:
                    pass


from lib.addons_page import AddonsPage


class HomeWindow(AddonsPage, NimbusWindow):
    def __init__(self, *args, **kwargs):
        self.account_rows = kwargs.pop('account_rows', [])
        self.row_count = kwargs.pop('row_count', 2)
        self.discover_skip = 0
        self.discover_page_size = 100
        self.discover_catalog = None
        self.discover_extras = {}
        self.library_kind = 'all'
        self.library_order = 'recent'
        self.library_entries = []
        self.hero_cache = {}
        self.hero_request = None
        self.hero_loading = False
        self.closed = False
        self.home_refreshing = False
        self.home_row_specs = {}
        self.home_row_loading = set()
        self.home_row_exhausted = set()
        super().__init__(*args, **kwargs)

    def onInit(self):
        from lib.perf_trace import now as perf_now, log as perf_log
        init_started = perf_now()
        if getattr(self, 'initialized', False):
            return
        self.initialized = True
        self.rows = {400+i: [] for i in range(self.row_count)}
        self.hero_key = None
        self.getControl(9000).addItems(menu_items(xbmcgui))
        self.getControl(9000).selectItem(home_index())
        self.load_home()
        perf_profile = None
        try:
            perf_profile = api.STORE.directory
        except (NameError, AttributeError):
            pass
        if isinstance(self.account_rows, (list, tuple)):
            perf_log('ui.home.initial', init_started, profile=perf_profile, rows=len(self.account_rows),
                     items=sum(len(row.get('items') or []) for row in self.account_rows
                               if isinstance(row, dict)))
        else:
            perf_log('ui.home.initial', init_started, profile=perf_profile)
        self.setFocusId(9000)
        self.refresh_home_async()
        from lib.weather_widget import request_refresh
        request_refresh()

    def load_home(self):
        self.populate_rows('Home', self.account_rows)

    def refresh_home_async(self):
        if self.home_refreshing or self.closed:
            return
        self.home_refreshing = True

        def refresh():
            from lib.perf_trace import now as perf_now, log as perf_log
            refresh_started = perf_now()
            try:
                fresh = api.account_home(True)
                if self.closed:
                    return
                self.account_rows = fresh
                # Never steal focus from another page or an open details window.
                if self.getProperty('page') != 'Home' or self.preview_suspended:
                    return
                focus = self.getFocusId()
                position = None
                if focus in self.rows:
                    position = self.getControl(focus).getSelectedPosition()
                populate_started = perf_now()
                self.populate_rows('Home', fresh)
                perf_log('ui.home.repopulate', populate_started, profile=api.STORE.directory, rows=len(fresh),
                         items=sum(len(row.get('items') or []) for row in fresh))
                perf_log('ui.home.background.total', refresh_started, profile=api.STORE.directory)
                if focus == 9000:
                    self.setFocusId(9000)
                elif focus in self.rows and self.rows[focus]:
                    self.getControl(focus).selectItem(
                        min(max(0, position or 0), len(self.rows[focus]) - 1))
                    self.setFocusId(focus)
            except Exception:
                # Cached/snapshot Home stays usable and the next launch retries.
                pass
            finally:
                self.home_refreshing = False

        threading.Thread(target=refresh, daemon=True).start()

    def populate(self, section, first, second=(), labels=('Movies', 'Series')):
        self.populate_rows(section, [{'label': labels[0], 'items': first},
                                     {'label': labels[1], 'items': second}])

    def populate_rows(self, section, catalogs):
        self.cancel_trailer()
        self.setProperty('page', section)
        self.setProperty('next_row', '')
        self.set_hero({})
        self.hero_key = None
        self.row_labels = {}
        for index, cid in enumerate(self.rows):
            catalog = catalogs[index] if index < len(catalogs) else {}
            rows = list(catalog.get('items', []))
            self.rows[cid] = rows
            self.row_labels[cid] = catalog.get('label', '')
            if section == 'Home':
                self.home_row_specs[cid] = {k:catalog.get(k) for k in ('url','kind','catalog_id','provider') if catalog.get(k) is not None}
            listing = self.getControl(cid)
            listing.reset()
            listing.addItems([item(row) for row in rows])
            self.setProperty('row'+str(cid), self.row_labels[cid])
            self.setProperty('has'+str(cid), 'true' if rows else '')
        available = [cid for cid, rows in self.rows.items() if rows]
        for index, cid in enumerate(available):
            up = available[index-1] if index else (9200 if section in ('Discover', 'Library') else 9000)
            down = available[index+1] if index+1 < len(available) else cid
            self.getControl(cid).setNavigation(self.getControl(up), self.getControl(down),
                                               self.getControl(9000), self.getControl(cid))
        self.setProperty('first_row', str(available[0] if available else 9000))
        failed = sum(bool(c.get('failed')) for c in catalogs)
        self.report(('Some account catalogs could not load. Reopen the addon to retry.' if failed else '')
                    if available else ('Your library has no saved titles for this filter.' if section == 'Library' else 'No titles available for this selection.'))
        selected = available[0] if available else 9000
        self.setFocusId(selected)
        self.update_hero()

    def maybe_load_more_home(self):
        if self.getProperty('page') != 'Home':return
        cid=self.getFocusId()
        if cid not in self.rows or cid in self.home_row_loading or cid in self.home_row_exhausted:return
        rows=self.rows[cid];spec=self.home_row_specs.get(cid) or {}
        if not rows or len(rows)<12 or len(rows)-self.getControl(cid).getSelectedPosition()>4:return
        if not all(spec.get(k) for k in ('url','kind','catalog_id')):return
        self.home_row_loading.add(cid);skip=len(rows)
        def work():
            try:
                from core.protocol import fetch,resource_url
                from lib.home_catalogs import load_more
                more=load_more(spec,fetch,resource_url,skip)
                if self.closed:return
                known={(r.get('type'),r.get('id')) for r in self.rows.get(cid,[])}
                fresh=[r for r in more if (r.get('type'),r.get('id')) not in known]
                if not fresh:self.home_row_exhausted.add(cid);return
                self.rows[cid].extend(fresh)
                self.getControl(cid).addItems([item(r) for r in fresh])
                if len(more)<16:self.home_row_exhausted.add(cid)
            except Exception:pass
            finally:self.home_row_loading.discard(cid)
        threading.Thread(target=work,daemon=True).start()

    def update_hero(self):
        if self.getProperty('page') == 'Addons':
            self.update_addon_selection()
            return
        if self.preview_suspended:
            return
        cid = self.getFocusId()
        if cid not in self.rows:
            self.cancel_trailer()
            self.hero_key = None
            return
        following = next((key for key in self.rows if key > cid and self.rows[key]), None)
        self.setProperty('next_row', self.row_labels.get(following, ''))
        pos = self.getControl(cid).getSelectedPosition()
        if 0 <= pos < len(self.rows[cid]):
            row = self.rows[cid][pos]
            key = (cid, pos, row['id'])
            if key != self.hero_key:
                self.cancel_trailer()
                self.hero_key = key
                cached = self.hero_cache.get((row.get('type'), row.get('id')))
                self.set_hero(cached or row)
                self.request_hero(key, row)
                if (self.getProperty('page') == 'Home' and imdb_id(row) and
                        ADDON.getSetting('trailers_enabled') != 'false' and
                        autoplay_enabled(ADDON.getSetting('trailers_auto'),
                                         ADDON.getSetting('trailers_auto_scope'), 'home')):
                    delay = autoplay_delay(ADDON.getSetting('trailers_delay'))
                    generation = self.preview_generation
                    window_id = xbmcgui.getCurrentWindowId()
                    self.trailer_timer = threading.Timer(0.25, self.play_hero_trailer,
                        args=(window_id, dict(row), generation, time.monotonic() + delay))
                    self.trailer_timer.daemon = True
                    self.trailer_timer.start()

    def request_hero(self, key, row):
        identity = (row.get('type'), row.get('id'))
        if identity in self.hero_cache:
            self.set_hero(self.hero_cache[identity])
            return
        from lib import mdblist
        if row.get('background') and row.get('background') != row.get('poster') and row.get('description') and not mdblist.enabled():
            return
        self.hero_request = (key, dict(row), self.getProperty('page'))
        if self.hero_loading:
            return
        self.hero_loading = True
        def enrich():
            try:
                while self.hero_request and not self.closed:
                    request = self.hero_request
                    self.hero_request = None
                    request_key, preview, page = request
                    try:
                        full = preview if preview.get('background') and preview.get('background') != preview.get('poster') and preview.get('description') else api.metadata(preview)
                        full = mdblist.enrich(full)
                        self.hero_cache[(preview.get('type'), preview.get('id'))] = full
                        if not self.closed and self.hero_key == request_key and self.getProperty('page') == page:
                            self.set_hero(full)
                    except Exception:
                        pass
            finally:
                self.hero_loading = False
        threading.Thread(target=enrich, daemon=True).start()

    def close(self):
        self.cancel_trailer()
        self.closed = True
        self.hero_request = None
        super().close()

    def load_discover(self):
        choices = api.discover_choices()
        if not choices:
            self.setProperty('filters', 'Discover · No account catalogs')
            self.populate_rows('Discover', [])
            self.setFocusId(9200)
            return
        if self.discover_catalog is None:
            self.discover_catalog = choices[0]
        catalog = self.discover_catalog
        values = dict(catalog['defaults']); values.update(self.discover_extras)
        if self.discover_skip:
            values['skip'] = str(self.discover_skip)
        self.setProperty('filter_label_0', catalog['kind'].title())
        self.setProperty('filter_label_1', catalog['label'])
        self.setProperty('filter_label_2', str(values.get('genre') or 'Genre'))
        summary = ' · '.join([catalog['kind'].title(), catalog['label']] + list(values.values()))
        self.setProperty('filters',  summary)
        rows = self.busy('Loading Discover', lambda: api.discover_items(catalog, values))
        if rows: self.discover_page_size = len(rows)
        self.populate_rows('Discover', [{'label': catalog['label'], 'items': rows or []}])
        if not rows:
            self.setFocusId(9200)

    def load_library(self):
        from lib.browse import library_sections, library_kinds
        if self.library_kind not in library_kinds(self.library_entries):
            self.library_kind = 'all'
        labels = {'recent':'Recently added', 'watched':'Last watched', 'name':'Name'}
        self.setProperty('filter_label_0', self.library_kind.title())
        self.setProperty('filter_label_1', labels[self.library_order])
        self.setProperty('filter_label_2', 'Refresh')
        self.setProperty('filters',  self.library_kind.title() + ' · ' + labels[self.library_order])
        self.populate_rows('Library', library_sections(self.library_entries, self.library_kind, self.library_order))
        if not any(self.rows.values()):
            self.setFocusId(9200)

    def edit_filters(self, direct=None):
        from lib.nimbus_select import Dialog
        dialog = Dialog(PATH, left=50 + (direct or 0)*290,
                        top=660 if self.getProperty('page') == 'Discover' else 600)
        if self.getProperty('page') == 'Discover':
            choices = api.discover_choices()
            if not choices:
                return
            current = self.discover_catalog or choices[0]
            extras = [e for e in current['extras'] if e.get('name') not in ('skip','search') and e.get('options')]
            paging = any(e.get('name') == 'skip' for e in current['extras'])
            options = ['Type', 'Catalog'] + [e['name'].title() for e in extras]
            option = direct if direct is not None else dialog.select('Discover', options + (['Next page', 'First page'] if paging else []))
            if option == 2 and direct is not None:
                genre = next((i for i,e in enumerate(extras) if e['name'] == 'genre'), None)
                if genre is None: return
                option = genre + 2
            if option < 0:
                return
            if paging and option >= len(options):
                self.discover_skip = self.discover_skip + self.discover_page_size if option == len(options) else 0
                self.load_discover()
                return
            self.discover_skip = 0
            if option == 0:
                types = list(dict.fromkeys(c['kind'] for c in choices))
                selected = dialog.select('Type', [t.title() for t in types])
                if selected < 0: return
                self.discover_catalog = next(c for c in choices if c['kind'] == types[selected])
                self.discover_extras = {}
            elif option == 1:
                matching = [c for c in choices if c['kind'] == current['kind']]
                selected = dialog.select('Catalog', [c['label'] + ' · ' + c['addon'] for c in matching])
                if selected < 0: return
                self.discover_catalog = matching[selected]
                self.discover_extras = {}
            else:
                extra = extras[option-2]
                required = extra['name'] in current['defaults']
                values = list(extra['options'])
                selected = dialog.select(extra['name'].title(), ([] if required else ['All']) + [str(v) for v in values])
                if selected < 0: return
                if not required and selected == 0:
                    self.discover_extras.pop(extra['name'], None)
                else:
                    self.discover_extras[extra['name']] = str(values[selected if required else selected-1])
            self.load_discover()
        elif self.getProperty('page') == 'Library':
            option = direct if direct is not None else dialog.select('Library', ['Type', 'Sort', 'Refresh from account'])
            if option == 0:
                from lib.browse import library_kinds
                kinds = library_kinds(self.library_entries)
                selected = dialog.select('Type', [t.title() for t in kinds])
                if selected < 0: return
                self.library_kind = kinds[selected]
            elif option == 1:
                selected = dialog.select('Sort', ['Recently added', 'Last watched', 'Name'])
                if selected < 0: return
                self.library_order = ['recent', 'watched', 'name'][selected]
            elif option == 2:
                rows = self.busy('Syncing your library', api.account_library)
                if rows is not None: self.library_entries = rows
            else:
                return
            self.load_library()

    def onFocus(self, control_id):
        if getattr(self, 'initialized', False):
            self.update_hero()
            if control_id == 9000:
                from lib.weather_widget import request_refresh
                request_refresh()

    def home_media_context_menu(self):
        cid = self.getFocusId()
        if (self.getProperty('page') != 'Home' or cid not in self.rows or
                self.row_labels.get(cid) != 'Continue Watching'):
            return False
        pos = self.getControl(cid).getSelectedPosition()
        if not 0 <= pos < len(self.rows[cid]):
            return False
        row = self.rows[cid][pos]
        saved = api.saved(row)
        state = saved.get('state') or {}
        target_id = str(state.get('video_id') or row.get('id') or '')
        from lib.media_action_menu import choose
        try:
            offset = max(0, int(float(state.get('timeOffset') or 0)))
            duration = max(0, int(float(state.get('duration') or 0)))
        except (TypeError, ValueError):
            offset, duration = 0, 0
        # A current partial rewatch is not treated as watched merely because an
        # older flaggedWatched value remains on the Stremio library item.
        partial = offset > 1 and (not duration or offset < duration * 0.90)
        watched = bool(state.get('flaggedWatched')) and not partial
        from context_options import continue_options
        selected = choose(PATH, continue_options(row.get('type'), watched))
        if selected is None:
            return True
        full = self.busy('Loading media', lambda: mdblist.enrich(api.metadata(row))) or row
        if selected == 'restart':
            identity = target_id if row.get('type') == 'series' else str(row.get('id') or '')
            self.details(full, auto_source=(identity, 0), focus_video_id=target_id)
        elif selected == 'episode':
            self.details(full, focus_video_id=target_id)
        elif selected in ('series', 'info'):
            self.details(full)
        elif selected == 'toggle-watched':
            if row.get('type') == 'series':
                from lib.episode_state import watched_ids
                is_watched = target_id in watched_ids(full.get('videos', []), api.saved(full))
                result = self.busy('Updating watched state',
                                   lambda: api.mark_episode(full, target_id, not is_watched))
            else:
                result = self.busy('Updating watched state',
                                   lambda: api.mark_movie(full, not watched))
            if result is not None:
                self.account_rows = api.account_home(False)
                self.load_home()
        elif selected == 'remove-continue':
            result = self.busy('Updating Continue Watching', lambda: api.remove_continue(full))
            if result is not None:
                self.account_rows = api.account_home(False)
                self.load_home()
        if cid in self.rows and self.rows[cid]:
            self.setFocusId(cid)
            self.getControl(cid).selectItem(min(pos, len(self.rows[cid]) - 1))
        return True

    def onAction(self, action):
        if isinstance(getattr(xbmcgui, '__name__', None), str):
            from lib.ui_dialogs import dialog as themed_dialog
        else:
            themed_dialog = xbmcgui.Dialog
        aid = action.getId()
        if aid in BACK:
            # Back from the main program window must always offer a real exit.
            # The previous two-press arm state made TV remotes appear trapped
            # because the first Back silently moved focus to the sidebar.
            self.exit_armed = False
            if themed_dialog().yesno(
                    'Exit Stremio for Kodi',
                    'Do you want to exit Stremio for Kodi?',
                    nolabel='Cancel', yeslabel='Exit'):
                self.close()
            return
        if aid in (1, 2, 3, 4, 7, 11, 100, 101):
            self.exit_armed = False
        if aid == 117 and self.home_media_context_menu():
            return
        if aid == 117 and self.getProperty('page') == 'Discover':
            self.edit_filters()
            return
        if aid == 11 and self.getFocusId() in self.rows:
            self.onClick(self.getFocusId())
        else:
            self.update_hero()
            self.maybe_load_more_home()

    def open_settings(self):
        from lib.settings_page import show as show_settings
        result = show_settings()
        from lib.playback_settings import apply
        apply()
        if result.get('request_page') == 'addons':
            self.load_addons()
        elif result.get('appearance_changed'):
            self.reload_appearance = True
            self.close()

    def onClick(self, cid):
        if isinstance(getattr(xbmcgui, '__name__', None), str):
            from lib.ui_dialogs import dialog as themed_dialog
        else:
            themed_dialog = xbmcgui.Dialog
        self.exit_armed = False
        if cid in (9300, 9301, 9302, 9303, 9304):
            self.addon_click(cid)
            return
        self.cancel_trailer()
        self.hero_key = None
        if cid in (9200, 9201, 9202):
            self.edit_filters(cid-9200)
            return
        if cid == 9000:
            pos = self.getControl(9000).getSelectedPosition()
            cid = menu_action(pos)
        if cid in self.rows:
            pos = self.getControl(cid).getSelectedPosition()
            if 0 <= pos < len(self.rows[cid]):
                self.details(self.rows[cid][pos])
                self.setFocusId(cid)
                self.getControl(cid).selectItem(pos)
            return
        if cid == 202:
            self.load_home()
        elif cid == 201:
            if ADDON.getSetting('search_native_keyboard') == 'true':
                keyboard = xbmc.Keyboard('', 'Search movies and series')
                keyboard.doModal()
                query = keyboard.getText().strip() if keyboard.isConfirmed() else ''
            else:
                query = themed_dialog().input('Search movies and series').strip()
            if query:
                result = self.busy('Searching', lambda: api.search(query, api.providers())) or []
                self.populate('Search: ' + query, [r for r in result if r.get('type') == 'movie'],
                              [r for r in result if r.get('type') == 'series'])
        elif cid == 203:
            self.load_discover()
        elif cid == 204:
            entries = self.busy('Syncing your library', api.account_library)
            self.library_entries = entries if entries is not None else api.account_library(False)
            self.load_library()
        elif cid == 205:
            self.load_addons()
        elif cid == 206:
            self.open_settings()


from lib.inline_streams import InlineStreams


class InfoWindow(InlineStreams, NimbusWindow):
    def __init__(self, *args, **kwargs):
        self.preview = kwargs.pop('meta')
        self.auto_source = kwargs.pop('auto_source', None)
        self.focus_video_id = kwargs.pop('focus_video_id', None)
        super().__init__(*args, **kwargs)
        self.initialized = False
        self.menu_mode = None
        self.section = ''
        self.section_cache = {}
        self.cards = []
        self.play_target = ''
        self.resume_ms = 0
        self.init_streams()

    def onInit(self):
        if self.initialized:
            return
        self.initialized = True
        self.meta = self.preview
        self.set_hero(self.meta)
        self.meta = self.busy('Loading details', lambda: mdblist.enrich(api.metadata(self.preview))) or self.preview
        self.set_hero(self.meta)
        series = self.meta.get('type') == 'series'
        self.setProperty('series', 'true' if series else '')
        self.available_seasons = api.seasons(self.meta)
        regular = [r for r in self.available_seasons if r['season'] > 0]
        self.season = (regular or self.available_seasons or [{'season': 1}])[0]['season']
        saved = api.saved(self.meta)
        from lib.episode_state import watched_ids
        self.watched_episodes = watched_ids(self.meta.get('videos', []), saved)
        if series:
            next_video, self.resume_ms = api.next_series_episode(self.meta.get('videos', []), self.meta['id'], saved)
            if next_video and next_video['id'] in self.watched_episodes:
                regular = [v for season in api.seasons(self.meta) if season['season'] > 0
                           for v in api.episodes(self.meta, season['season'])]
                next_video = next((v for v in regular if v['id'] not in self.watched_episodes), next_video)
                self.resume_ms = 0
            if next_video:
                self.play_target = next_video['id']
                self.season = int(next_video.get('season', self.season))
            if self.focus_video_id:
                focus_video = next((v for v in self.meta.get('videos', [])
                                    if str(v.get('id') or '') == str(self.focus_video_id)), None)
                if focus_video:
                    self.season = int(focus_video.get('season', self.season))
        else:
            self.play_target = self.meta['id']
            self.resume_ms = (saved.get('state') or {}).get('timeOffset') or 0
        self.setProperty('playlabel', 'Resume' if api.resume_seconds(self.resume_ms) else 'Play')
        self.prefetch_streams(self.play_target)
        self.setProperty('hastrailer', 'true' if ADDON.getSetting('trailers_enabled') != 'false' and imdb_id(self.meta) else '')
        self.refresh_library()
        self.select_section('Episodes' if series else 'Similar')
        if series and self.focus_video_id:
            pos = next((i for i, row in enumerate(self.cards)
                        if str(row.get('id') or '') == str(self.focus_video_id)), None)
            if pos is not None:
                self.getControl(501).selectItem(pos)
        self.setFocusId(501 if series and self.cards else 21001)
        if self.auto_source:
            identity, resume = self.auto_source
            self.choose_source(identity, resume_ms=resume)
            self.auto_source = None
            return
        if (autoplay_enabled(ADDON.getSetting('trailers_auto'),
                             ADDON.getSetting('trailers_auto_scope'), 'info')
                and self.getProperty('hastrailer')):
            window_id = xbmcgui.getCurrentWindowId()
            delay = autoplay_delay(ADDON.getSetting('trailers_delay'))
            generation = self.preview_generation
            deadline = time.monotonic() + delay
            def autoplay():
                if xbmcgui.getCurrentWindowId() == window_id and not xbmc.Player().isPlaying():
                    self.play_hero_trailer(window_id, generation=generation, deadline=deadline)
            self.trailer_timer = threading.Timer(0.25, autoplay)
            self.trailer_timer.daemon = True
            self.trailer_timer.start()

    def close(self):
        self.stop_streams()
        self.cancel_trailer()
        super().close()

    def play_trailer(self):
        self.cancel_trailer()
        if ADDON.getSetting('trailers_enabled') == 'false':
            return
        from lib.trailer_options import playback_url, imdb_id
        url = playback_url(imdb_id(self.meta), self.season if self.meta.get('type') == 'series' else -1)
        if url:
            self.report('')
            xbmc.executebuiltin('PlayMedia(' + url + ')')
        else:
            self.report('No direct trailer is available for this title.')

    def refresh_library(self):
        self.setProperty('librarylabel', 'In library' if api.in_library(self.meta) else 'Add to library')

    def select_section(self, section):
        self.section = section
        self.setProperty('section', section)
        self.setProperty('seasonlabel', 'Specials' if self.season == 0 else 'Season ' + str(self.season))
        self.clearProperty('menu')
        self.menu_mode = None
        self.report('')
        if section == 'Episodes':
            rows = api.episodes(self.meta, self.season)
        elif section in ('Cast', 'Crew'):
            rows = api.people(self.meta, section.lower())
        elif section == 'Languages':
            rows = api.languages(self.meta)
        else:
            if 'Similar' not in self.section_cache:
                self.section_cache['Similar'] = self.busy('Loading similar titles',
                    lambda: api.recommendations(self.meta, api.providers())) or []
            rows = self.section_cache['Similar']
        self.cards = rows
        self.active_list = 500 if section in ('Cast', 'Crew') else 502 if section == 'Languages' else 503 if section == 'Similar' else 501
        for cid in (500, 501, 502, 503):
            self.getControl(cid).reset()
        items = []
        episode_progress = {}
        if section == 'Episodes':
            saved = api.saved(self.meta)
            state = saved.get('state') if isinstance(saved, dict) else {}
            if isinstance(state, dict):
                active_id = str(state.get('video_id') or '')
                try:
                    offset = max(0.0, float(state.get('timeOffset') or 0) / 1000.0)
                    duration = max(0.0, float(state.get('duration') or 0) / 1000.0)
                except (TypeError, ValueError):
                    offset, duration = 0.0, 0.0
                if active_id and duration > 0 and offset >= 1 and offset < duration:
                    episode_progress[active_id] = (offset, duration)
        for row in rows:
            li = item(row)
            li.setProperty('initials', row.get('code') or ''.join(p[:1] for p in row.get('name', '').split()[:2]).upper())
            li.setProperty('job', row.get('job', ''))
            if section == 'Episodes':
                li.setProperty('watched', 'true' if row.get('id') in self.watched_episodes else '')
                number = row.get('episode') or row.get('number') or ''
                title = clean(row.get('name') or row.get('title') or 'Episode')
                season = row.get('season', self.season)
                if isinstance(season, int) and isinstance(number, int):
                    episode_code = 'S{:02d}E{:02d}'.format(season, number)
                else:
                    episode_code = 'Ep. {}'.format(number) if number != '' else 'Episode'
                li.setProperty('episode_code', episode_code)
                li.setProperty('episode_title', title)
                li.setProperty('episode_heading', '{} - {}'.format(episode_code, title))
                li.setProperty('episode_runtime', episode_runtime(
                    row.get('runtime') if row.get('runtime') not in (None, '') else row.get('duration')))
                li.setProperty('episode_imdb', episode_rating(row))
                li.setProperty('episode_date', episode_date(row))
                progress = episode_progress.get(str(row.get('id') or ''))
                if progress and row.get('id') not in self.watched_episodes:
                    offset, duration = progress
                    percent = max(1, min(99, int(round(offset * 100.0 / duration))))
                    li.setProperty('WatchedProgress', str(percent))
                    try:
                        li.getVideoInfoTag().setResumePoint(offset, duration)
                    except Exception:
                        pass
                else:
                    li.setProperty('WatchedProgress', '0')
                li.setLabel('{} - {}'.format(episode_code, title))
                li.setArt({'thumb': row.get('thumbnail') or self.meta.get('background', '')})
            elif section == 'Similar':
                li.setArt({'thumb': row.get('background') or row.get('poster', '')})
            items.append(li)
        self.getControl(self.active_list).addItems(items)
        if section == 'Episodes' and rows:
            target = next((i for i, row in enumerate(rows) if row.get('id') == self.play_target), None)
            if target is None:
                target = next((i for i, row in enumerate(rows) if row.get('id') not in self.watched_episodes), 0)
            self.getControl(self.active_list).selectItem(target)
        self.setProperty('hascards', 'true' if rows else '')
        if not rows:
            self.report('No {} provided for this title.'.format(section.lower()))

    def open_menu(self, mode):
        self.menu_mode = mode
        self.setProperty('menu_kind', mode)
        self.menu_entries = ([r['season'] for r in self.available_seasons] if mode == 'seasons' else
                             (['Episodes'] if self.meta['type'] == 'series' else []) + ['Cast', 'Crew', 'Languages', 'Similar'])
        if not self.menu_entries:
            self.report('No seasons provided for this series.')
            return
        listing = self.getControl(600)
        listing.reset()
        for value in self.menu_entries:
            label = ('Specials' if value == 0 else 'Season ' + str(value)) if mode == 'seasons' else value
            selected = value == (self.season if mode == 'seasons' else self.section)
            li = xbmcgui.ListItem(label)
            li.setProperty('selected', '✓' if selected else '')
            listing.addItem(li)
        self.setProperty('menu', 'true')
        self.setFocusId(600)
        current = self.season if mode == 'seasons' else self.section
        if current in self.menu_entries:
            listing.selectItem(self.menu_entries.index(current))

    def _refresh_episode_cards(self, pos):
        saved = api.saved(self.meta)
        from lib.episode_state import watched_ids
        self.watched_episodes = watched_ids(self.meta.get('videos', []), saved)
        self._resume_marker = None
        self.refresh_resume_state()
        self.select_section('Episodes')
        self.getControl(501).selectItem(min(pos, max(0, len(self.cards) - 1)))
        self.setFocusId(501)

    def episode_context_menu(self):
        if self.section != 'Episodes' or self.getFocusId() != 501:
            return False
        pos = self.getControl(501).getSelectedPosition()
        if not 0 <= pos < len(self.cards):
            return False
        episode = self.cards[pos]
        target_id = str(episode.get('id') or '')
        if not target_id:
            return False
        watched = target_id in self.watched_episodes
        from episode_actions import through_is_watched
        prefix_watched = through_is_watched(
            self.meta.get('videos') or [], target_id, self.watched_episodes)
        from lib.media_action_menu import choose
        from context_options import episode_options
        resume = bool(target_id == self.play_target and api.resume_seconds(self.resume_ms))
        selected = choose(PATH, episode_options(watched, prefix_watched, resume))
        if selected is None:
            return True
        if selected == 'play':
            resume = self.resume_ms if target_id == self.play_target else 0
            self.choose_source(target_id, resume_ms=resume)
            return True
        if selected == 'restart':
            self.choose_source(target_id, resume_ms=0)
            return True
        if selected == 'info':
            title = episode.get('name') or episode.get('title') or 'Episode'
            plot = clean(episode.get('description') or episode.get('overview') or 'No episode description is available.')
            themed_dialog().textviewer(title, plot)
            return True
        operation = None
        if selected == 'toggle-watched':
            operation = lambda: api.mark_episode(self.meta, target_id, not watched)
        elif selected == 'through-watched':
            operation = lambda: api.mark_episodes_through(self.meta, target_id, True)
        elif selected == 'through-unwatched':
            operation = lambda: api.mark_episodes_through(self.meta, target_id, False)
        if operation is not None:
            result = self.busy('Updating watched episodes', operation)
            if result is not None:
                self._refresh_episode_cards(pos)
        return True

    def refresh_resume_state(self):
        if not self.initialized or xbmc.Player().isPlayingVideo():
            return
        saved = api.saved(self.meta)
        state = saved.get('state') or {}
        marker = (saved.get('_mtime'), state.get('video_id'), state.get('timeOffset'), state.get('watched'))
        if marker == getattr(self, '_resume_marker', None):
            return
        self._resume_marker = marker
        from lib.episode_state import watched_ids
        self.watched_episodes = watched_ids(self.meta.get('videos', []), saved)
        if self.meta.get('type') == 'series':
            next_video, self.resume_ms = api.next_series_episode(
                self.meta.get('videos', []), self.meta['id'], saved)
            if next_video:
                self.play_target = next_video['id']
                self.season = int(next_video.get('season', self.season))
        else:
            self.resume_ms = state.get('timeOffset') or 0
        self.setProperty('playlabel', 'Resume' if api.resume_seconds(self.resume_ms) else 'Play')
        self.prefetch_streams(self.play_target)

    def onFocus(self, control_id):
        if self.initialized:
            self.refresh_resume_state()
            self.streams_focus(control_id)

    def onAction(self, action):
        if isinstance(getattr(xbmcgui, '__name__', None), str):
            from lib.ui_dialogs import dialog as themed_dialog
        else:
            themed_dialog = xbmcgui.Dialog
        self.refresh_resume_state()
        if self.streams_action(action):
            return
        was_preview = bool(self.preview_url)
        self.cancel_trailer()
        aid = action.getId()
        if aid == 117 and self.episode_context_menu():
            return
        if aid in BACK and was_preview:
            return
        if aid in BACK:
            if self.menu_mode:
                target = 22011 if self.menu_mode == 'seasons' else 22001
                self.clearProperty('menu')
                self.menu_mode = None
                self.setFocusId(target)
            else:
                self.close()
        elif aid == 4 and self.getFocusId() in (21001, 21002, 21005):
            self.setFocusId(22001)

    def onClick(self, cid):
        if isinstance(getattr(xbmcgui, '__name__', None), str):
            from lib.ui_dialogs import dialog as themed_dialog
        else:
            themed_dialog = xbmcgui.Dialog
        if self.streams_click(cid):
            return
        self.cancel_trailer()
        if cid == 22001:
            self.open_menu('sections')
        elif cid == 22011:
            self.open_menu('seasons')
        elif cid == 600:
            pos = self.getControl(600).getSelectedPosition()
            if 0 <= pos < len(self.menu_entries):
                if self.menu_mode == 'seasons':
                    self.season = self.menu_entries[pos]
                    self.select_section('Episodes')
                else:
                    self.select_section(self.menu_entries[pos])
                self.setFocusId(self.active_list if self.cards else 22001)
        elif cid == 21001:
            if self.play_target:
                self.choose_source(self.play_target, resume_ms=self.resume_ms)
            else:
                self.report('Select an episode when episode metadata is available.')
        elif cid == 21002:
            self.play_trailer()
        elif cid == 21005:
            if not api.STORE.load().get('token'):
                self.report('Connect your Stremio account in Settings first.')
                return
            self.busy('Updating library', lambda: api.toggle_library(self.meta))
            self.refresh_library()
        elif cid in (500, 501, 502, 503):
            pos = self.getControl(cid).getSelectedPosition()
            if not 0 <= pos < len(self.cards):
                return
            row = self.cards[pos]
            if self.section == 'Similar':
                self.details(row)
            elif self.section == 'Episodes':
                self.choose_source(row['id'], resume_ms=self.resume_ms if row['id'] == self.play_target else 0)
            elif self.section in ('Cast', 'Crew'):
                themed_dialog().ok(row['name'], row.get('job', self.section))

