"""Optional MDbList ratings, independent of the active Kodi skin."""
import re
from urllib.parse import urlencode

SOURCES = [('imdb', 'IMDb'), ('tmdb', 'TMDb'), ('trakt', 'Trakt'),
           ('tomatoes', 'Rotten Tomatoes'), ('metacritic', 'Metacritic'),
           ('letterboxd', 'Letterboxd')]


def rating_text(payload, source):
    name, label = SOURCES[source] if 0 <= source < len(SOURCES) else SOURCES[0]
    for rating in payload.get('ratings') or []:
        if rating.get('source') == name and rating.get('value') is not None:
            return '{} {}'.format(label, rating['value'])
    return ''


def enabled():
    from addon_state import get_addon
    return bool(get_addon().getSetting('mdblist_api_key').strip())


def enrich(row):
    from addon_state import get_addon
    import xbmcvfs
    from pathlib import Path
    from protocol import fetch
    from lib.disk_cache import DiskCache
    addon = get_addon()
    key = addon.getSetting('mdblist_api_key').strip()
    identity = str(row.get('imdb_id') or row.get('id') or '')
    if not key or not re.fullmatch(r'tt\d+', identity) or row.get('type') not in ('movie', 'series'):
        return row
    kind = 'show' if row['type'] == 'series' else 'movie'
    url = 'https://api.mdblist.com/imdb/{}/{}/?{}'.format(kind, identity, urlencode({'apikey': key}))
    try:
        cache = DiskCache(Path(xbmcvfs.translatePath(addon.getAddonInfo('profile'))) / 'cache')
        payload = cache.get(url)
        if payload is None:
            payload = fetch(url, timeout=8)
            if payload.get('ratings'):
                cache.put(url, payload, 86400)
        text = rating_text(payload, int(addon.getSetting('mdblist_rating_source') or 0))
        return dict(row, rating_text=text) if text else row
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
        xbmcgui.Dialog().ok('MDbList', 'An API key is already saved in this addon.')
        return
    try:
        path = Path(xbmcvfs.translatePath('special://profile/addon_data/skin.nimbus/settings.xml'))
        root = ET.parse(path).getroot()
        entry = root.find(".//setting[@id='mdblist_api_key']")
        key = (entry.text or '').strip() if entry is not None else ''
        if not key:
            raise ValueError()
        addon.setSetting('mdblist_api_key', key)
        xbmcgui.Dialog().ok('MDbList', 'API key copied from Nimbus. Reopen the addon to apply.')
    except Exception:
        xbmcgui.Dialog().ok('MDbList', 'No saved Nimbus API key found. Enter your key in addon settings.')
