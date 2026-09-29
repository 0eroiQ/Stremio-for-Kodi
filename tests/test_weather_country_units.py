"""Country-selected temperature units, without changing Kodi's locale."""
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs
import weather
from lib import weather_widget as widget
from lib.weather_units import addon_temperature_unit, country_temperature_unit

class Window:
    def __init__(self): self.values = {}
    def getProperty(self, key): return self.values.get(key, '')
    def setProperty(self, key, value): self.values[key] = value
    def clearProperty(self, key): self.values.pop(key, None)

class WeatherCountryTests(unittest.TestCase):
    def test_country_unit_mapping(self):
        for country in ('AU','Australia','au','GB','CA','BA','DE','FR','LR','MM',''):
            self.assertEqual(country_temperature_unit(country), '°C')
        for country in ('US','United States','BS','BZ','KY','PR','PW'):
            self.assertEqual(country_temperature_unit(country), '°F')

    def test_setting_code_priority_and_name_fallback(self):
        addon = Mock()
        for values, expected in (({'weather_country_code':'AU','weather_country_name':'United States'},'°C'),
                                 ({'weather_country_name':'Australia'},'°C'),
                                 ({'weather_country_code':'invalid','weather_country_name':'United States'},'°F'),
                                 ({},'°C')):
            addon.getSetting.side_effect = lambda k: values.get(k,'')
            self.assertEqual(addon_temperature_unit(addon),expected)

    def context(self, country):
        window, addon, kodi, gui, state = Window(), Mock(), Mock(), Mock(), Mock()
        values = {'weather_location':'Example','weather_lat':'10','weather_lon':'20','weather_country_code':country}
        addon.getSetting.side_effect = lambda k: values.get(k,'')
        state.get_addon.return_value = addon
        gui.Window.return_value = window
        kodi.getRegion.return_value = '°F' if country == 'AU' else '°C'
        modules = {'addon_state':state, 'xbmcgui':gui, 'xbmc':kodi}
        return window, values, kodi, modules

    def test_refresh_ignores_opposite_kodi_unit(self):
        for country, expected in (('AU','20°C'),('US','68°F')):
            window, values, kodi, modules = self.context(country)
            payload = {'current':{'weather_code':0,'temperature_2m':20}}
            with patch.dict('sys.modules',modules), patch.object(weather,'forecast',return_value=payload):
                weather.refresh(force=True)
            self.assertEqual(window.getProperty(widget.TEMPERATURE),expected)
            kodi.getRegion.assert_not_called()
            kodi.executeJSONRPC.assert_not_called()
            modules['addon_state'].get_addon.return_value.setSetting.assert_not_called()

    def test_request_always_uses_celsius_data(self):
        fetcher = Mock(return_value={})
        weather.forecast(0,0,fetcher)
        query = parse_qs(urlsplit(fetcher.call_args.args[0]).query)
        self.assertEqual(query['temperature_unit'], ['celsius'])

    def test_country_change_invalidates_recent_cached_units(self):
        window, values, kodi, modules = self.context('AU')
        payload = {'current': {'weather_code': 0, 'temperature_2m': 20}}
        with patch.dict('sys.modules', modules), patch.object(weather, 'forecast', return_value=payload) as fetch:
            weather.refresh(force=True)
            self.assertEqual(window.getProperty(widget.TEMPERATURE), '20°C')
            values['weather_country_code'] = 'US'
            weather.refresh()
            self.assertEqual(window.getProperty(widget.TEMPERATURE), '68°F')
            self.assertEqual(fetch.call_count, 2)

    def test_late_country_change_does_not_publish_stale_units(self):
        window, values, kodi, modules = self.context('AU')
        def late_response(*args):
            values['weather_country_code'] = 'US'
            return {'current': {'weather_code': 0, 'temperature_2m': 20}}
        with patch.dict('sys.modules', modules), patch.object(weather, 'forecast', side_effect=late_response):
            weather.refresh(force=True)
        self.assertEqual(window.getProperty(widget.READY), '')
        self.assertEqual(window.getProperty(widget.TEMPERATURE), '')

    def test_refresh_is_scheduled_when_cached_unit_changes(self):
        window, values, kodi, modules = self.context('AU')
        window.values.update({widget.READY:'true', widget.REQUESTED:'1000',
                              'Stremio.LastRefreshEpoch':'1000', 'Stremio.TemperatureUnit':'°F'})
        with patch.dict('sys.modules', modules):
            self.assertTrue(widget.request_refresh(kodi=kodi, gui=modules['xbmcgui'], now=1100))
        kodi.executebuiltin.assert_called_once()
