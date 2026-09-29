"""Optional MDbList ratings, independent of the active Kodi skin."""
from lib.ui_dialogs import dialog as themed_dialog
import re
from urllib.parse import urlencode

SOURCES = [('imdb', 'IMDb'), ('tmdb', 'TMDb'), ('trakt', 'Trakt'),
           ('tomatoes', 'Rotten Tomatoes'), ('metacritic', 'Metacritic'),
           ('letterboxd', 'Letterboxd'), ('tomatoesaudience', 'RT Audience'),
           ('metacriticuser', 'Metacritic User'), ('myanimelist', 'MyAnimeList'), ('mdblist', 'MDbList')]


def rating_text(payload, source):
    name, label = SOURCES[source] if 0 <= source < len(SOURCES) else SOURCES[0]
    for rating in payload.get('ratings') or []:
        if rating.get('source') == name and rating.get('value') is not None:
            return '{} {}'.format(label, rating['value'])
    return ''


def selected_text(payload, get_setting):
    return '  ·  '.join(text for index, (name, _) in enumerate(SOURCES)
                       if get_setting('rating_' + name) == 'true'
                       for text in [rating_text(payload, index)] if text)


def enabled():
    from addon_state import get_addon
    return bool(get_addon().getSetting('mdblist_api_key').strip())


def enrich(row):
    from addon_state import get_addon
    import xbmcvfs
    from pathlib import Path
    from protocol import fetch
    from lib.cache_policy import read_policy, open_cache
    addon = get_addon()
    key = addon.getSetting('mdblist_api_key').strip()
    identity = str(row.get('imdb_id') or row.get('id') or '')
    if not key or not re.fullmatch(r'tt\d+', identity) or row.get('type') not in ('movie', 'series'):
        return row
    kind = 'show' if row['type'] == 'series' else 'movie'
    url = 'https://api.mdblist.com/imdb/{}/{}/?{}'.format(kind, identity, urlencode({'apikey': key}))
    try:
        policy = read_policy(addon.getSetting)
        cache = open_cache('ratings', policy)
        payload = None
        if cache is not None:
            try:
                payload = cache.get(url)
            except Exception:
                pass
        if payload is None:
            payload = fetch(url, timeout=8)
            if cache is not None and payload.get('ratings'):
                try:
                    cache.put(url, payload, policy['ratings'])
                except Exception:
                    pass
        text = selected_text(payload, addon.getSetting)
        result = dict(row, rating_text=text, rating_badges=badges(payload, addon.getSetting))
        if payload.get('certification'):
            result['certification'] = payload['certification']
        if payload.get('released'):
            result['released'] = payload['released']
        return result
    except Exception:
        # Never log request URLs or exception text containing the API key.
        return row


def import_nimbus_key():
    from pathlib import Path
    import xml.etree.ElementTree as ET
    import xbmcgui
    import xbmcvfs
    from addon_state import get_addon
    addon = get_addon()
    if addon.getSetting('mdblist_api_key').strip():
        themed_dialog().ok('MDbList', 'An API key is already saved in this addon.')
        return
    try:
        path = Path(xbmcvfs.translatePath('special://profile/addon_data/skin.nimbus/settings.xml'))
        root = ET.parse(path).getroot()
        entry = root.find(".//setting[@id='mdblist_api_key']")
        key = (entry.text or '').strip() if entry is not None else ''
        if not key:
            raise ValueError()
        addon.setSetting('mdblist_api_key', key)
        themed_dialog().ok('MDbList', 'API key copied from Nimbus. Reopen the addon to apply.')
    except Exception:
        themed_dialog().ok('MDbList', 'No saved Nimbus API key found. Enter your key in addon settings.')


def badges(payload, get_setting):
    """Nimbus-compatible scales and rating icons."""
    result = []
    icons = {'imdb':'imdb','tmdb':'tmdb','trakt':'trakt','letterboxd':'letterboxd',
             'metacritic':'metacritic','metacriticuser':'metacritic','myanimelist':''}
    for name, label in SOURCES:
        if get_setting('rating_' + name) != 'true':
            continue
        entry = ({'value': payload.get('score')} if name == 'mdblist' else
                 next((r for r in payload.get('ratings', []) if r.get('source') == name), {}))
        try:
            value = float(entry['value'])
        except (KeyError, TypeError, ValueError):
            continue
        icon = icons.get(name, 'mdblist')
        if name in ('tmdb', 'trakt'): value /= 10
        if name == 'letterboxd': value *= 2
        text = '{:g}'.format(value)
        if name in ('tomatoes','tomatoesaudience','metacritic','mdblist'):
            text += '%'
        if name == 'tomatoes': icon = 'rtfresh' if value >= 60 else 'rtrotten'
        if name == 'tomatoesaudience': icon = 'popcorn' if value >= 60 else 'popcorn_spilt'
        result.append({'source':name,'value':text,'icon':icon+'.png' if icon else '', 'label':'MAL' if name == 'myanimelist' else ''})
    return result
