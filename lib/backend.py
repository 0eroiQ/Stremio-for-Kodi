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
