"""Weather header regressions: layout, icons, units and failure safety."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import weather
from lib import weather_widget as widget

ROOT = Path(__file__).resolve().parents[1]

class Window:
    def __init__(self): self.values = {}
    def getProperty(self, name): return self.values.get(name, '')
    def setProperty(self, name, value): self.values[name] = value
    def clearProperty(self, name): self.values.pop(name, None)

class WeatherWidgetTests(unittest.TestCase):
    def test_all_weather_icons_exist(self):
        for code in weather.WMO:
            for day in (0, 1):
                path = widget.colour_icon(code, day)
                target = ROOT / path.split('script.stremioelec/', 1)[1]
                self.assertEqual(target.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
    def test_day_and_night_are_distinct(self):
        self.assertTrue(widget.colour_icon(0, 1).endswith('/32.png'))
        self.assertTrue(widget.colour_icon(0, 0).endswith('/31.png'))
        self.assertEqual(widget.colour_icon(None), '')
    def test_temperature_units_and_invalid_values(self):
        self.assertEqual(widget.temperature(0), '0°C')
        self.assertEqual(widget.temperature(20, '°F'), '68°F')
        self.assertEqual(widget.temperature(-4), '-4°C')
        for value in (None, True, '20', float('nan'), float('inf')):
            self.assertEqual(widget.temperature(value), '')
    def test_apply_publishes_real_current_values(self):
        window = Window()
        weather.apply({'current': {'weather_code': 0, 'is_day': 0,
                                   'temperature_2m': 0}}, 'Example', window)
        self.assertEqual(window.getProperty(widget.READY), 'true')
        self.assertEqual(window.getProperty(widget.TEMPERATURE), '0°C')
        self.assertTrue(window.getProperty(widget.ICON).endswith('/31.png'))
    def test_missing_data_never_fakes_weather(self):
        window = Window()
        weather.apply({'current': {}}, 'Example', window)
        self.assertEqual(window.getProperty(widget.READY), '')
        self.assertEqual(window.getProperty(widget.TEMPERATURE), '')
    def test_refresh_is_nonblocking_and_throttled(self):
        window, kodi, gui = Window(), Mock(), Mock()
        gui.Window.return_value = window
        self.assertTrue(widget.request_refresh(kodi=kodi, gui=gui, now=1000))
        self.assertFalse(widget.request_refresh(kodi=kodi, gui=gui, now=1001))
        kodi.executebuiltin.assert_called_once_with('RunScript(' + widget.REFRESH_SCRIPT + ')')
        window.values.update({widget.READY: 'true', 'Stremio.LastRefreshEpoch': '1000', 'Stremio.TemperatureUnit': '°C'})
        self.assertFalse(widget.request_refresh(kodi=kodi, gui=gui, now=1100))
        self.assertTrue(widget.request_refresh(force=True, kodi=kodi, gui=gui, now=1101))
    def test_clock_and_short_date_are_only_at_top(self):
        tree = ET.parse(ROOT / 'resources/skins/Main/1080i/script-stremio-nimbus.xml')
        clocks = [n for n in tree.iter('control') if n.findtext('label') == '$INFO[System.Time]']
        dates = [n for n in tree.iter('control') if 'System.Date' in (n.findtext('label') or '')]
        self.assertEqual(len(clocks), 1)
        self.assertEqual(len(dates), 1)
        self.assertLess(int(clocks[0].findtext('top')), 180)
        self.assertLess(int(dates[0].findtext('top')), 180)
        self.assertEqual(dates[0].findtext('label'), '$INFO[System.Date(ddd d mmm)]')
        self.assertIsNone(clocks[0].find('visible'))
        self.assertIsNone(dates[0].find('visible'))
        image = tree.find('.//control[@id="9901"]/control[@type="image"]')
        self.assertIsNone(image.find('texture').get('colordiffuse'))
    def test_refresh_requests_daylight_field(self):
        from urllib.parse import urlsplit, parse_qs
        fetcher = Mock(return_value={})
        weather.forecast(0, 0, fetcher)
        query = parse_qs(urlsplit(fetcher.call_args.args[0]).query)
        self.assertIn('is_day', query['current'][0].split(','))
    def test_weather_actions_have_their_own_short_lived_entry(self):
        settings = ET.parse(ROOT / 'resources/settings.xml')
        actions = [n.get('action', '') for n in settings.iter('setting')]
        self.assertTrue(any('/weather_settings.py,country)' in a for a in actions))
        for filename in ('weather_settings.py', 'weather_refresh.py'):
            ast.parse((ROOT / filename).read_text())
            self.assertIn("BASE / 'core'", (ROOT / filename).read_text())
    def test_refresh_failure_hides_old_weather_without_popup(self):
        window, addon, gui = Window(), Mock(), Mock()
        window.values[widget.READY] = 'true'
        addon.getSetting.side_effect = lambda key: {'weather_location': 'Example',
            'weather_lat': '10', 'weather_lon': '20'}.get(key, '')
        gui.Window.return_value = window
        state = Mock()
        state.get_addon.return_value = addon
        with patch.dict('sys.modules', {'xbmcgui': gui, 'addon_state': state}), \
                patch.object(weather, 'forecast', side_effect=OSError('offline')):
            self.assertIsNone(weather.refresh(force=True))
        self.assertEqual(window.getProperty(widget.READY), '')
        self.assertEqual(window.getProperty('Stremio.WeatherStatus'), 'Weather unavailable')
        gui.Dialog.assert_not_called()

if __name__ == '__main__':
    unittest.main()
