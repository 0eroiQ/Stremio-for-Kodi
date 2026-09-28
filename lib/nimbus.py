"""Embedded Nimbus program windows. All navigation stays inside this addon."""
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

ADDON = get_addon()
PATH = ADDON.getAddonInfo('path')
BACK = (10, 92, 216, 247)


from lib.theme import window as themed_window


def clean(value):
    return re.sub(r'<[^>]+>', '', str(value or ''))


def item(row):
    li = xbmcgui.ListItem(clean(row.get('name') or row.get('title') or ''))
    li.setArt({'poster': row.get('poster', ''), 'thumb': row.get('thumbnail') or row.get('poster', ''),
               'fanart': row.get('background') or row.get('poster', '')})
    li.setProperty('id', str(row.get('id', '')))
    li.setProperty('type', str(row.get('type', 'movie')))
    li.setProperty('plot', clean(row.get('description')))
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
        progress = xbmcgui.DialogProgressBG()
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

    def details(self, row):
        self.preview_suspended = True
        self.cancel_trailer()
        try:
            window = themed_window(InfoWindow, 'script-stremio-info.xml', PATH, 'Main', '1080i', meta=row)
            window.doModal()
            del window
        finally:
            self.preview_suspended = False


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
        super().__init__(*args, **kwargs)

    def onInit(self):
        if getattr(self, 'initialized', False):
            return
        self.initialized = True
        self.rows = {400+i: [] for i in range(self.row_count)}
        self.hero_key = None
        self.getControl(9000).addItems([xbmcgui.ListItem(label) for label in
                                      ('Home', 'Search', 'Discover', 'Library', 'Addons', 'Settings')])
        self.load_home()
        self.setFocusId(9000)

    def load_home(self):
        self.populate_rows('Home', self.account_rows)

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

    def onAction(self, action):
        aid = action.getId()
        if aid in BACK:
            if not getattr(self, 'exit_armed', False):
                self.cancel_trailer()
                self.setFocusId(9000)
                self.exit_armed = True
                return
            self.exit_armed = False
            if xbmcgui.Dialog().yesno(
                    'Exit Stremio for Kodi',
                    'Do you want to exit Stremio for Kodi?',
                    nolabel='Cancel', yeslabel='Exit'):
                self.close()
            return
        if aid in (1, 2, 3, 4, 7, 11, 100, 101):
            self.exit_armed = False
        if aid == 117 and self.getProperty('page') == 'Discover':
            self.edit_filters()
            return
        if aid == 11 and self.getFocusId() in self.rows:
            self.onClick(self.getFocusId())
        else:
            self.update_hero()

    def onClick(self, cid):
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
            cid = (202, 201, 203, 204, 205, 206)[pos] if 0 <= pos < 6 else 202
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
            query = xbmcgui.Dialog().input('Search movies and series').strip()
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
            choice = xbmcgui.Dialog().select('Stremio for Kodi Settings', ['Account', 'Add-on settings', 'About Nimbus', 'Browse all addon features'])
            if choice == 0:
                from settings_ui import account_menu
                account_menu()
            elif choice == 1:
                from lib.appearance import options
                before = options(ADDON)
                api.CORE.openSettings()
                from lib.playback_settings import apply
                apply()
                if options(ADDON) != before:
                    self.reload_appearance = True
                    self.close()
            elif choice == 2:
                xbmcgui.Dialog().textviewer('Nimbus · Stremio for Kodi',
                    'Nimbus by Ivar Brandt\nEmbedded program adaptation for Stremio for Kodi.\nGPL-2.0-or-later.\nKodi remains the playback engine.')

            elif choice == 3:
                self.close()
                xbmc.executebuiltin('ActivateWindow(Videos,plugin://script.stremioelec/?action=root,return)')


class InfoWindow(NimbusWindow):
    def __init__(self, *args, **kwargs):
        self.preview = kwargs.pop('meta')
        super().__init__(*args, **kwargs)
        self.initialized = False
        self.menu_mode = None
        self.section = ''
        self.section_cache = {}
        self.cards = []
        self.play_target = ''
        self.resume_ms = 0

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
        else:
            self.play_target = self.meta['id']
            self.resume_ms = (saved.get('state') or {}).get('timeOffset') or 0
        self.setProperty('playlabel', 'Resume' if api.resume_seconds(self.resume_ms) else 'Play')
        self.setProperty('hastrailer', 'true' if ADDON.getSetting('trailers_enabled') != 'false' and imdb_id(self.meta) else '')
        self.refresh_library()
        self.select_section('Episodes' if series else 'Similar')
        self.setFocusId(501 if series and self.cards else 21001)
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
        for row in rows:
            li = item(row)
            li.setProperty('initials', row.get('code') or ''.join(p[:1] for p in row.get('name', '').split()[:2]).upper())
            li.setProperty('job', row.get('job', ''))
            if section == 'Episodes':
                li.setProperty('watched', 'true' if row.get('id') in self.watched_episodes else '')
                number = row.get('episode') or row.get('number') or ''
                li.setLabel('{}. {}'.format(number, row.get('name') or row.get('title') or 'Episode'))
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

    def onAction(self, action):
        was_preview = bool(self.preview_url)
        self.cancel_trailer()
        aid = action.getId()
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
        elif aid == 4 and self.getFocusId() in (21001, 21002, 21003, 21004, 21005):
            self.setFocusId(22001)

    def onClick(self, cid):
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
        elif cid in (21001, 21003, 21004):
            if self.play_target:
                self.choose_source(self.play_target, quality=(cid == 21003), resume_ms=self.resume_ms)
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
                self.choose_source(row['id'])
            elif self.section in ('Cast', 'Crew'):
                xbmcgui.Dialog().ok(row['name'], row.get('job', self.section))

    def choose_source(self, identity, quality=False, resume_ms=0):
        cache_key = 'streams:' + identity
        if cache_key not in self.section_cache:
            result = self.busy('Finding sources', lambda: api.source_rows(self.meta, identity))
            if result is None:
                return
            self.section_cache[cache_key] = result
        rows, skipped, failed = self.section_cache[cache_key]
        if not rows:
            self.report('No supported sources. {} unsupported · {} providers unavailable.'.format(skipped, failed))
            return
        if quality:
            choices = sorted({r['card']['quality'] for r in rows})
            pos = xbmcgui.Dialog().select('Quality', choices)
            if pos < 0:
                return
            rows = [r for r in rows if r['card']['quality'] == choices[pos]]
        labels = ['{} · {}'.format(r['card']['quality'], clean(r.get('label'))) for r in rows]
        choice = xbmcgui.Dialog().select('Sources', labels)
        if choice >= 0:
            play_meta = dict(self.meta)
            if self.meta['type'] == 'series':
                video = next((v for v in self.meta.get('videos', []) if v.get('id') == identity), {})
                play_meta.update(id=identity, name=video.get('name') or video.get('title') or self.meta.get('name'),
                                 season=video.get('season'), episode=video.get('episode'),
                                 tvshowtitle=self.meta.get('name'), _media_type='episode')
            api.play(play_meta, identity, rows[choice], resume_ms)
