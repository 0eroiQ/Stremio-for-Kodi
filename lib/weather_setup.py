"""Country-scoped weather setup. No IP location, account data or global changes."""
from lib.ui_dialogs import progress_bg as themed_progress_bg, dialog as themed_dialog
import json
import math
from pathlib import Path
import re
from functools import lru_cache

DATA = Path(__file__).resolve().parents[1] / 'resources/geonames/countries.json'

@lru_cache(maxsize=1)
def countries():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    rows = data['countries']
    assert data['schemaVersion'] == 1 and isinstance(rows, list)
    result = {r['code']: r['name'] for r in rows
              if re.fullmatch(r'[A-Z]{2}', r.get('code', ''))
              and isinstance(r.get('name'), str) and r['name'].strip()}
    return tuple(sorted(result.items(), key=lambda row: row[1].casefold()))

def resolve_country(value):
    value = str(value or '').strip()
    rows = dict(countries())
    if value.upper() in rows:
        return value.upper()
    return next((code for code, name in rows.items() if name.casefold() == value.casefold()), '')

def postcode(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 -]{0,15}', value.strip()):
        raise ValueError('Enter a postal code using letters, numbers, spaces or hyphens.')
    return value.strip().upper()

def choose_country(dialog, current=''):
    rows = countries()
    index = next((i for i, row in enumerate(rows) if row[0] == current), -1)
    selected = dialog.select('Choose country / territory',
        ['{} ({})'.format(name, code) for code, name in rows], preselect=index)
    return rows[selected][0] if type(selected) is int and 0 <= selected < len(rows) else ''

def save_place(addon, country, query, place, postal=True):
    if country not in dict(countries()) or place.get('country_code') != country:
        raise ValueError('The selected place does not match the selected country.')
    lat, lon = place.get('latitude'), place.get('longitude')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon)):
        raise ValueError('The selected place has invalid coordinates.')
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not place.get('label'):
        raise ValueError('The selected place has invalid coordinates or name.')
    values = {'weather_country_code': country, 'weather_country_name': dict(countries())[country],
              'weather_postcode': postcode(query) if postal else '',
              'weather_lat': str(lat), 'weather_lon': str(lon), 'weather_location': place['label']}
    old = {key: addon.getSetting(key) for key in values}
    try:
        for key, value in values.items():
            if addon.setSetting(key, value) is False:
                raise ValueError('Location settings could not be saved.')
    except Exception:
        for key, value in old.items():
            try:
                addon.setSetting(key, value)
            except Exception:
                pass
        raise

def _lookup(query, country, postal, fetcher):
    from weather import search, fetch_json
    progress = None
    try:
        import xbmcgui
        progress = themed_progress_bg()
        progress.create('Weather', 'Finding places in ' + dict(countries())[country] + '...')
    except ImportError:
        pass
    try:
        return search(query, country, fetcher=fetcher or fetch_json, postal=postal)
    finally:
        if progress is not None:
            progress.close()

def configure_weather(action='menu', dialog=None, addon=None, fetcher=None):
    if dialog is None:
        import xbmcgui
        dialog = themed_dialog()
    if addon is None:
        from addon_state import get_addon
        addon = get_addon()
    names = dict(countries())
    code = resolve_country(addon.getSetting('weather_country_code') or addon.getSetting('weather_country_name'))
    saved_zip = addon.getSetting('weather_postcode') or ''
    saved_place = addon.getSetting('weather_location') or ''
    choice = {'country': 0, 'postcode': 1, 'city': 3}.get(action)
    while True:
        if choice is None:
            choice = dialog.select('Weather - country and location', [
                'Country: ' + names.get(code, 'Choose country'),
                'ZIP / postal code: ' + (saved_zip or 'Enter code'),
                'Selected place: ' + (saved_place or 'Not selected'),
                'Search by city / suburb instead', 'Done'])
        if type(choice) is not int or choice < 0 or choice >= 4:
            return False
        if choice == 0:
            new_code = choose_country(dialog, code)
            if not new_code:
                return False
            if code != new_code:
                saved_zip, saved_place = '', ''
            code, choice = new_code, 1
        if not code:
            code = choose_country(dialog)
            if not code:
                return False
        postal = choice != 3
        choice = None
        heading = ('ZIP / postal code' if postal else 'City / suburb') + ' - ' + names[code]
        query = dialog.input(heading, defaultt=saved_zip if postal else '')
        if not query or not query.strip():
            return False
        try:
            query = postcode(query) if postal else query.strip()
            if len(query) > 100 or any(ord(c) < 32 for c in query):
                raise ValueError('Enter a short place name.')
        except ValueError as error:
            dialog.ok('Check location', str(error))
            continue
        try:
            rows = _lookup(query, code, postal, fetcher)
        except Exception:
            dialog.ok('Weather location', 'Location search is unavailable. Check your connection and try again. Your saved location was not changed.')
            continue
        if not rows:
            dialog.ok('No matching places in ' + names[code],
                'No places were found for that code or name in the selected country. Check the country and code, or use Search by city / suburb instead.')
            continue
        selected = dialog.select('Choose place - ' + names[code], [r['label'] for r in rows])
        if type(selected) is not int or not 0 <= selected < len(rows):
            return False
        try:
            save_place(addon, code, query, rows[selected], postal)
        except Exception:
            dialog.ok('Weather location', 'The selected location could not be saved. Please reopen settings and try again.')
            return False
        try:
            import xbmcgui
            window = xbmcgui.Window(12600)
            window.clearProperty('Stremio.LastRefreshEpoch')
            window.clearProperty('Daily.IsFetched')
            window.clearProperty('Hourly.IsFetched')
        except Exception:
            pass
        dialog.notification('Weather location saved', rows[selected]['label'], time=5000)
        return True

def search_places(query, code, fetcher, postal=False, au_search=None):
    from urllib.parse import urlencode
    if not isinstance(query, str) or not query.strip():
        return []
    query = query.strip()
    names = dict(countries())
    if code and code not in names:
        raise ValueError('Select a valid country.')
    if postal:
        query = postcode(query)
    if code == 'AU' and re.fullmatch(r'\d{4}', query) and au_search:
        local = au_search(query)
        if local:
            return local
    params = {'name': query, 'count': 100, 'language': 'en', 'format': 'json'}
    if code:
        params['countryCode'] = code
    endpoint = 'https://geocoding-api.open-meteo.com/v1/search'
    data = fetcher(endpoint + '?' + urlencode(params))
    if not isinstance(data, dict) or data.get('error'):
        raise ValueError('Location search unavailable.')
    results = data.get('results') or []
    if not isinstance(results, list):
        raise ValueError('Invalid location response.')
    rows, seen = [], set()
    compact = lambda value: re.sub(r'[\s-]', '', str(value)).upper()
    for value in results[:100]:
        if not isinstance(value, dict):
            continue
        item_code = str(value.get('country_code') or '').upper()
        # Fail closed: never show unverified-country or other-country matches.
        if code and item_code != code:
            continue
        lat, lon = value.get('latitude'), value.get('longitude')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon)):
            continue
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            continue
        codes = value.get('postcodes')
        if postal and isinstance(codes, list) and codes and compact(query) not in {compact(c) for c in codes}:
            continue
        name = str(value.get('name') or '').strip()
        if not name:
            continue
        parts = [name + (' ' + query if postal else ''), value.get('admin1'), names.get(item_code, value.get('country', ''))]
        label = ', '.join(str(part) for part in parts if part)
        key = (label.casefold(), round(lat, 5), round(lon, 5))
        if key in seen:
            continue
        seen.add(key)
        rows.append({'label': label, 'latitude': float(lat), 'longitude': float(lon),
                     'country_code': item_code, 'place': name, 'postcode': query if postal else ''})
    return rows
