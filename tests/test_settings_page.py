"""Custom addon-owned settings window regressions."""
import ast
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class SettingsPageTests(unittest.TestCase):
    def test_settings_window_is_addon_owned_and_packaged(self):
        xml = ROOT / "resources/skins/Main/1080i/script-stremio-settings.xml"
        tree = ET.parse(xml)
        self.assertEqual(tree.getroot().tag, "window")
        self.assertIsNotNone(tree.find('.//control[@id="100"]'))
        self.assertIsNotNone(tree.find('.//control[@id="200"]'))
        self.assertIsNotNone(tree.find('.//control[@id="300"]'))

    def test_settings_categories_are_reorganized(self):
        source = (ROOT / "lib/settings_page.py").read_text(encoding="utf-8")
        for label in ("General", "Account & Stremio", "Playback", "Subtitles & AI",
                      "Appearance", "Weather", "Ratings", "Cache", "Support", "Premium"):
            self.assertIn('"' + label + '"', source)
        self.assertIn("Auto - Video first, then Stremio addons", source)
        self.assertIn("$4.99 USD / month", source)
        self.assertIn("Subtitle text size", source)
        self.assertIn("Subtitle font", source)
        self.assertIn("Subtitle color", source)

    def test_choice_rows_use_custom_in_window_subpage_not_kodi_select(self):
        source = (ROOT / "lib/settings_page.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SettingsWindow")
        methods = {n.name: ast.unparse(n) for n in cls.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("open_subpage", methods)
        self.assertIn("self.open_enum(row)", methods["onClick"])
        self.assertIn("self.open_secret(row)", methods["onClick"])
        self.assertIn("self.open_kodi(row)", methods["onClick"])
        self.assertNotIn("Dialog().select", methods["onClick"])

    def test_entire_settings_tree_avoids_native_select_yesno_and_textviewer(self):
        source = (ROOT / "lib/settings_page.py").read_text(encoding="utf-8")
        self.assertNotIn(".select(", source)
        self.assertNotIn(".yesno(", source)
        self.assertNotIn(".textviewer(", source)
        for legacy in ("locale_menu()", "configure_weather(", "configure_cache()",
                       "clear_selected()", "manual_report(", "report_last_error("):
            self.assertNotIn(legacy, source)
        for custom in ("locale_language", "locale_region", "weather_country",
                       "cache_ttl:", "feedback_type", "account_disconnect"):
            self.assertIn(custom, source)

    def test_language_preference_never_reloads_kodi_skin_from_modal_settings(self):
        source = (ROOT / "lib/settings_page.py").read_text(encoding="utf-8")
        self.assertNotIn("apply_kodi_locale", source)
        self.assertNotIn("ReloadSkin", source)
        self.assertIn("Never switch Kodi's global language", source)

    def test_home_settings_no_longer_opens_native_addon_settings(self):
        source = (ROOT / "lib/nimbus.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "HomeWindow")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "open_settings")
        text = ast.unparse(method)
        self.assertIn("show_settings", text)
        self.assertNotIn("openSettings", text)


if __name__ == "__main__":
    unittest.main()
