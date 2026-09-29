"""Program-window adapter to the existing Stremio for Kodi backend.

No video-plugin navigation and no global skin settings are used here.
"""
import sys
import time
import uuid
from urllib.parse import urlencode

import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcvfs

CORE = get_addon()
CORE_PATH = xbmcvfs.translatePath(CORE.getAddonInfo('path'))
if CORE_PATH not in sys.path:
    sys.path.append(CORE_PATH)

from account import Store, library_rows
from addons_core import active_addons
from metadata_bridge import details, people, seasons, episodes, recommendations, search, trailer_rows
from protocol import fetch, resource_url
from sources import collect
from continue_playback import next_series_episode, resume_seconds
from stream_ui import stream_card
from library_actions import member, change

STORE = Store(xbmcvfs.translatePath(CORE.getAddonInfo('profile')))
HOME = 'https://v3-cinemeta.strem.io/manifest.json'


def providers():
    return list(active_addons(STORE.load()))


def catalog(kind, genre=''):
    payload = fetch(resource_url(HOME, 'catalog', kind, 'top', {'genre': genre} if genre else None))
    return [r for r in payload.get('metas', []) if isinstance(r, dict) and r.get('id')][:40]


def metadata(row):
    result = dict(row)
    full = details(row['type'], row['id'], providers=providers())
    result.update({k: v for k, v in full.items() if v not in ('', None, [], {})})
    return result


def library():
    return [dict(r, id=r.get('_id') or r.get('id')) for r in library_rows(STORE.load().get('library', []))]


def saved(meta):
    return next((r for r in STORE.load().get('library', [])
                 if r.get('_id') == meta['id'] and r.get('type') == meta['type']), {})


def in_library(meta):
    return member(STORE.load().get('library', []), meta['id'], meta['type'])


def toggle_library(meta):
    state = STORE.load()
    if not state.get('token'):
        raise ValueError('Connect your Stremio account in Settings first.')
    state['library'] = change(state['token'], meta['id'], meta['type'],
                              meta.get('name', ''), meta.get('poster', ''), not in_library(meta))
    STORE.save(state)


def mark_episodes_through(meta, target_id, watched=True):
    from episode_actions import sync_through
    remote, selected = sync_through(STORE, meta, target_id, watched)
    return remote, selected


def mark_episode(meta, target_id, watched=True):
    from episode_actions import sync_single
    remote, selected = sync_single(STORE, meta, target_id, watched)
    return remote, selected


def mark_movie(meta, watched=True):
    from media_actions import sync_movie_watched
    return sync_movie_watched(STORE, meta, watched)


def remove_continue(meta):
    from media_actions import sync_remove_continue
    return sync_remove_continue(STORE, meta)


def languages(meta):
    raw = (meta.get('languages') or meta.get('spokenLanguages') or
           meta.get('audioLanguages') or meta.get('language') or [])
    if isinstance(raw, (str, dict)):
        raw = [raw]
    rows = []
    for value in raw if isinstance(raw, list) else []:
        if isinstance(value, dict):
            code = value.get('iso_639_1') or value.get('code') or ''
            name = value.get('english_name') or value.get('name') or code
        else:
            name = str(value).strip()
            code = name if len(name) in (2, 3) else ''
        if code:
            name = xbmc.convertLanguage(str(code), xbmc.ENGLISH_NAME) or name
        row = {'name': str(name), 'code': str(code).upper() or str(name)[:2].upper()}
        if name and row not in rows:
            rows.append(row)
    return rows


def source_rows(meta, identity):
    rows, skipped, failed = collect(providers(), meta['type'], identity)
    for row in rows:
        row['card'] = stream_card(row)
    return rows, skipped, failed


def play(meta, identity, stream, resume_ms=0):
    # Reuse the core resolver, subtitles and playback observer rather than
    # introducing a second playback implementation in the program addon.
    key = uuid.uuid4().hex
    state = Store(STORE.directory / 'streams')
    cache = state.load()
    cache.update(created=time.time())
    urls = dict(cache.get('urls') or {})
    urls[key] = dict(stream, meta=meta, kind=meta['type'], id=identity, resume_ms=resume_ms)
    cache['urls'] = urls
    state.save(cache)
    url = 'plugin://script.stremioelec/?' + urlencode({'action': 'play', 'key': key})
    xbmc.executebuiltin('PlayMedia(' + url + ')')


def _continue_rows(state, catalogs=(), allow_network=False):
    continuing = [dict(row, id=row.get('_id') or row.get('id'))
                  for row in library_rows(state.get('library', []), True)]
    if not continuing:
        return None

    # Fast startup stays network-free and trusts Stremio's saved pointer. During
    # the background refresh we can verify series episode state against current
    # metadata so a watched/future/final episode never remains in Continue Watching.
    if allow_network:
        from continue_playback import continue_series_target
        verified = []
        for row in continuing:
            if row.get('type') != 'series':
                verified.append(row)
                continue
            try:
                full = metadata(row)
                target, resume_ms = continue_series_target(full.get('videos') or [], row)
            except Exception:
                # A metadata outage must not destructively remove a valid saved
                # Continue Watching item. Keep it until a later refresh can verify.
                verified.append(row)
                continue
            if target is None:
                continue
            projected = dict(row)
            projected.update({key: value for key, value in full.items()
                              if value not in ('', None, [], {})})
            projected['id'] = row.get('_id') or row.get('id')
            projected['state'] = dict(row.get('state') or {})
            projected['state']['video_id'] = str(target.get('id') or '')
            projected['state']['timeOffset'] = int(resume_ms) if resume_ms else 1
            verified.append(projected)
        continuing = verified

    if continuing:
        from lib.hero_metadata import prepare
        continuing = prepare(continuing, catalogs, metadata if allow_network else None)
        return {'label': 'Continue Watching', 'items': continuing, 'failed': False}
    return None


def account_home_capacity():
    """Number of Home controls needed from saved manifests; no network access."""
    from lib.home_catalogs import descriptors
    state = STORE.load()
    remote = [a for a in state.get('addons', []) if a.get('account') is True]
    return len(descriptors(remote)) + (1 if library_rows(state.get('library', []), True) else 0)


def account_home(refresh=True):
    """Return Home without blocking startup when refresh=False.

    Fast mode uses the last display-only snapshot plus the locally saved Stremio
    library. Refresh mode performs account/catalog network work and replaces the
    snapshot only after the UI is already available.
    """
    from lib.home_snapshot import load as load_snapshot, save as save_snapshot
    state = STORE.load()
    if not state.get('token'):
        return []

    if not refresh:
        rows = load_snapshot(STORE.directory)
        continuing = _continue_rows(state, rows, False)
        return ([continuing] if continuing else []) + rows

    from account import pull_addons, pull_library
    from addons_core import merge_account
    from lib.home_catalogs import load_rows

    # Account addon order may change on another Stremio device. Failure here is
    # non-fatal: the last saved account collection remains usable.
    try:
        remote, _ = pull_addons(state['token'])
        state['addons'] = merge_account(state, remote)
        STORE.save(state)
    except Exception:
        xbmc.log('Stremio for Kodi: using saved account catalog order; sync unavailable', xbmc.LOGWARNING)

    remote = [a for a in state.get('addons', []) if a.get('account') is True]
    catalog_rows = load_rows(remote, fetch, resource_url)
    catalog_rows = save_snapshot(STORE.directory, catalog_rows)

    try:
        state['library'] = pull_library(state['token'])
        STORE.save(state)
    except Exception:
        pass

    continuing = _continue_rows(state, catalog_rows, True)
    return ([continuing] if continuing else []) + catalog_rows


def discover_choices():
    from lib.browse import discover_catalogs
    return discover_catalogs(STORE.load().get('addons', []))


def discover_items(catalog, extras=None):
    values = dict(catalog['defaults'])
    values.update(extras or {})
    data = fetch(resource_url(catalog['url'], 'catalog', catalog['kind'], catalog['id'], values))
    return [dict(row, type=row.get('type') or catalog['kind']) for row in data.get('metas', [])
            if isinstance(row, dict) and row.get('id')][:100]


def account_library(refresh=True):
    from account import pull_library
    state = STORE.load()
    if refresh and state.get('token'):
        state['library'] = pull_library(state['token'])
        STORE.save(state)
    return state.get('library', [])
