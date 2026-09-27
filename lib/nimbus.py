"""Embedded Nimbus program windows. All navigation stays inside this addon."""
import re
from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcgui

from lib import backend as api

ADDON = get_addon()
PATH = ADDON.getAddonInfo('path')
BACK = (10, 92, 216, 247)


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
        values = {'title': clean(row.get('name')), 'plot': clean(row.get('description')),
                  'fanart': row.get('background') or row.get('poster') or '',
                  'logo': row.get('logo') or '',
                  'genres': ' · '.join(row.get('genres') or []),
                  'facts': '  ·  '.join(str(v) for v in (
                      row.get('releaseInfo') or row.get('year'),
                      ('★ ' + str(row['imdbRating'])) if row.get('imdbRating') else '',
                      row.get('runtime'), 'Series' if row.get('type') == 'series' else 'Movie') if v)}
        for key, value in values.items():
            self.setProperty(key, value)

    def details(self, row):
        window = InfoWindow('script-stremio-info.xml', PATH, 'Main', '1080i', meta=row)
        window.doModal()
        del window


class HomeWindow(NimbusWindow):
    def __init__(self, *args, **kwargs):
        self.account_rows = kwargs.pop('account_rows', [])
        self.row_count = kwargs.pop('row_count', 2)
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
        self.setProperty('page', section)
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
            up = available[index-1] if index else 9000
            down = available[index+1] if index+1 < len(available) else cid
            self.getControl(cid).setNavigation(self.getControl(up), self.getControl(down),
                                               self.getControl(9000), self.getControl(cid))
        self.setProperty('first_row', str(available[0] if available else 9000))
        failed = sum(bool(c.get('failed')) for c in catalogs)
        self.report(('Some account catalogs could not load. Reopen the addon to retry.' if failed else '')
                    if available else 'No account catalogs available. Check your Stremio add-ons and connection.')
        selected = available[0] if available else 9000
        self.setFocusId(selected)
        self.update_hero()

    def update_hero(self):
        cid = self.getFocusId()
        if cid not in self.rows:
            return
        following = next((key for key in self.rows if key > cid and self.rows[key]), None)
        self.setProperty('next_row', self.row_labels.get(following, ''))
        pos = self.getControl(cid).getSelectedPosition()
        if 0 <= pos < len(self.rows[cid]):
            row = self.rows[cid][pos]
            key = (cid, pos, row['id'])
            if key != self.hero_key:
                self.hero_key = key
                self.set_hero(row)

    def onFocus(self, control_id):
        if getattr(self, 'initialized', False):
            self.update_hero()

    def onAction(self, action):
        if action.getId() in BACK:
            if self.getFocusId() in self.rows:
                self.setFocusId(9000)
            else:
                self.close()
        elif action.getId() == 11 and self.getFocusId() in self.rows:
            self.onClick(self.getFocusId())
        else:
            self.update_hero()

    def onClick(self, cid):
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
            genres = ['All', 'Action', 'Adventure', 'Animation', 'Comedy', 'Crime', 'Documentary',
                      'Drama', 'Fantasy', 'Horror', 'Mystery', 'Romance', 'Sci-Fi', 'Thriller']
            choice = xbmcgui.Dialog().select('Discover · Genre', genres)
            if choice >= 0:
                genre = '' if choice == 0 else genres[choice]
                def load():
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        return list(pool.map(lambda k: api.catalog(k, genre), ('movie', 'series')))
                result = self.busy('Discover', load) or ([], [])
                self.populate('Discover · ' + genres[choice], *result)
        elif cid == 204:
            rows = api.library()
            self.populate('Library', [r for r in rows if r.get('type') == 'movie'],
                          [r for r in rows if r.get('type') == 'series'])
        elif cid == 205:
            rows = api.providers()
            choice = xbmcgui.Dialog().select('Installed Stremio addons',
                [r.get('manifest', {}).get('name', 'Addon') for r in rows]) if rows else -1
            if choice >= 0:
                manifest = rows[choice].get('manifest', {})
                xbmcgui.Dialog().textviewer(manifest.get('name', 'Addon'), clean(manifest.get('description')))
            elif not rows:
                xbmcgui.Dialog().ok('Addons', 'No active Stremio addons. Connect or sync your account in Settings.')
        elif cid == 206:
            choice = xbmcgui.Dialog().select('Stremio for Kodi Settings', ['Account', 'Add-on settings', 'About Nimbus', 'Browse all addon features'])
            if choice == 0:
                from settings_ui import account_menu
                account_menu()
            elif choice == 1:
                api.CORE.openSettings()
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
        self.meta = self.busy('Loading details', lambda: api.metadata(self.preview)) or self.preview
        self.set_hero(self.meta)
        series = self.meta.get('type') == 'series'
        self.setProperty('series', 'true' if series else '')
        self.available_seasons = api.seasons(self.meta)
        regular = [r for r in self.available_seasons if r['season'] > 0]
        self.season = (regular or self.available_seasons or [{'season': 1}])[0]['season']
        saved = api.saved(self.meta)
        if series:
            next_video, self.resume_ms = api.next_series_episode(self.meta.get('videos', []), self.meta['id'], saved)
            if next_video:
                self.play_target = next_video['id']
                self.season = int(next_video.get('season', self.season))
        else:
            self.play_target = self.meta['id']
            self.resume_ms = (saved.get('state') or {}).get('timeOffset') or 0
        self.setProperty('playlabel', 'Resume' if api.resume_seconds(self.resume_ms) else 'Play')
        self.setProperty('hastrailer', 'true' if api.trailer_rows(self.meta) else '')
        self.refresh_library()
        self.select_section('Episodes' if series else 'Cast')
        self.setFocusId(21001)

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
        self.active_list = 500 if section in ('Cast', 'Crew') else 502 if section == 'Languages' else 501
        for cid in (500, 501, 502):
            self.getControl(cid).reset()
        items = []
        for row in rows:
            li = item(row)
            li.setProperty('initials', row.get('code') or ''.join(p[:1] for p in row.get('name', '').split()[:2]).upper())
            li.setProperty('job', row.get('job', ''))
            if section == 'Episodes':
                number = row.get('episode') or row.get('number') or ''
                li.setLabel('{}. {}'.format(number, row.get('name') or row.get('title') or 'Episode'))
                li.setArt({'thumb': row.get('thumbnail') or self.meta.get('background', '')})
            elif section == 'Similar':
                li.setArt({'thumb': row.get('background') or row.get('poster', '')})
            items.append(li)
        self.getControl(self.active_list).addItems(items)
        self.setProperty('hascards', 'true' if rows else '')
        if not rows:
            self.report('No {} provided for this title.'.format(section.lower()))

    def open_menu(self, mode):
        self.menu_mode = mode
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
        aid = action.getId()
        if aid in BACK:
            if self.menu_mode:
                self.clearProperty('menu')
                self.menu_mode = None
                self.setFocusId(22001)
            else:
                self.close()
        elif aid == 4 and self.getFocusId() in (21001, 21002, 21003, 21004, 21005):
            self.setFocusId(22001)

    def onClick(self, cid):
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
            trailers = api.trailer_rows(self.meta)
            if trailers:
                from urllib.parse import urlencode
                vid = trailers[0]['id']
                if xbmc.getCondVisibility('System.HasAddon(slyguy.trailers)'):
                    url = 'plugin://slyguy.trailers/play/?' + urlencode({'video_id': vid})
                elif xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
                    url = 'plugin://plugin.video.youtube/play/?' + urlencode({'video_id': vid})
                else:
                    self.report('Install a Kodi trailer provider to play this trailer.')
                    return
                xbmc.executebuiltin('PlayMedia(' + url + ')')
        elif cid == 21005:
            if not api.STORE.load().get('token'):
                self.report('Connect your Stremio account in Settings first.')
                return
            self.busy('Updating library', lambda: api.toggle_library(self.meta))
            self.refresh_library()
        elif cid in (500, 501, 502):
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
