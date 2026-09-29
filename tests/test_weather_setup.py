"""Country-scoped postal search and non-destructive weather setup."""
from pathlib import Path
import math
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET
import weather
from lib.weather_setup import countries, postcode, search_places, save_place, configure_weather

class Addon:
    def __init__(self, **values): self.values = values; self.writes = []
    def getSetting(self, key): return self.values.get(key, '')
    def setSetting(self, key, value): self.values[key] = value; self.writes.append((key, value))

class WeatherTests(unittest.TestCase):
    def row(self, country='US', **changes):
        value = {'name': 'New York', 'country_code': country, 'country': 'United States',
                 'admin1': 'New York', 'latitude': 40.75, 'longitude': -73.99,
                 'postcodes': ['10001']}
        value.update(changes)
        return value
    def test_all_country_options_are_unique(self):
        rows = countries()
        self.assertGreaterEqual(len(rows), 249)
        self.assertEqual(len(rows), len(dict(rows)))
        for code in ('AU','NZ','US','GB','BA','RS','CH','JP','ZA'):
            self.assertIn(code, dict(rows))
    def test_country_name_and_code_resolve(self):
        for name in ('Australia', 'Australia (24h)', 'AU', 'au'):
            self.assertEqual(weather.country_code(name), 'AU')
    def test_leading_zero_and_alphanumeric_postcodes_preserved(self):
        for value, expected in [('0800','0800'),('sw1a 1aa','SW1A 1AA'),('h2x 1y4','H2X 1Y4'),('12-345','12-345')]:
            self.assertEqual(postcode(value), expected)
    def test_invalid_postcodes_rejected(self):
        for value in ('','  ','a/b','https://bad','123\n456', 'x'*20):
            with self.assertRaises(ValueError): postcode(value)
    def test_au_postcode_uses_local_data_not_other_country(self):
        fetcher = Mock(side_effect=AssertionError('Network not needed'))
        rows = weather.search('6000','AU',fetcher=fetcher,postal=True)
        self.assertTrue(rows)
        self.assertTrue(all(row['country_code']=='AU' and row['postcode']=='6000' for row in rows))
        fetcher.assert_not_called()
    def test_api_and_client_enforce_country_and_postcode(self):
        network = Mock(return_value={'results':[self.row(),self.row('AU'),self.row(''),self.row(postcodes=['10002'])]})
        rows = search_places('10001','US',network,postal=True)
        self.assertEqual(len(rows),1)
        query = parse_qs(urlsplit(network.call_args.args[0]).query)
        self.assertEqual(query['countryCode'],['US'])
        self.assertEqual(query['name'],['10001'])
        self.assertEqual(query['count'],['100'])
    def test_malformed_coordinates_never_selectable(self):
        network = Mock(return_value={'results':[self.row(latitude=v) for v in (True,None,'40.7',math.nan,1000)]})
        self.assertEqual(search_places('10001','US',network,True),[])
    def test_duplicates_removed(self):
        network=Mock(return_value={'results':[self.row(),self.row()]})
        self.assertEqual(len(search_places('10001','US',network,True)),1)
    def test_unknown_country_does_not_fall_back_worldwide(self):
        network=Mock()
        with self.assertRaises(ValueError): weather.search('10001','Not a country',fetcher=network)
        network.assert_not_called()
    def test_city_lookup_stays_in_country_without_postal_requirement(self):
        network=Mock(return_value={'results':[self.row('BA',name='Sarajevo',postcodes=[]),self.row('US')]})
        rows=search_places('Sarajevo','BA',network,False)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['country_code'],'BA')
    def test_postal_setup_saves_selected_place_coordinates(self):
        addon=Addon(weather_country_code='US',token='untouched')
        dialog=Mock(); dialog.input.return_value='10001'; dialog.select.return_value=0
        self.assertTrue(configure_weather('postcode',dialog,addon,Mock(return_value={'results':[self.row()]})))
        self.assertEqual(addon.values['weather_postcode'],'10001')
        self.assertEqual(addon.values['weather_lat'],'40.75')
        self.assertEqual(addon.values['weather_lon'],'-73.99')
        self.assertEqual(addon.values['weather_country_name'],'United States')
        self.assertEqual(addon.values['token'],'untouched')
    def test_cancel_place_selection_does_not_change_saved_location(self):
        addon=Addon(weather_country_code='US',weather_location='Old place')
        old=dict(addon.values); dialog=Mock(); dialog.input.return_value='10001'; dialog.select.return_value=-1
        self.assertFalse(configure_weather('postcode',dialog,addon,Mock(return_value={'results':[self.row()]})))
        self.assertEqual(addon.values,old)
        self.assertFalse(addon.writes)
    def test_cancel_country_has_no_network_or_settings_writes(self):
        addon=Addon(); dialog=Mock(); dialog.select.return_value=-1; network=Mock()
        self.assertFalse(configure_weather('country',dialog,addon,network))
        network.assert_not_called(); self.assertFalse(addon.writes)
    def test_country_change_then_cancel_keeps_old_forecast_location(self):
        addon=Addon(weather_country_code='AU',weather_location='Old AU place')
        dialog=Mock(); dialog.select.return_value=next(i for i,row in enumerate(countries()) if row[0]=='US')
        dialog.input.return_value=''; network=Mock(); old=dict(addon.values)
        self.assertFalse(configure_weather('country',dialog,addon,network))
        self.assertEqual(addon.values,old); network.assert_not_called()
    def test_no_results_allows_exit_without_saving(self):
        addon=Addon(weather_country_code='US'); dialog=Mock()
        dialog.input.return_value='00000'; dialog.select.return_value=4
        self.assertFalse(configure_weather('postcode',dialog,addon,Mock(return_value={'results':[]})))
        dialog.ok.assert_called_once(); self.assertFalse(addon.writes)
    def test_network_error_does_not_save_or_use_other_country(self):
        addon=Addon(weather_country_code='US'); dialog=Mock()
        dialog.input.return_value='10001'; dialog.select.return_value=4
        self.assertFalse(configure_weather('postcode',dialog,addon,Mock(side_effect=OSError('offline'))))
        self.assertFalse(addon.writes)
    def test_invalid_or_foreign_place_cannot_be_saved(self):
        addon=Addon()
        with self.assertRaises(ValueError):
            save_place(addon,'AU','6000',{'country_code':'US','latitude':40,'longitude':-70,'label':'Wrong'})
        self.assertFalse(addon.writes)
    def test_settings_hide_coordinates_and_keep_country_zip_actions(self):
        root=Path(__file__).resolve().parents[1]
        tree=ET.parse(root/'resources/settings.xml')
        for key in ('weather_lat','weather_lon'):
            self.assertEqual(tree.find(".//setting[@id='"+key+"']").get('visible'),'false')
        self.assertIn('weather_country',(root/'resources/settings.xml').read_text())
        self.assertIn('weather_postcode',(root/'default.py').read_text())

if __name__=='__main__': unittest.main()
