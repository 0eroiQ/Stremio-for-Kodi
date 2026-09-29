"""Coloured sidebar weather; no fake conditions and no blocking Home requests."""
import math
import time
from lib.weather_units import addon_temperature_unit

MEDIA = 'special://home/addons/script.stremioelec/resources/skins/Main/media/weather-coloured/'
REFRESH_SCRIPT = 'special://home/addons/script.stremioelec/weather_refresh.py'
READY = 'Stremio.WeatherReady'
ICON = 'Stremio.CurrentIcon'
TEMPERATURE = 'Stremio.CurrentTemperature'
REQUESTED = 'Stremio.WeatherRequested'


def colour_icon(code, is_day=1):
    from weather import condition
    _, art = condition(code)
    if is_day == 0:
        art = {'32': '31', '34': '33', '30': '29'}.get(art, art)
    return MEDIA + art + '.png' if art != 'na' else ''


def temperature(value, unit='°C'):
    if type(value) not in (int, float) or not math.isfinite(value):
        return ''
    fahrenheit = 'f' in str(unit).lower()
    value = value * 9 / 5 + 32 if fahrenheit else value
    return '{}°{}'.format(int(round(value)), 'F' if fahrenheit else 'C')


def request_refresh(force=False, kodi=None, gui=None, now=None):
    """Schedule a short-lived Kodi script, never a network call on the UI thread."""
    try:
        if kodi is None:
            import xbmc as kodi
        if gui is None:
            import xbmcgui as gui
        window = gui.Window(12600)
        now = time.time() if now is None else now
        last_request = float(window.getProperty(REQUESTED) or 0)
        last_update = float(window.getProperty('Stremio.LastRefreshEpoch') or 0)
        if not force and 0 <= now - last_request < 30:
            return False
        same_unit = window.getProperty('Stremio.TemperatureUnit') == addon_temperature_unit()
        if not force and same_unit and window.getProperty(READY) == 'true' and 0 <= now - last_update < 900:
            return False
        window.setProperty(REQUESTED, str(now))
        kodi.executebuiltin('RunScript(' + REFRESH_SCRIPT + (',force)' if force else ')'))
        return True
    except Exception:
        return False
