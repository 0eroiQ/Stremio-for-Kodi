"""Addon weather units follow the saved weather country, never Kodi's region.

Temperature preferences: Unicode CLDR units.xml, temperature/weather preferences.
https://github.com/unicode-org/cldr/blob/main/common/supplemental/units.xml
Open-Meteo data stays in Celsius; display values are converted exactly once.
"""
FAHRENHEIT_COUNTRIES = frozenset(('US', 'BS', 'BZ', 'KY', 'PR', 'PW'))


def country_temperature_unit(country):
    from lib.weather_setup import resolve_country
    code = resolve_country(country)
    return '°F' if code in FAHRENHEIT_COUNTRIES else '°C'


def addon_temperature_unit(addon=None):
    """Code has priority; the saved country name supports older settings."""
    try:
        if addon is None:
            from addon_state import get_addon
            addon = get_addon()
        from lib.weather_setup import resolve_country
        for key in ('weather_country_code', 'weather_country_name'):
            code = resolve_country(addon.getSetting(key))
            if code:
                return country_temperature_unit(code)
    except Exception:
        pass
    return '°C'
