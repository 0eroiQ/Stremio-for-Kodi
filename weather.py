"""Built-in Stremio for Kodi weather provider using Open-Meteo.

Part of the Stremio for Kodi SYSTEM runtime. No Kodi weather addon or API key.
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

GEOCODE='https://geocoding-api.open-meteo.com/v1/search'
FORECAST='https://api.open-meteo.com/v1/forecast'
ALLOWED={'geocoding-api.open-meteo.com','api.open-meteo.com'}
GEONAMES_AU = Path(__file__).resolve().parent / 'resources' / 'geonames' / 'AU.txt'
COUNTRY_CODES = {
    'australia': 'AU',
    'new zealand': 'NZ',
    'usa': 'US',
    'united states': 'US',
    'united kingdom': 'GB',
    'canada': 'CA',
    'ireland': 'IE',
    'germany': 'DE',
    'france': 'FR',
    'italy': 'IT',
    'spain': 'ES',
    'netherlands': 'NL',
    'switzerland': 'CH',
    'austria': 'AT',
    'croatia': 'HR',
    'bosnia and herzegovina': 'BA',
    'serbia': 'RS',
    'montenegro': 'ME',
    'north macedonia': 'MK',
    'slovenia': 'SI',
}
WMO={
0:('Clear sky','32'),1:('Mainly clear','34'),2:('Partly cloudy','30'),3:('Overcast','26'),
45:('Fog','20'),48:('Rime fog','20'),51:('Light drizzle','9'),53:('Drizzle','9'),55:('Heavy drizzle','9'),
56:('Freezing drizzle','10'),57:('Heavy freezing drizzle','10'),61:('Light rain','11'),63:('Rain','12'),
65:('Heavy rain','12'),66:('Freezing rain','10'),67:('Heavy freezing rain','10'),71:('Light snow','13'),
73:('Snow','14'),75:('Heavy snow','16'),77:('Snow grains','13'),80:('Rain showers','11'),81:('Rain showers','12'),
82:('Heavy rain showers','12'),85:('Snow showers','14'),86:('Heavy snow showers','16'),95:('Thunderstorm','4'),
96:('Thunderstorm with hail','3'),99:('Severe thunderstorm with hail','3')}

def fetch_json(url,timeout=12):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in ALLOWED or p.username or p.password:
        raise ValueError('Unsupported weather endpoint')
    with urlopen(Request(url,headers={'Accept':'application/json','User-Agent':'Stremio for Kodi-weather/1'}),timeout=timeout) as r:
        data=r.read(2*1024*1024+1)
    if len(data)>2*1024*1024: raise ValueError('Weather response too large')
    out=json.loads(data)
    if not isinstance(out,dict): raise ValueError('Invalid weather response')
    return out

def normalize_country(region):
    """Return a plain country name from Kodi region labels such as Australia (24h)."""
    if not isinstance(region, str):
        return ''
    return re.sub(r'\s*\([^)]*\)\s*$', '', region).strip()


def country_code(region):
    return COUNTRY_CODES.get(normalize_country(region).casefold(), '')


def _au_postcode_search(postcode, path=GEONAMES_AU):
    """Resolve Australian postcodes from the bundled GeoNames postal dataset."""
    if not re.fullmatch(r'\d{4}', str(postcode or '').strip()):
        return []
    target = str(postcode).strip()
    rows = []
    try:
        with Path(path).open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                parts = line.rstrip('\n').split('\t')
                if len(parts) < 11 or parts[0] != 'AU' or parts[1] != target:
                    continue
                try:
                    lat, lon = float(parts[9]), float(parts[10])
                except (TypeError, ValueError):
                    continue
                place = parts[2].strip()
                admin1 = parts[3].strip()
                label = ', '.join(v for v in (place + ' ' + target, admin1, 'Australia') if v)
                rows.append({
                    'label': label,
                    'latitude': lat,
                    'longitude': lon,
                    'country_code': 'AU',
                    'postcode': target,
                    'place': place,
                })
    except OSError:
        return []

    # Put normal locality names before delivery-centre/GPO records and de-duplicate labels.
    def rank(row):
        name = row.get('place', '').casefold()
        service = any(token in name for token in ('delivery centre', ' gpo', 'boxes', 'bc '))
        return (1 if service else 0, len(name), name)

    output, seen = [], set()
    for row in sorted(rows, key=rank):
        key = row['label'].casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
        if len(output) >= 8:
            break
    return output


def search(query, country='', fetcher=fetch_json, postcode_path=GEONAMES_AU):
    if not isinstance(query,str) or not query.strip():
        return []
    query = query.strip()
    country_name = normalize_country(country)
    code = country_code(country_name)

    if code == 'AU' and re.fullmatch(r'\d{4}', query):
        rows = _au_postcode_search(query, postcode_path)
        if rows:
            return rows

    params = {'name': query, 'count': 8, 'language': 'en', 'format': 'json'}
    if code:
        params['countryCode'] = code
    elif country_name:
        params['name'] = query + ', ' + country_name
    data=fetcher(GEOCODE+'?'+urlencode(params))
    rows=[]
    for item in data.get('results') or []:
        lat,lon=item.get('latitude'),item.get('longitude')
        if not isinstance(lat,(int,float)) or not isinstance(lon,(int,float)):
            continue
        if code and str(item.get('country_code','')).upper() not in ('', code):
            continue
        label=', '.join(str(v) for v in (item.get('name'),item.get('admin1'),item.get('country')) if v)
        rows.append({'label':label or query,'latitude':float(lat),'longitude':float(lon),
                     'country_code':str(item.get('country_code','')).upper()})
    return rows

def forecast(latitude,longitude,fetcher=fetch_json):
    lat,lon=float(latitude),float(longitude)
    if not -90<=lat<=90 or not -180<=lon<=180: raise ValueError('Invalid coordinates')
    params={
      'latitude':lat,'longitude':lon,'timezone':'auto','forecast_days':7,
      'current':'temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m',
      'hourly':'temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,precipitation,weather_code,wind_speed_10m,wind_direction_10m',
      'daily':'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset,wind_speed_10m_max,wind_direction_10m_dominant'}
    return fetcher(FORECAST+'?'+urlencode(params))

def condition(code):
    try: return WMO.get(int(code),('Unknown','na'))
    except (TypeError,ValueError): return ('Unknown','na')

def wind_direction(value):
    try: deg=float(value)%360
    except (TypeError,ValueError): return ''
    names=('N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW')
    return names[int((deg+11.25)//22.5)%16]

def number(value,fallback=''):
    return str(int(round(value))) if isinstance(value,(int,float)) else fallback

def _set(window,key,value):
    window.setProperty(key,'' if value is None else str(value))

def apply(payload,location,window=None):
    if window is None:
        import xbmcgui
        window=xbmcgui.Window(12600)
    cur=payload.get('current') or {}; daily=payload.get('daily') or {}; hourly=payload.get('hourly') or {}
    label,art=condition(cur.get('weather_code'))
    for k,v in {
      'Location':location,'WeatherProvider':'Open-Meteo','Updated':cur.get('time',''),
      'Current.Condition':label,'Current.Temperature':number(cur.get('temperature_2m')),
      'Current.FeelsLike':number(cur.get('apparent_temperature')),'Current.Humidity':number(cur.get('relative_humidity_2m')),
      'Current.Precipitation':cur.get('precipitation',''),'Current.Wind':number(cur.get('wind_speed_10m')),
      'Current.WindDirection':wind_direction(cur.get('wind_direction_10m')),'Current.OutlookIcon':art+'.png',
      'Current.FanartCode':art}.items(): _set(window,k,v)
    dates=daily.get('time') or []; codes=daily.get('weather_code') or []; highs=daily.get('temperature_2m_max') or []
    lows=daily.get('temperature_2m_min') or []; rain=daily.get('precipitation_probability_max') or []
    winds=daily.get('wind_speed_10m_max') or []; dirs=daily.get('wind_direction_10m_dominant') or []
    rises=daily.get('sunrise') or []; sets=daily.get('sunset') or []
    for i in range(7):
        if i>=len(dates): break
        try:
            d=datetime.fromisoformat(dates[i]); longday=d.strftime('%A'); short=d.strftime('%d %b')
        except Exception:
            longday=short=dates[i]
        outlook,fan=condition(codes[i] if i<len(codes) else None); n=i+1
        vals={
          f'Day{i}.Title':longday,f'Day{i}.HighTemp':number(highs[i] if i<len(highs) else None),
          f'Day{i}.LowTemp':number(lows[i] if i<len(lows) else None),f'Day{i}.Outlook':outlook,f'Day{i}.FanartCode':fan,
          f'Daily.{n}.LongDay':longday,f'Daily.{n}.ShortDate':short,
          f'Daily.{n}.HighTemperature':number(highs[i] if i<len(highs) else None),
          f'Daily.{n}.LowTemperature':number(lows[i] if i<len(lows) else None),f'Daily.{n}.Outlook':outlook,
          f'Daily.{n}.Precipitation':number(rain[i] if i<len(rain) else None),
          f'Daily.{n}.WindSpeed':number(winds[i] if i<len(winds) else None),
          f'Daily.{n}.WindDirection':wind_direction(dirs[i] if i<len(dirs) else None),f'Daily.{n}.FanartCode':fan}
        for k,v in vals.items(): _set(window,k,v)
    _set(window,'Daily.IsFetched','true' if dates else '')
    if rises: _set(window,'Today.Sunrise',rises[0].split('T')[-1])
    if sets: _set(window,'Today.Sunset',sets[0].split('T')[-1])
    times=hourly.get('time') or []; now=cur.get('time','')
    start=next((i for i,t in enumerate(times) if t>=now),0) if now and times else 0
    arrays={'Temperature':hourly.get('temperature_2m') or [],'FeelsLike':hourly.get('apparent_temperature') or [],
      'Humidity':hourly.get('relative_humidity_2m') or [],'ChancePrecipitation':hourly.get('precipitation_probability') or [],
      'Precipitation':hourly.get('precipitation') or [],'WindSpeed':hourly.get('wind_speed_10m') or [],
      'WindDirection':hourly.get('wind_direction_10m') or [],'Code':hourly.get('weather_code') or []}
    count=min(24,max(0,len(times)-start))
    for slot in range(1,count+1):
        idx=start+slot-1; outlook,fan=condition(arrays['Code'][idx] if idx<len(arrays['Code']) else None)
        vals={f'Hourly.{slot}.Time':times[idx].split('T')[-1],
          f'Hourly.{slot}.Temperature':number(arrays['Temperature'][idx] if idx<len(arrays['Temperature']) else None),
          f'Hourly.{slot}.FeelsLike':number(arrays['FeelsLike'][idx] if idx<len(arrays['FeelsLike']) else None),
          f'Hourly.{slot}.Humidity':number(arrays['Humidity'][idx] if idx<len(arrays['Humidity']) else None),
          f'Hourly.{slot}.ChancePrecipitation':number(arrays['ChancePrecipitation'][idx] if idx<len(arrays['ChancePrecipitation']) else None),
          f'Hourly.{slot}.Precipitation':arrays['Precipitation'][idx] if idx<len(arrays['Precipitation']) else '',
          f'Hourly.{slot}.WindSpeed':number(arrays['WindSpeed'][idx] if idx<len(arrays['WindSpeed']) else None),
          f'Hourly.{slot}.WindDirection':wind_direction(arrays['WindDirection'][idx] if idx<len(arrays['WindDirection']) else None),
          f'Hourly.{slot}.Outlook':outlook,f'Hourly.{slot}.FanartCode':fan}
        for k,v in vals.items(): _set(window,k,v)
    _set(window,'Hourly.IsFetched','true' if count else '')
    return window

def refresh(force=False):
    import xbmcgui
    from addon_state import get_addon
    addon=get_addon(); window=xbmcgui.Window(12600)
    try: last=float(window.getProperty('Stremio.LastRefreshEpoch') or 0)
    except ValueError: last=0
    if not force and time.time()-last < 900 and window.getProperty('Current.Condition'):
        return
    loc=addon.getSetting('weather_location').strip(); lat=addon.getSetting('weather_lat').strip(); lon=addon.getSetting('weather_lon').strip()
    if not loc or not lat or not lon:
        _set(window,'Current.Condition','Set a location in Weather settings'); _set(window,'Daily.IsFetched',''); _set(window,'Hourly.IsFetched',''); return
    try:
        payload = forecast(float(lat),float(lon))
        apply(payload,loc,window)
        _set(window,'Stremio.LastRefreshEpoch',time.time())
        return payload
    except Exception:
        _set(window,'Current.Condition','Weather unavailable')
        xbmcgui.Dialog().notification('Weather','Unable to refresh weather. Check the network connection.')

if __name__=='__main__': refresh()
