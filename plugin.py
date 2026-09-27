"""Kodi entry point. No account writes, library mutations or torrent engine."""
import sys
import time
import re
import json
import html
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

import xbmcaddon
from addon_state import get_addon
import xbmc
import xbmcvfs
import xbmcgui
import xbmcplugin

from protocol import base_url, catalogs, fetch, resource_url
from account import AccountError, Store, create_link, read_link, pull_addons, pull_library, library_rows
from sources import collect, direct_url, supports
from stream_ui import stream_card
from continue_playback import button_label, resume_seconds, next_series_episode
from addons_core import active_addons, community_catalog, configuration_state, descriptor_id, filter_community, merge_account
from metadata_bridge import (details as metadata_details, people as metadata_people,
                             languages as metadata_languages,
                             seasons as metadata_seasons, episodes as metadata_episodes,
                             recommendations as metadata_recommendations,
                             search as metadata_search,
                             trailer_rows as metadata_trailers, runtime_seconds)

HANDLE = int(sys.argv[1])
BASE = 'plugin://script.stremioelec/'
ADDON = get_addon()
MANIFEST = ADDON.getSetting('manifest').strip()
HOME_MANIFEST = 'https://v3-cinemeta.strem.io/manifest.json'
COMMUNITY_RUNTIME_WINDOW_ID = 11194
STREAMS_WINDOW_ID = 10000
STORE = Store(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')))



def plain_text(value, limit=1200):
    value = re.sub(r'<[^>]*>', ' ', str(value or ''))
    value = html.unescape(value)
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def safe_image(value):
    if not isinstance(value, str):
        return ''
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        return ''
    return value


def resource_names(manifest):
    rows = []
    for resource in manifest.get('resources', []):
        name = resource.get('name') if isinstance(resource, dict) else resource
        if isinstance(name, str) and name not in rows:
            rows.append(name)
    return rows


def connect_account():
    if not xbmcgui.Dialog().yesno('Connect Stremio',
            'Sign in on the official Stremio page. This device will store a session token '
            'and your addon URLs locally (not encrypted). Continue?'):
        return
    code, link = create_link()
    progress = xbmcgui.DialogProgress()
    progress.create('Connect Stremio', 'Open on your phone or computer:\n' + link)
    monitor = xbmc.Monitor()
    deadline = time.monotonic() + 300
    try:
        while time.monotonic() < deadline and not progress.iscanceled():
            if monitor.abortRequested():
                return
            token = read_link(code)
            if progress.iscanceled() or monitor.abortRequested():
                return
            if token:
                addons, skipped = pull_addons(token)
                if progress.iscanceled() or monitor.abortRequested():
                    return
                state = STORE.load()
                state['token'] = token
                state['addons'] = merge_account(state, addons)
                STORE.save(state)
                try:
                    library = pull_library(token)
                    state['library'] = library
                    STORE.save(state)
                except AccountError:
                    xbmcgui.Dialog().notification('Stremio', 'Library import failed; retry Refresh library.')
                progress.close()
                xbmcgui.Dialog().ok('Stremio connected',
                    '{} addons imported. {} unsupported entries skipped.'.format(len(addons), skipped))
                return
            if monitor.waitForAbort(5):
                return
        if not progress.iscanceled():
            xbmcgui.Dialog().ok('Stremio', 'Sign-in timed out. Start again for a new link.')
    finally:
        progress.close()


def route(**params):
    return BASE + '?' + urlencode(params)


def trailer_route(identity):
    from lib.trailer_options import playback_url
    return playback_url(identity)


def catalog_entries(state, section='home'):
    """Return account catalog folders without exposing transport URLs."""
    rows = []
    for addon in active_addons(state):
        manifest = addon.get('manifest', {})
        manifest_id = str(manifest.get('id') or '').lower()
        for catalog in manifest.get('catalogs', []):
            if not isinstance(catalog, dict) or not catalog.get('id') or not catalog.get('type'):
                continue
            catalog_id = str(catalog['id'])
            name = str(catalog.get('name') or catalog_id)
            discover_marker = 'discover' in catalog_id.lower() or 'discover' in name.lower()
            extras = {
                str(extra.get('name') or ''): extra
                for extra in catalog.get('extra', [])
                if isinstance(extra, dict) and extra.get('name')
            }
            required = {
                extra_name for extra_name, extra in extras.items()
                if extra.get('isRequired')
            }
            if required.intersection({'lastVideosIds', 'calendarVideosIds'}):
                continue
            if 'search' in required and 'genre' not in extras and not discover_marker:
                continue
            if section == 'home' and (required or discover_marker):
                continue
            if section == 'discover' and not (required or discover_marker):
                continue
            values = {'action': 'catalog', 'provider': addon['id'],
                      'kind': catalog['type'], 'id': catalog_id}
            if 'cinemeta' in manifest_id:
                values = {'action': 'home_catalog', 'home': '1',
                          'kind': catalog['type'], 'id': catalog_id}
            genre = extras.get('genre')
            if 'genre' in required and isinstance(genre, dict):
                options = genre.get('options') or []
                if options:
                    values['genre'] = str(options[0])
            kind = {'movie': 'Movies', 'series': 'Series', 'mixed': 'Mixed'}.get(
                str(catalog['type']).lower(), str(catalog['type']).title())
            label = name if kind == 'Mixed' else '{} · {}'.format(name, kind)
            rows.append((label, route(**values)))
    return rows

def add_catalog_folders(section):
    xbmcplugin.setContent(HANDLE, 'files')
    for label, target in catalog_entries(STORE.load(), section):
        entry = xbmcgui.ListItem(label=label)
        entry.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(HANDLE, target, entry, True)


def add_installed_addons():
    state = STORE.load()
    disabled = set(state.get('disabledAddons', []))
    xbmcplugin.setContent(HANDLE, 'addons')
    for addon in state.get('addons', []):
        if not isinstance(addon, dict) or not isinstance(addon.get('manifest'), dict):
            continue
        manifest = addon['manifest']
        name = str(manifest.get('name') or 'Stremio addon')
        entry = xbmcgui.ListItem(label=name)
        logo = safe_image(manifest.get('logo')) or 'DefaultAddon.png'
        entry.setArt({'icon': logo, 'thumb': logo})
        entry.setProperty('StremioInstalled', 'Disabled' if addon.get('id') in disabled else 'Installed')
        entry.setProperty('StremioVersion', str(manifest.get('version') or ''))
        entry.setProperty('StremioDescription', plain_text(manifest.get('description') or ''))
        xbmcplugin.addDirectoryItem(
            HANDLE, route(action='addon_action', id=addon.get('id', '')), entry, False)


def item(meta):
    meta = dict(meta or {})
    identity = str(meta.get('id', ''))
    media_type = meta.get('_media_type') or ('tvshow' if meta.get('type') == 'series' else 'movie')
    entry = xbmcgui.ListItem(label=meta.get('name') or identity)
    info = entry.getVideoInfoTag()
    info.setTitle(meta.get('name', ''))
    info.setPlot(meta.get('description', ''))
    info.setMediaType(media_type)

    imdb = str(meta.get('imdb_id') or (identity if re.fullmatch(r'tt[0-9]+', identity) else ''))
    tmdb = str(meta.get('moviedb_id') or '')
    ids = {}
    if imdb:
        ids['imdb'] = imdb
    if tmdb:
        ids['tmdb'] = tmdb
    if ids:
        try:
            info.setUniqueIDs(ids, 'imdb' if imdb else 'tmdb')
        except Exception:
            pass

    year_text = str(meta.get('year') or meta.get('releaseInfo') or meta.get('released') or '')
    year_match = re.search(r'(19|20)\d{2}', year_text)
    details = {
        'title': meta.get('name', ''),
        'plot': meta.get('description', ''),
        'mediatype': media_type,
        'genre': meta.get('genres') or [],
        'cast': meta.get('cast') or [],
        'director': meta.get('director') or [],
        'writer': meta.get('writer') or [],
        'duration': runtime_seconds(meta.get('runtime')),
        'country': meta.get('country') or '',
        'status': meta.get('status') or '',
    }
    for key in ('season', 'episode'):
        try:
            if meta.get(key) is not None:
                details[key] = int(meta.get(key))
        except (TypeError, ValueError):
            pass
    if meta.get('tvshowtitle'):
        details['tvshowtitle'] = str(meta.get('tvshowtitle'))
    if meta.get('released'):
        details['premiered'] = str(meta.get('released'))[:10]
    if year_match:
        details['year'] = int(year_match.group(0))
    try:
        if meta.get('imdbRating') not in (None, ''):
            details['rating'] = float(meta.get('imdbRating'))
    except (TypeError, ValueError):
        pass
    try:
        entry.setInfo('video', details)
    except Exception:
        pass
    from lib.trailer_options import imdb_id
    trailer_identity = imdb_id(meta)
    if trailer_identity:
        trailer = trailer_route(trailer_identity)
        try:
            info.setTrailer(trailer)
        except Exception:
            entry.setProperty('Trailer', trailer)
        entry.setProperty('StremioTrailerURL', trailer)

    entry.setProperty('StremioID', identity)
    entry.setProperty('StremioType', str(meta.get('type', '')))
    if identity:
        stremio_kind = 'series' if media_type == 'tvshow' else 'movie'
        entry.setProperty('StremioCastPath',
                          route(action='details_cast', kind=stremio_kind, id=identity))
        entry.setProperty('StremioCrewPath',
                          route(action='details_crew', kind=stremio_kind, id=identity))
        entry.setProperty('StremioRecommendationsPath',
                          route(action='details_recommendations', kind=stremio_kind, id=identity))
        entry.setProperty('StremioLanguagesPath',
                          route(action='details_languages', kind=stremio_kind, id=identity))
        entry.setProperty('StremioTrailersPath',
                          route(action='details_trailers', kind=stremio_kind, id=identity))
    if media_type == 'tvshow' and identity:
        entry.setProperty('StremioSeriesID', identity)
        entry.setProperty('StremioMoreEpisodesPath',
                          route(action='more_episodes', kind='series', id=identity,
                                layout='bingie527v2'))
        available_seasons = metadata_seasons(meta)
        regular_seasons = [row for row in available_seasons
                           if int(row.get('season', 0)) > 0]
        default_season = (regular_seasons[0] if regular_seasons else
                          (available_seasons[0] if available_seasons else {'season': 0}))
        default_season_number = int(default_season.get('season', 0))
        entry.setProperty('StremioDefaultSeason', str(default_season_number))
        entry.setProperty('StremioDefaultSeasonLabel',
                          'Specials' if default_season_number == 0 else
                          'Season {}'.format(default_season_number))
        entry.setProperty('StremioEpisodesPath',
                          route(action='episodes', kind='series', id=identity,
                                season=str(default_season_number)))
    if meta.get('genres'):
        entry.setProperty('StremioGenre', str(meta['genres'][0]))
    if meta.get('director'):
        entry.setProperty('StremioDirector', str(meta['director'][0]))
    if meta.get('writer'):
        entry.setProperty('StremioWriter', str(meta['writer'][0]))
    if year_match:
        entry.setProperty('StremioYear', year_match.group(0))
    if imdb:
        entry.setProperty('imdb_id', imdb)
    if tmdb:
        entry.setProperty('tmdb_id', tmdb)
    if meta.get('tvdb_id') not in (None, ''):
        entry.setProperty('tvdb_id', str(meta.get('tvdb_id')))
    if meta.get('country'):
        entry.setProperty('StremioCountry', str(meta.get('country')))
    if meta.get('status'):
        entry.setProperty('StremioStatus', str(meta.get('status')))
    if meta.get('awards'):
        entry.setProperty('StremioAwards', str(meta.get('awards')))
    if meta.get('imdbRating') not in (None, ''):
        entry.setProperty('StremioRating', str(meta.get('imdbRating')))
    if meta.get('runtime'):
        entry.setProperty('StremioRuntime', str(meta.get('runtime')))
    entry.setArt({key: value for key, value in {
        'poster': meta.get('poster'),
        'thumb': meta.get('landscape') or meta.get('background') or 'DefaultVideo.png',
        'landscape': meta.get('landscape') or meta.get('background') or 'DefaultVideo.png',
        'fanart': meta.get('background'),
        'clearlogo': meta.get('logo')
    }.items() if isinstance(value, str) and value})
    return entry


def episode_item(video, series_meta=None):
    series_meta = series_meta or {}
    season = video.get('season')
    episode = video.get('episode') if video.get('episode') is not None else video.get('number')
    title = video.get('title') or video.get('name') or (
        'Episode {}'.format(episode) if episode not in (None, '') else 'Episode')
    prefix = ''
    if season not in (None, '') or episode not in (None, ''):
        prefix = 'S{} E{} · '.format(
            season if season not in (None, '') else '?',
            episode if episode not in (None, '') else '?')
    entry = xbmcgui.ListItem(label=prefix + title)
    info = entry.getVideoInfoTag()
    info.setMediaType('episode')
    info.setTitle(title)
    if isinstance(season, int) or str(season).isdigit():
        info.setSeason(int(season))
    if isinstance(episode, int) or str(episode).isdigit():
        info.setEpisode(int(episode))
    show_title = series_meta.get('name') or series_meta.get('title')
    if isinstance(show_title, str) and show_title:
        info.setTvShowTitle(show_title)
    plot = video.get('overview') or video.get('description') or ''
    if isinstance(plot, str) and plot:
        info.setPlot(plot)
    duration = runtime_seconds(video.get('runtime') or series_meta.get('runtime'))
    if duration:
        try:
            info.setDuration(duration)
        except Exception:
            pass
    released = video.get('released') or video.get('firstAired')
    if isinstance(released, str) and released:
        first_aired = released[:10]
        info.setFirstAired(first_aired)
        if first_aired[:4].isdigit():
            info.setYear(int(first_aired[:4]))
    identity = str(video.get('id') or '')
    if re.fullmatch(r'tt[0-9]+', identity):
        info.setUniqueIDs({'imdb': identity}, 'imdb')
    thumb = (video.get('thumbnail') or video.get('poster') or video.get('background')
             or series_meta.get('landscape') or series_meta.get('background')
             or series_meta.get('poster'))
    fanart = video.get('background') or series_meta.get('background') or thumb
    art = {}
    if isinstance(thumb, str) and thumb:
        art.update({'thumb': thumb, 'landscape': thumb, 'poster': thumb})
    if isinstance(fanart, str) and fanart:
        art['fanart'] = fanart
    show_poster = series_meta.get('poster')
    show_fanart = series_meta.get('background')
    show_logo = series_meta.get('logo')
    if isinstance(show_poster, str) and show_poster:
        art['tvshow.poster'] = show_poster
    if isinstance(show_fanart, str) and show_fanart:
        art['tvshow.fanart'] = show_fanart
    if isinstance(show_logo, str) and show_logo:
        art['tvshow.clearlogo'] = show_logo
    if art:
        entry.setArt(art)
    series_id = str(series_meta.get('id') or identity.split(':', 1)[0])
    entry.setProperty('StremioID', identity)
    entry.setProperty('StremioType', 'series')
    entry.setProperty('StremioSeriesID', series_id)
    if series_id:
        entry.setProperty('StremioMoreEpisodesPath',
                          route(action='more_episodes', kind='series', id=series_id,
                                layout='bingie527v2'))
    return entry


def season_item(row, series_meta):
    season = int(row.get('season', 0))
    count = int(row.get('count', 0))
    label = 'Specials' if season == 0 else 'Season {}'.format(season)
    entry = xbmcgui.ListItem(label=label)
    tag = entry.getVideoInfoTag()
    tag.setMediaType('season')
    tag.setTitle(label)
    tag.setSeason(season)
    series_id = str(series_meta.get('id', ''))
    entry.setProperty('StremioID', series_id)
    entry.setProperty('StremioType', 'series')
    entry.setProperty('StremioSeriesID', series_id)
    entry.setProperty('StremioSeason', str(season))
    entry.setProperty('TotalEpisodes', str(count))
    if series_id:
        entry.setProperty('StremioMoreEpisodesPath',
                          route(action='episodes', kind='series',
                                id=series_id, season=str(season)))
    art = {}
    for key, value in {
        'poster': series_meta.get('poster'),
        'landscape': series_meta.get('background'),
        'fanart': series_meta.get('background'),
        'tvshow.poster': series_meta.get('poster'),
        'tvshow.fanart': series_meta.get('background'),
        'tvshow.clearlogo': series_meta.get('logo'),
    }.items():
        if isinstance(value, str) and value:
            art[key] = value
    if art:
        entry.setArt(art)
    return entry


def configure_streams_window(play_meta, kind, stream_id, selected_provider, resume_ms):
    window = xbmcgui.Window(STREAMS_WINDOW_ID)
    names = [
        'Title', 'Subtitle', 'Meta', 'Poster', 'Landscape', 'HeroImage',
        'Fanart', 'ClearLogo', 'ItemsPath', 'SelectedProvider',
        'SelectedProviderIndex', 'AllPath', 'RefocusChip'
    ]
    for index in range(1, 7):
        names.extend(('Provider{}Name'.format(index),
                      'Provider{}Path'.format(index)))
    for name in names:
        window.clearProperty('StremioStreams.' + name)

    title = str(play_meta.get('tvshowtitle') or play_meta.get('name') or 'Sources')
    subtitle = ''
    if kind == 'series':
        season = play_meta.get('season')
        episode = play_meta.get('episode')
        episode_name = str(play_meta.get('name') or '')
        if season not in (None, '') and episode not in (None, ''):
            subtitle = 'S{}:E{}'.format(season, episode)
            if episode_name and episode_name != title:
                subtitle += ' · ' + episode_name

    year_text = str(play_meta.get('year') or play_meta.get('releaseInfo') or play_meta.get('released') or '')
    year_match = re.search(r'(19|20)\d{2}', year_text)
    genres = play_meta.get('genres') or []
    if isinstance(genres, str):
        genres = [genres]
    meta = ' • '.join(
        [value for value in (
            year_match.group(0) if year_match else '',
            ' / '.join(str(g) for g in genres[:3] if g),
        ) if value])

    window.setProperty('StremioStreams.Title', title)
    window.setProperty('StremioStreams.Subtitle', subtitle)
    window.setProperty('StremioStreams.Meta', meta)
    hero_image = safe_image(play_meta.get('landscape')) or safe_image(play_meta.get('poster'))
    if hero_image:
        window.setProperty('StremioStreams.HeroImage', hero_image)
    for prop, key in (
            ('Poster', 'poster'), ('Landscape', 'landscape'),
            ('Fanart', 'background'), ('ClearLogo', 'logo')):
        value = safe_image(play_meta.get(key))
        if value:
            window.setProperty('StremioStreams.' + prop, value)

    selected = selected_provider if selected_provider and selected_provider != 'all' else 'all'
    window.setProperty('StremioStreams.SelectedProvider', selected)

    cache = Store(STORE.directory / 'streams').load()
    provider_names = []
    if (cache.get('kind') == kind and cache.get('id') == stream_id
            and isinstance(cache.get('raw'), list)):
        for stream in cache['raw']:
            name = str(stream.get('provider') or '').strip()
            if name and name not in provider_names:
                provider_names.append(name)
    if not provider_names:
        for addon in active_addons(STORE.load()):
            manifest = addon.get('manifest', {})
            if not supports(manifest, kind, stream_id):
                continue
            name = str(manifest.get('name') or '').strip()
            if name and name not in provider_names:
                provider_names.append(name)

    common = dict(kind=kind, id=stream_id,
                  resume_ms=str(resume_ms or ''), layout='streams1200v2')
    window.setProperty(
        'StremioStreams.AllPath',
        route(action='stream_select_filter', stream_provider='all', **common))

    selected_index = 0
    for index, provider_name in enumerate(provider_names[:6], 1):
        window.setProperty(
            'StremioStreams.Provider{}Name'.format(index), provider_name)
        window.setProperty(
            'StremioStreams.Provider{}Path'.format(index),
            route(action='stream_select_filter',
                  stream_provider=provider_name, **common))
        if provider_name == selected:
            selected_index = index

    window.setProperty(
        'StremioStreams.SelectedProviderIndex', str(selected_index))
    window.setProperty(
        'StremioStreams.ItemsPath',
        route(action='stream_items', kind=kind, id=stream_id,
              stream_provider=selected, resume_ms=str(resume_ms or ''),
              layout='streams1200v2'))


def stream_list_item(stream, play_meta):
    card = stream_card(stream)
    entry = xbmcgui.ListItem(label=card['headline'])
    entry.setArt({k: v for k, v in {
        'thumb': play_meta.get('landscape') or play_meta.get('poster'),
        'fanart': play_meta.get('background')
    }.items() if isinstance(v, str) and v})
    for prop, value in (
            ('Provider', card['provider']),
            ('Quality', card['quality']),
            ('Headline', card['headline']),
            ('Filename', card['filename']),
            ('Tech', card['tech']),
            ('Meta', card['meta']),
            ('Size', card['size']),
            ('Source', card['source']),
            ('Seeders', card['seeders']),
            ('Languages', card['languages'])):
        if value:
            entry.setProperty('StremioStream.' + prop, value)
    entry.setProperty('IsPlayable', 'true')
    return entry


def run(params):
    # Kodi RunAddon may choose the media extension even for a Program add-on.
    # Ordinary launches must open the same Nimbus interface as Programs.
    if not params.get('action'):
        xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
        xbmc.executebuiltin('RunScript(script.stremioelec)')
        return
    action = params['action']
    if action == 'play_trailer':
        from lib.trailer_options import resolve
        entry = xbmcgui.ListItem()
        try:
            if ADDON.getSetting('trailers_enabled') == 'false':
                raise ValueError('Trailers disabled')
            stream = resolve(params.get('id', ''), int(params.get('season', -1)),
                             ADDON.getSetting('trailers_quality'))
            if not stream:
                raise ValueError('No trailer')
            entry.setPath(stream['url'])
            entry.setLabel(stream['title'])
            entry.setMimeType(stream['mime'])
            entry.setContentLookup(False)
            entry.setProperty('IsPlayable', 'true')
            entry.setProperty('StartOffset', '0')
            entry.setProperty('script.trakt.exclude', '1')
            entry.getVideoInfoTag().setTitle(stream['title'])
            xbmcplugin.setResolvedUrl(HANDLE, True, entry)
        except Exception:
            xbmcgui.Dialog().notification('Stremio for Kodi', 'Trailer unavailable. Please try another title or retry later.')
            xbmcplugin.setResolvedUrl(HANDLE, False, entry)
        return
    if action == 'open_season':
        target = route(action='episodes', kind='series',
                       id=params.get('id', ''), season=params.get('season', '0'))
        xbmc.executebuiltin('Dialog.Close(all,true)')
        xbmc.sleep(250)
        xbmc.executebuiltin('ActivateWindow(Videos,{},return)'.format(target))
        return
    # Kodi may dispatch the subtitle extension through the addon's primary
    # plugin entry point; support both entry paths explicitly.
    if action in ('search', 'manualsearch', 'download'):
        from subtitle_service import run as subtitle_service
        return subtitle_service()
    if action == 'helper_play':
        from helper_player import resolve
        from subtitles import prepare_selected
        providers = active_addons(STORE.load())
        return resolve(params, providers, collect,
                       xbmcgui.Dialog(), xbmcplugin, xbmcgui, HANDLE,
                       lambda kind, identity, stream, item: prepare_selected(STORE.directory, kind, identity, stream, providers, item))
    if action == 'subtitles':
        from subtitles import manual_selection
        manual_selection(STORE.directory, active_addons(STORE.load()))
        return
    if action == 'setup_home':
        from setup_profile import prepare
        prepare(STORE.directory, xbmcvfs.translatePath(ADDON.getAddonInfo('path')), force_home=True)
        xbmcgui.Dialog().notification('Stremio for Kodi', 'Home defaults restored')
        xbmc.executebuiltin('ReloadSkin()')
        return
    if action == 'first_catalog':
        for addon in active_addons(STORE.load()):
            available = catalogs(addon['manifest'])
            if available:
                return run({'action': 'catalog', 'provider': addon['id'],
                            'kind': available[0]['type'], 'id': available[0]['id']})
        xbmcplugin.endOfDirectory(HANDLE)
        return

    if action == 'stream_filters':
        kind = params.get('kind', '')
        identity = params.get('id', '')
        selected = params.get('selected', 'all') or 'all'
        resume_ms = params.get('resume_ms', '')
        cache = Store(STORE.directory / 'streams').load()
        raw = cache.get('raw', []) if (
            cache.get('kind') == kind and cache.get('id') == identity
            and time.time() - cache.get('created', 0) < 300
            and isinstance(cache.get('raw'), list)) else []

        provider_names = []
        for stream in raw:
            name = str(stream.get('provider') or '').strip()
            if name and name not in provider_names:
                provider_names.append(name)

        if not provider_names:
            for addon in active_addons(STORE.load()):
                manifest = addon.get('manifest', {})
                if not supports(manifest, kind, identity):
                    continue
                name = str(manifest.get('name') or '').strip()
                if name and name not in provider_names:
                    provider_names.append(name)

        for value, label in [('all', 'All')] + [(name, name) for name in provider_names]:
            entry = xbmcgui.ListItem(label=label)
            entry.setProperty('StremioFilterSelected',
                              'true' if value == selected else 'false')
            entry.setProperty('StremioFilterValue', value)
            target = route(action='stream_select_filter', kind=kind, id=identity,
                           stream_provider=value, resume_ms=resume_ms,
                           layout='streams1193v1')
            xbmcplugin.addDirectoryItem(HANDLE, target, entry, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    if action == 'stream_items':
        kind = params.get('kind', '')
        identity = params.get('id', '')
        selected = params.get('stream_provider', 'all') or 'all'
        resume_ms = params.get('resume_ms', '')
        cache_store = Store(STORE.directory / 'streams')
        cache = cache_store.load()
        if not (cache.get('kind') == kind and cache.get('id') == identity
                and time.time() - cache.get('created', 0) < 300
                and isinstance(cache.get('raw'), list)
                and isinstance(cache.get('meta'), dict)):
            xbmcplugin.endOfDirectory(HANDLE)
            return

        raw = cache['raw']
        visible = raw if selected == 'all' else [
            stream for stream in raw
            if str(stream.get('provider') or '').strip() == selected
        ]
        import secrets
        urls = dict(cache.get('urls') or {})
        for stream in visible:
            key = secrets.token_hex(16)
            urls[key] = dict(
                stream, kind=kind, id=identity, meta=cache['meta'],
                resume_ms=int(resume_seconds(resume_ms) * 1000))
            xbmcplugin.addDirectoryItem(
                HANDLE, route(action='play', key=key),
                stream_list_item(stream, cache['meta']), False)
        cache['urls'] = urls
        cache_store.save(cache)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    if action == 'stream_select_filter':
        kind = params.get('kind', '')
        identity = params.get('id', '')
        selected = params.get('stream_provider', 'all') or 'all'
        resume_ms = params.get('resume_ms', '')
        cache = Store(STORE.directory / 'streams').load()
        play_meta = cache.get('meta') if (
            cache.get('kind') == kind and cache.get('id') == identity
            and isinstance(cache.get('meta'), dict)) else {}
        if play_meta:
            configure_streams_window(
                play_meta, kind, identity, selected, resume_ms)
            try:
                index = int(xbmcgui.Window(STREAMS_WINDOW_ID).getProperty(
                    'StremioStreams.SelectedProviderIndex') or '0')
            except (TypeError, ValueError):
                index = 0
            xbmc.sleep(250)
            xbmc.executebuiltin('SetFocus({})'.format(101 + max(0, min(index, 6))))
        return

    if action == 'community_catalog':
        window = xbmcgui.Window(COMMUNITY_RUNTIME_WINDOW_ID)
        category = window.getProperty('StremioCommunity.Category') or 'all'
        query = window.getProperty('StremioCommunity.Query')
        cache = Store(STORE.directory / 'community')
        saved = cache.load()
        if (isinstance(saved.get('catalog'), list)
                and time.time() - saved.get('created', 0) < 900):
            catalog_rows = saved['catalog']
        else:
            catalog_rows = community_catalog()
        rows = filter_community(catalog_rows, category, query)
        installed_ids = {item.get('manifest', {}).get('id')
                         for item in STORE.load().get('addons', [])}
        cache.save({'created': time.time(), 'catalog': catalog_rows, 'visible': rows})
        window.setProperty('StremioCommunity.Status',
                           '{} addons{}'.format(len(rows),
                           ' · Search: ' + query if query else ''))
        for row in rows:
            manifest = row['manifest']
            entry = xbmcgui.ListItem(label=manifest.get('name', 'Stremio addon'))
            logo = safe_image(manifest.get('logo')) or safe_image(manifest.get('background')) or 'DefaultAddon.png'
            art = {'thumb': logo, 'icon': logo}
            background = safe_image(manifest.get('background'))
            if background:
                art['fanart'] = background
            entry.setArt(art)
            installed = manifest.get('id') in installed_ids
            config = configuration_state(manifest)
            entry.setProperty('StremioDescription', plain_text(manifest.get('description', '')))
            entry.setProperty('StremioVersion', str(manifest.get('version', '')))
            entry.setProperty('StremioTypes', ', '.join(str(v) for v in manifest.get('types', []) if isinstance(v, str)))
            entry.setProperty('StremioResources', ', '.join(resource_names(manifest)))
            key = descriptor_id(row['transportUrl'])
            entry.setProperty('StremioInstalled', 'Installed' if installed else 'Community addon')
            entry.setProperty('StremioActionLabel',
                              'Press OK · Manage installed addon' if installed else
                              ('Press OK · Configure' if config['required'] else 'Press OK · Install'))
            xbmcplugin.addDirectoryItem(
                HANDLE,
                route(action='community_action', key=key),
                entry,
                False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    if action == 'community_action':
        from addons_ui import community_selected
        key = params.get('key', '')
        saved = Store(STORE.directory / 'community').load()
        row = next((item for item in saved.get('visible', [])
                    if descriptor_id(item.get('transportUrl', '')) == key), None)
        if not row or time.time() - saved.get('created', 0) > 900:
            xbmcgui.Dialog().notification('Community Addons', 'Catalog item expired. Reopen Community Addons.')
        else:
            community_selected(row, xbmcgui.Dialog())
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    if action in ('connect', 'sync', 'sync_library', 'disconnect'):
        if action == 'connect':
            connect_account()
        elif action == 'sync':
            state = STORE.load()
            if not state.get('token'):
                raise AccountError('Connect your account first.')
            addons, skipped = pull_addons(state['token'])
            state['addons'] = merge_account(state, addons)
            STORE.save(state)
            xbmcgui.Dialog().ok('Stremio', '{} addons imported. {} skipped.'.format(len(addons), skipped))
        elif action == 'sync_library':
            state = STORE.load()
            if not state.get('token'):
                raise AccountError('Connect your account first.')
            state['library'] = pull_library(state['token'])
            STORE.save(state)
            xbmcgui.Dialog().ok('Stremio', '{} library entries imported. Account unchanged.'.format(len(state['library'])))
        elif xbmcgui.Dialog().yesno('Disconnect this device',
                'Remove this device login and account-synced addons? Local-only Stremio addons stay on this device. Your online account stays unchanged.'):
            state = STORE.load()
            local = [item for item in state.get('addons', []) if item.get('account') is not True]
            disabled = set(state.get('disabledAddons', []))
            STORE.save({'addons': local,
                        'disabledAddons': sorted(disabled & {item.get('id') for item in local})})
            Store(STORE.directory / 'streams').forget()
            Store(STORE.directory / 'playback').forget()
            Store(STORE.directory / 'subtitle-results').forget()
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        xbmc.executebuiltin('Container.Refresh')
        return
    if action == 'select_info_season':
        identity = params.get('id', '')
        season = params.get('season', '1')
        label = 'Specials' if str(season) == '0' else 'Season {}'.format(season)
        xbmcgui.Window(10000).setProperty(
            'NimbusInfoEpisodes',
            route(action='episodes', kind='series', id=identity, season=str(season)))
        window = xbmcgui.Window(12003)
        window.setProperty('NimbusInfoSeasonLabel', label)
        window.clearProperty('NimbusInfoSeasonMenu')
        window.setProperty('NimbusInfoTab', 'episodes')
        xbmc.sleep(150)
        xbmc.executebuiltin('SetFocus(80)')
        return

    if action in ('details_cast', 'details_crew', 'details_recommendations',
                  'details_trailers', 'seasons', 'episodes', 'more_episodes',
                  'episodes_auto', 'next_episode'):
        state = STORE.load()
        providers = list(active_addons(state))
        kind = params.get('kind', 'movie')
        if kind in ('tv', 'tvshow', 'season', 'episode'):
            kind = 'series'
        identity = params.get('id') or params.get('imdb_id') or ''
        query = params.get('query', '')
        meta = metadata_details(kind, identity, query, providers)

        if action == 'details_cast':
            xbmcplugin.setContent(HANDLE, 'actors')
            for row in metadata_people(meta, 'cast'):
                entry = xbmcgui.ListItem(label=row['name'])
                try:
                    entry.setLabel2(row['job'])
                except Exception:
                    pass
                entry.setProperty('StremioPersonJob', row['job'])
                entry.setProperty('StremioPersonInitials', ''.join(
                    part[:1].upper() for part in row['name'].split()[:2]))
                xbmcplugin.addDirectoryItem(HANDLE, '', entry, False)
        elif action == 'details_crew':
            xbmcplugin.setContent(HANDLE, 'actors')
            for row in metadata_people(meta, 'crew'):
                entry = xbmcgui.ListItem(label=row['name'])
                try:
                    entry.setLabel2(row['job'])
                except Exception:
                    pass
                entry.setProperty('StremioPersonJob', row['job'])
                entry.setProperty('StremioPersonInitials', ''.join(
                    part[:1].upper() for part in row['name'].split()[:2]))
                xbmcplugin.addDirectoryItem(HANDLE, '', entry, False)
        elif action == 'details_languages':
            xbmcplugin.setContent(HANDLE, 'files')
            for row in metadata_languages(meta):
                entry = xbmcgui.ListItem(label=row['label'])
                entry.setProperty('StremioLanguageCode', row['code'])
                xbmcplugin.addDirectoryItem(HANDLE, '', entry, False)
        elif action == 'details_recommendations':
            xbmcplugin.setContent(HANDLE, 'tvshows' if kind == 'series' else 'movies')
            for row in metadata_recommendations(meta, providers):
                xbmcplugin.addDirectoryItem(
                    HANDLE, route(action='meta', home='1', kind=row.get('type', kind),
                                  id=row.get('id', '')), item(row), True)
        elif action == 'details_trailers':
            xbmcplugin.setContent(HANDLE, 'videos')
            from lib.trailer_options import imdb_id
            target = trailer_route(imdb_id(meta))
            if target:
                entry = xbmcgui.ListItem(label='Trailer')
                entry.setProperty('StremioTrailerURL', target)
                entry.setProperty('IsPlayable', 'true')
                xbmcplugin.addDirectoryItem(HANDLE, target, entry, False)
        elif action == 'next_episode':
            xbmcplugin.setContent(HANDLE, 'episodes')
            saved = next((row for row in state.get('library', [])
                          if isinstance(row, dict) and row.get('_id') == identity
                          and row.get('type') == 'series'), None)
            video, resume_ms = next_series_episode(meta.get('videos', []), identity, saved)
            if video:
                entry = episode_item(video, meta)
                target = route(action='streams', kind='series', id=video.get('id', ''))
                if resume_ms:
                    target = route(action='streams', kind='series', id=video.get('id', ''),
                                   resume_ms=str(resume_ms))
                    try:
                        tag = entry.getVideoInfoTag()
                        duration_ms = ((saved or {}).get('state') or {}).get('duration', 0)
                        tag.setResumePoint(
                            resume_seconds(resume_ms),
                            resume_seconds(duration_ms) if duration_ms else 0)
                    except Exception:
                        pass
                entry.setProperty('StremioNextEpisodePath', target)
                xbmcplugin.addDirectoryItem(HANDLE, target, entry, True)
        elif action in ('seasons', 'more_episodes'):
            xbmcplugin.setContent(HANDLE, 'seasons')
            season_rows = metadata_seasons(meta)
            if action == 'more_episodes':
                regular = [row for row in season_rows if int(row.get('season', 0)) > 0]
                if regular:
                    season_rows = regular
            for row in season_rows:
                season = row['season']
                entry = season_item(row, meta)
                xbmcplugin.addDirectoryItem(
                    HANDLE, route(action='episodes', kind='series',
                                  id=meta.get('id', ''), season=str(season)), entry, True)
        elif action in ('episodes', 'episodes_auto'):
            xbmcplugin.setContent(HANDLE, 'episodes')
            season = params.get('season', '0')
            if action == 'episodes_auto':
                available = metadata_seasons(meta)
                regular = [row for row in available if int(row.get('season', 0)) > 0]
                chosen = regular[0] if regular else (available[0] if available else {'season': 0})
                season = str(chosen.get('season', 0))
            for video in metadata_episodes(meta, season):
                entry = episode_item(video, meta)
                xbmcplugin.addDirectoryItem(
                    HANDLE, route(action='streams', kind='series',
                                  id=video.get('id', '')), entry, True)
        xbmcplugin.endOfDirectory(HANDLE)
        if action == 'more_episodes':
            xbmc.executebuiltin('Container.SetViewMode(527)')
        return

    provider = params.get('provider', '')
    home_context = params.get('home') == '1'
    manifest_url = HOME_MANIFEST if home_context else MANIFEST
    descriptor = None
    if provider:
        descriptor = next((entry for entry in active_addons(STORE.load())
                           if entry.get('id') == provider), None)
        if descriptor is None:
            raise AccountError('Addon no longer in local account collection. Refresh the list.')
        manifest_url = descriptor['transportUrl']
    base_url(manifest_url)

    def provider_route(**values):
        context = {}
        if provider:
            context['provider'] = provider
        if home_context:
            context['home'] = '1'
        context.update(values)
        return route(**context)

    if action == 'genres':
        kind = params.get('kind', 'movie')
        if kind not in ('movie', 'series'):
            kind = 'movie'
        manifest = fetch(HOME_MANIFEST)
        genre_rows = []
        seen = set()
        for catalog in manifest.get('catalogs', []):
            if not isinstance(catalog, dict) or catalog.get('type') != kind:
                continue
            catalog_id = catalog.get('id')
            if not catalog_id:
                continue
            for extra in catalog.get('extra', []):
                if not isinstance(extra, dict) or extra.get('name') != 'genre':
                    continue
                for genre in extra.get('options') or []:
                    genre = str(genre)
                    if not genre or genre.isdigit() or genre in seen:
                        continue
                    seen.add(genre)
                    genre_rows.append((genre, catalog_id))
            if genre_rows:
                break
        for genre, catalog_id in genre_rows:
            xbmcplugin.addDirectoryItem(
                HANDLE,
                route(action='home_catalog', kind=kind, id=catalog_id, genre=genre),
                xbmcgui.ListItem(label=genre),
                True)
    elif action == 'home_catalog':
        kind = params.get('kind', 'movie')
        catalog = params.get('id', 'top')
        extras = {}
        genre = params.get('genre', '')
        if catalog == 'year' and not genre:
            genre = str(datetime.now().year)
        if genre:
            extras['genre'] = genre
        xbmcplugin.setContent(HANDLE, 'tvshows' if kind == 'series' else 'movies')
        response = fetch(resource_url(HOME_MANIFEST, 'catalog', kind, catalog, extras or None))
        for meta in response.get('metas', []):
            if not meta.get('id'):
                continue
            xbmcplugin.addDirectoryItem(
                HANDLE,
                route(action='meta', home='1', kind=meta.get('type', kind), id=meta['id']),
                item(meta),
                True)
    elif action == 'search_results':
        query = params.get('query', '').strip()
        requested_kind = params.get('kind', '')
        kinds = (requested_kind,) if requested_kind in ('movie', 'series') else ('movie', 'series')
        xbmcplugin.setContent(HANDLE, 'videos')
        providers = list(active_addons(STORE.load()))
        for meta in metadata_search(query, providers, kinds):
            identity = meta.get('id')
            kind = meta.get('type') if meta.get('type') in ('movie', 'series') else requested_kind or 'movie'
            if not identity:
                continue
            xbmcplugin.addDirectoryItem(
                HANDLE,
                route(action='meta', home='1', kind=kind, id=identity),
                item(meta),
                True)
    elif action == 'widgets':
        for target, label in [('library', 'My Library'), ('continue', 'Continue Watching')]:
            xbmcplugin.addDirectoryItem(HANDLE, route(action=target), xbmcgui.ListItem(label=label), True)
        # Widget picker has no login/logout actions and excludes stream-only addons.
        xbmcplugin.addDirectoryItem(HANDLE, route(action='provider'),
                                   xbmcgui.ListItem(label='Manual catalog'), True)
        for addon in active_addons(STORE.load()):
            if not catalogs(addon['manifest']):
                continue
            label = addon['manifest'].get('name') or 'Stremio addon'
            xbmcplugin.addDirectoryItem(HANDLE, route(action='provider', provider=addon['id']),
                                       xbmcgui.ListItem(label=label), True)
    elif action == 'root':
        xbmcplugin.setContent(HANDLE, 'files')
        for target, label in (
                ('home', 'Home'), ('discover', 'Discover'),
                ('library', 'Library'), ('installed_addons', 'Addons')):
            entry = xbmcgui.ListItem(label=label)
            entry.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
            xbmcplugin.addDirectoryItem(HANDLE, route(action=target), entry, True)
    elif action == 'home':
        add_catalog_folders('home')
    elif action == 'discover':
        add_catalog_folders('discover')
    elif action == 'installed_addons':
        add_installed_addons()
    elif action == 'addon_action':
        from addons_ui import addon_actions
        addon_actions(xbmcgui.Dialog(), params.get('id', ''))
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        xbmc.executebuiltin('Container.Refresh')
        return
    elif action in ('library', 'continue'):
        from artwork import enrich
        xbmcplugin.setContent(HANDLE, 'videos')
        state = STORE.load()
        if action == 'library' and params.get('hub') == '1' and params.get('refresh') == '1':
            if not state.get('token'):
                raise AccountError('Connect to Stremio to open My Library.')
            try:
                state['library'] = pull_library(state['token'])
                STORE.save(state)
            except AccountError:
                xbmcgui.Dialog().notification('My Library', 'Offline — showing the last synced library')
        rows = library_rows(state.get('library', []), action == 'continue')
        # Home is bounded; keep the full Library browsable.
        if action == 'continue':
            rows = rows[:20]
        enriched = enrich(rows, state.get('addons', []), STORE.directory / 'artwork')
        if action == 'library' and params.get('hub') == '1':
            from library_filters import select_rows
            genres = sorted({g for r in enriched for g in (r.get('genres') or []) if isinstance(g, str)})
            xbmcgui.Window(10000).setProperty('LibraryGenres', json.dumps(genres))
            enriched = select_rows(enriched, params.get('kind', 'all'), params.get('sort', 'recent'), params.get('genre', ''))
        for meta in enriched:
            saved = meta
            entry = item(meta)
            progress = saved['state']
            video = progress.get('video_id')
            if action == 'continue' and (saved['type'] == 'movie' or video):
                target = route(action='streams', kind=saved['type'], id=video or saved['_id'],
                               resume_ms=str(int(resume_seconds(progress.get('timeOffset')) * 1000)))
                entry.setProperty('StremioContinuePath', target)
                entry.setProperty('StremioContinueLabel', button_label(saved))
                entry.setProperty('StremioResumeMilliseconds', str(progress.get('timeOffset', 0)))
                # The info dialog uses the item's folder for More episodes.
                # Keep that route at show level; Play has its own exact stream route.
                if saved['type'] == 'series':
                    target = route(action='meta', kind='series', id=saved['_id'])
            else:
                target = route(action='meta', kind=saved['type'], id=saved['_id'])
            # Series stay inside the Stremio for Kodi meta/season browser.
            xbmcplugin.addDirectoryItem(HANDLE, target, entry, True)
    elif action == 'provider':
        manifest = descriptor['manifest'] if descriptor else fetch(manifest_url)
        available = catalogs(manifest)
        if not available:
            xbmcgui.Dialog().ok('Stremio', 'This addon has no unfiltered catalogs. Its supported streams are requested when opening sources for a matching title.')
        for catalog in available:
            label = catalog.get('name', catalog['id']) + ' · ' + catalog['type']
            xbmcplugin.addDirectoryItem(HANDLE, provider_route(action='catalog', kind=catalog['type'],
                id=catalog['id']), xbmcgui.ListItem(label=label), True)
    elif action == 'catalog':
        kind = params['kind']
        xbmcplugin.setContent(HANDLE, 'tvshows' if kind == 'series' else 'movies')
        extras = {}
        genre = params.get('genre', '')
        if genre:
            extras['genre'] = genre
        response = fetch(resource_url(manifest_url, 'catalog', kind, params['id'], extras or None))
        for meta in response.get('metas', []):
            if not meta.get('id'):
                continue
            xbmcplugin.addDirectoryItem(HANDLE, provider_route(action='meta',
                kind=meta.get('type', kind), id=meta['id']), item(meta), True)
    elif action == 'meta':
        kind, identity = params['kind'], params['id']
        providers = list(active_addons(STORE.load()))
        if manifest_url and manifest_url not in {p.get('transportUrl') for p in providers}:
            try:
                providers.append({'transportUrl': manifest_url,
                                  'manifest': descriptor['manifest'] if descriptor else fetch(manifest_url)})
            except Exception:
                pass
        meta = metadata_details(kind, identity, '', providers)
        if kind == 'series' and meta.get('videos'):
            xbmcplugin.setContent(HANDLE, 'seasons')
            for row in metadata_seasons(meta):
                season = row['season']
                entry = season_item(row, meta)
                xbmcplugin.addDirectoryItem(
                    HANDLE,
                    route(action='episodes', kind='series',
                          id=identity, season=str(season)),
                    entry, True)
        else:
            xbmcplugin.addDirectoryItem(
                HANDLE, provider_route(action='streams', kind=kind, id=identity),
                item(meta), True)
    elif action == 'streams':
        providers = list(active_addons(STORE.load()))
        if not provider:
            try:
                providers.append({'transportUrl': manifest_url, 'manifest': fetch(manifest_url)})
            except Exception:
                pass  # Account providers can still work if the manual provider is down.

        kind, stream_id = params['kind'], params['id']
        selected_provider = params.get('stream_provider', 'all') or 'all'
        resume_ms = params.get('resume_ms', '')
        cache = Store(STORE.directory / 'streams')
        cached_state = cache.load()
        cache_valid = (
            cached_state.get('kind') == kind
            and cached_state.get('id') == stream_id
            and time.time() - cached_state.get('created', 0) < 300
            and isinstance(cached_state.get('raw'), list)
            and isinstance(cached_state.get('meta'), dict))

        if cache_valid:
            playable = cached_state['raw']
            play_meta = cached_state['meta']
            skipped = int(cached_state.get('skipped', 0))
            failed = int(cached_state.get('failed', 0))
        else:
            base_id = stream_id.split(':', 1)[0] if kind == 'series' else stream_id
            play_meta = metadata_details(kind, base_id, '', providers)
            if kind == 'series' and ':' in stream_id:
                episode = next((v for v in play_meta.get('videos', [])
                                if str(v.get('id', '')) == stream_id), None)
                if episode:
                    play_meta = dict(play_meta)
                    play_meta.update({
                        'id': stream_id,
                        'name': episode.get('name') or episode.get('title') or play_meta.get('name'),
                        'description': episode.get('description') or episode.get('overview') or '',
                        'released': episode.get('released') or episode.get('firstAired') or '',
                        'season': episode.get('season'),
                        'episode': episode.get('episode') or episode.get('number'),
                        'tvshowtitle': play_meta.get('name', ''),
                        '_media_type': 'episode',
                        'landscape': episode.get('thumbnail') or play_meta.get('landscape'),
                    })
            playable, skipped, failed = collect(providers, kind, stream_id)

        cache.save({
            'created': time.time(), 'kind': kind, 'id': stream_id,
            'raw': playable, 'meta': play_meta,
            'skipped': skipped, 'failed': failed,
            'urls': dict(cached_state.get('urls') or {}) if cache_valid else {}
        })

        configure_streams_window(
            play_meta, kind, stream_id, selected_provider, resume_ms)

        if not playable:
            xbmcgui.Dialog().ok('Stremio for Kodi',
                'No supported direct HTTP streams. {} unsupported; {} addons failed. '
                'Torrents, DRM and custom proxy headers are not supported yet.'.format(skipped, failed))
        elif skipped or failed:
            xbmcgui.Dialog().notification('Stremio for Kodi',
                '{} unsupported streams; {} addons failed'.format(skipped, failed))

        xbmcplugin.endOfDirectory(HANDLE)
        if playable:
            xbmc.executebuiltin('ActivateWindow(1200)')
        return
    elif action == 'play':
        cache = Store(STORE.directory / 'streams').load()
        stream = cache.get('urls', {}).get(params.get('key'), '')
        url = stream.get('url', '') if isinstance(stream, dict) else stream
        if time.time() - cache.get('created', 0) > 3600 or not direct_url({'url': url}):
            raise ValueError('Source expired; reopen the stream list')
        if isinstance(stream, dict) and isinstance(stream.get('meta'), dict):
            entry = item(stream['meta'])
            entry.setPath(url)
        else:
            entry = xbmcgui.ListItem(path=url)
        if isinstance(stream, dict) and resume_seconds(stream.get('resume_ms')):
            entry.setProperty('StartOffset', str(resume_seconds(stream['resume_ms'])))
        if isinstance(stream, dict):
            from subtitles import prepare_selected
            try:
                prepare_selected(STORE.directory, stream['kind'], stream['id'], stream,
                                 active_addons(STORE.load()), entry)
            except Exception:
                xbmcgui.Dialog().notification('Stremio subtitles', 'Subtitles unavailable; video will still start.')
        xbmcplugin.setResolvedUrl(HANDLE, True, entry)
        return
    else:
        raise ValueError('Unknown route')
    xbmcplugin.endOfDirectory(HANDLE)


if __name__ == '__main__':
    params = dict(parse_qsl(sys.argv[2].lstrip('?')))
    try:
        run(params)
    except AccountError as error:
        xbmcgui.Dialog().ok('Stremio account', str(error))
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
    except Exception:
        # Provider URLs can contain secrets: never log exceptions/URLs here.
        xbmcgui.Dialog().ok('Stremio for Kodi', 'Unable to load this addon response. Check the manifest setting and connection.')
        if params.get('action') in ('play', 'helper_play'):
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        else:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
