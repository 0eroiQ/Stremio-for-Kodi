"""Addon-owned full-screen settings UI for Stremio for Kodi."""
from pathlib import Path

import xbmc
import xbmcgui
import xbmcvfs

from addon_state import get_addon
from account import Store
from lib.theme import window as themed_window
from lib.ui_dialogs import dialog as themed_dialog

ADDON = get_addon()
PROFILE = Path(xbmcvfs.translatePath(ADDON.getAddonInfo("profile")))
BACK = (10, 92, 216, 247)

THEMES = ("Purple", "Black", "Blue", "Green", "Gold")
FOCUS = ("Original", "Purple", "Blue", "Green", "Gold", "Theme")
START_DELAYS = ("Immediately", "1 second", "2 seconds", "3 seconds", "5 seconds")
TRAILER_QUALITY = ("1080p", "720p", "480p")
TRAILER_SCOPE = ("Home and Media info hero", "Home hero only", "Media info hero only")
TRAILER_DELAY = ("3 seconds", "5 seconds", "10 seconds", "15 seconds", "30 seconds", "1 second")
SUBTITLE_SETTINGS_SOURCES = ("MKGA.TV Account - Recommended", "This device - Local")
AI_PROVIDERS = ("My Gemini API key - Free",)
AI_SOURCES = ("Auto - Video first, then Stremio addons", "Video subtitles only", "Stremio addons only")
AI_TARGETS = ("Bosnian", "Croatian", "Serbian", "English", "German", "French", "Spanish",
              "Italian", "Portuguese", "Dutch", "Polish", "Czech", "Slovak", "Slovenian",
              "Macedonian", "Albanian", "Turkish", "Greek", "Romanian", "Hungarian",
              "Bulgarian", "Russian", "Ukrainian", "Arabic", "Hebrew", "Hindi",
              "Chinese", "Japanese", "Korean")

CATEGORIES = (
    ("General", "general"), ("Account & Stremio", "account"), ("Playback", "playback"),
    ("Subtitles & AI", "subtitles"), ("Appearance", "appearance"), ("Weather", "weather"),
    ("Ratings", "ratings"), ("Cache", "cache"), ("Support", "support"),
)


def _enum(setting, label, values, help_text):
    return {"kind": "enum", "id": setting, "label": label, "values": values, "help": help_text}


def _bool(setting, label, help_text):
    return {"kind": "bool", "id": setting, "label": label, "help": help_text}


def _action(action, label, help_text, summary="Open"):
    return {"kind": "action", "action": action, "label": label, "help": help_text, "summary": summary}


def _secret(setting, label, help_text):
    return {"kind": "secret", "id": setting, "label": label, "help": help_text}


def _text(setting, label, help_text):
    return {"kind": "text", "id": setting, "label": label, "help": help_text}


def _info(label, summary, help_text):
    return {"kind": "info", "label": label, "summary": summary, "help": help_text}


def _choice(identity, label, labels, values, selected, help_text):
    return {
        "kind": "choice", "id": identity, "label": label,
        "labels": tuple(labels), "values": tuple(values), "selected": int(selected),
        "summary": str(labels[selected]) if labels and 0 <= selected < len(labels) else "Choose",
        "help": help_text,
    }


def _kodi(setting, label, help_text):
    return {"kind": "kodi", "id": setting, "label": label, "help": help_text}


def _kodi_definition(setting_id):
    try:
        from setup_profile import rpc
        settings = rpc("Settings.GetSettings", {"level": "expert"}).get("settings", [])
        return next((item for item in settings if item.get("id") == setting_id), None)
    except Exception:
        return None


def _kodi_options(definition):
    if not definition:
        return []
    try:
        from settings_ui import setting_options
        return setting_options(definition)
    except Exception:
        return []


def _kodi_rows():
    return [
        _kodi("subtitles.fontsize", "Subtitle text size", "Kodi subtitle text size."),
        _kodi("subtitles.fontname", "Subtitle font", "Font used for text subtitles."),
        _kodi("subtitles.style", "Subtitle style", "Normal, bold, italic or bold italic where supported."),
        _kodi("subtitles.colorpick", "Subtitle color", "Main subtitle text color."),
        _kodi("subtitles.align", "Subtitle position", "Vertical subtitle alignment and position."),
        _kodi("subtitles.backgroundtype", "Background style", "Subtitle background / box style."),
        _kodi("subtitles.bordercolorpick", "Border color", "Subtitle outline / border color."),
        _kodi("subtitles.bgcolorpick", "Background color", "Subtitle background color."),
        _kodi("subtitles.shadowcolor", "Shadow color", "Subtitle shadow color."),
        _kodi("subtitles.overridestyles", "Override embedded styles", "Control whether Kodi overrides subtitle file styling."),
    ]


def rows_for(category):
    if category == "general":
        from lib.settings import load_setup
        from lib.windows import LANGUAGES, REGIONS
        setup = load_setup()
        language = setup.get("language") or LANGUAGES[0]
        region = setup.get("region") or REGIONS[0]
        language_index = next((i for i, row in enumerate(LANGUAGES) if tuple(row) == tuple(language)), 0)
        region_index = next((i for i, row in enumerate(REGIONS) if tuple(row) == tuple(region)), 0)
        return [
            _bool("startup_autostart", "Launch when Kodi starts", "Automatically open Stremio for Kodi after Kodi starts."),
            _enum("startup_delay", "Startup delay", START_DELAYS, "Delay before automatic launch."),
            _choice("locale_language", "Language", [row[0] for row in LANGUAGES], LANGUAGES,
                    language_index, "Stremio for Kodi language preference. This does not reload or change Kodi's global skin language."),
            _choice("locale_region", "Location / region", [row[0] for row in REGIONS], REGIONS,
                    region_index, "Stremio for Kodi regional preference. Weather has its own country/location settings."),
        ]
    if category == "account":
        connected = bool(Store(PROFILE).load().get("token"))
        manifest = ADDON.getSetting("manifest").strip() or "https://v3-cinemeta.strem.io/manifest.json"
        rows = [
            _info("Stremio account", "Connected" if connected else "Not connected",
                  "This device uses your Stremio account for library, addons and MKGA.TV account sync."),
        ]
        rows += ([
            _action("account_refresh", "Refresh Stremio library", "Refresh library data from the connected Stremio account.", "Refresh"),
            _action("account_disconnect", "Disconnect this device", "Remove this device login and account-synced addons only.", "Disconnect"),
        ] if connected else [
            _action("account_signin", "Connect Stremio account", "Open the addon-owned QR sign-in screen.", "Connect"),
        ])
        rows += [
            _action("addons", "Stremio addons", "Open the addon's Stremio addon manager.", "Manage"),
            _text("manifest", "Catalog manifest", "Default is the official Cinemeta manifest URL."),
            _info("Catalog source", "Official Cinemeta" if "v3-cinemeta.strem.io" in manifest else "Custom",
                  "Shows whether the catalog manifest is the default official source or a custom URL."),
        ]
        return rows
    if category == "playback":
        return [
            _bool("trailers_enabled", "Enable trailers", "Use built-in direct IMDb trailers."),
            _enum("trailers_quality", "Trailer quality", TRAILER_QUALITY, "Preferred trailer resolution."),
            _bool("trailers_auto", "Automatic hero previews", "Automatically preview trailers in the hero."),
            _enum("trailers_auto_scope", "Preview location", TRAILER_SCOPE, "Where automatic trailer previews are allowed."),
            _enum("trailers_delay", "Preview delay", TRAILER_DELAY, "How long focus waits before previewing a trailer."),
            _bool("playback_back_stops", "Back stops fullscreen video", "Back stops fullscreen Kodi playback."),
        ]

    if category == "subtitles":
        try:
            mode = int(ADDON.getSetting("subtitle_settings_source") or "0")
        except (TypeError, ValueError):
            mode = 0
        common = [
            _enum("subtitle_settings_source", "Subtitle settings source", SUBTITLE_SETTINGS_SOURCES,
                  "Use your MKGA.TV Stremio Account Hub as the main control center, or keep all preferences local to this Kodi device."),
            _bool("ai_subtitles_enabled", "AI subtitles on this device",
                  "Local master switch. Turn this off to disable AI subtitles on this Kodi device even when MKGA.TV enables Smart Subtitles."),
            _enum("ai_subtitles_provider", "AI provider", AI_PROVIDERS,
                  "Provider choice stays local. Free mode uses your own Gemini API key."),
            _secret("ai_subtitles_gemini_api_key", "Gemini API key",
                    "Always stored locally in Kodi and sent only to Google's Gemini API in Free BYOK mode."),
        ]
        if mode == 0:
            try:
                hub_state_data = Store(PROFILE).load()
                synced_at = int(hub_state_data.get("mkga_stremio_hub_checked_at") or 0)
                import time as _time
                sync_summary = "Never synced" if not synced_at else ("{}s ago".format(max(0, int(_time.time())-synced_at)) if int(_time.time())-synced_at < 120 else "{}m ago".format(max(1,(int(_time.time())-synced_at)//60)))
            except Exception:
                sync_summary = "Unknown"
            return common + [
                _info("MKGA.TV subtitle profile", "Synced automatically",
                      "Language priority, Smart Subtitles, translation/generation behavior, source priority, timing, size, position and color are managed in Account > Stremio > Subtitles on MKGA.TV."),
                _info("Last MKGA sync", sync_summary, "Background sync checks about every 30 seconds."),
                _action("subtitle_sync_now", "Sync from MKGA.TV now", "Force an immediate refresh of the linked Stremio subtitle profile.", "Sync now"),
            ]
        return common + [
            _enum("ai_subtitles_source", "Subtitle source", AI_SOURCES,
                  "Auto prefers the subtitle embedded in the exact video for best sync, then Stremio addons."),
            _enum("ai_subtitles_target", "Translate to", AI_TARGETS, "Target language for AI subtitles."),
        ] + _kodi_rows()
    if category == "appearance":
        return [
            _enum("ui_theme", "Theme", THEMES, "Changes the colors of addon-owned windows."),
            _enum("ui_focus_color", "Poster focus color", FOCUS, "Focus border color for posters and cards."),
            _bool("ui_animations", "Animations", "Enable addon interface animations."),
            _bool("search_native_keyboard", "Use native Kodi keyboard for Search", "Improves physical/Bluetooth keyboard and Yatse/Kore mobile keyboard support."),
            _bool("ui_dim_rows", "Dim rows with side menu", "Dim content rows while the side menu is open."),
            _bool("ui_show_logo", "Title logos", "Use title logos when available."),
            _bool("ui_show_plot", "Descriptions", "Show title descriptions in hero areas."),
            _bool("ui_show_rating", "Ratings", "Show ratings in hero areas."),
            _bool("ui_show_genres", "Genres", "Show genres in hero metadata."),
            _bool("ui_show_runtime", "Runtime", "Show runtime in hero metadata."),
        ]
    if category == "weather":
        from lib.weather_setup import countries, resolve_country
        country_rows = countries()
        code = resolve_country(ADDON.getSetting("weather_country_code") or
                               ADDON.getSetting("weather_country_name"))
        country_index = next((i for i, row in enumerate(country_rows) if row[0] == code), 0)
        place = ADDON.getSetting("weather_location").strip() or "Not set"
        postcode = ADDON.getSetting("weather_postcode").strip() or "Not set"
        return [
            _choice("weather_country", "Country / territory",
                    ["{} ({})".format(name, code) for code, name in country_rows],
                    country_rows, country_index, "Country used to scope every weather location search."),
            _action("weather_postal", "ZIP / postal code", "Enter a postal code, then choose a matching place in our Settings page.", postcode),
            _action("weather_city", "City / suburb", "Search by city or suburb, then choose a matching place in our Settings page.", "Search"),
            _info("Selected place", place, "Current saved weather location."),
            _action("weather_refresh", "Refresh weather now", "Refresh the built-in weather provider using the saved place.", "Refresh"),
        ]
    if category == "ratings":
        return [
            _secret("mdblist_api_key", "MDbList API key", "Optional key used for additional rating providers."),
            _bool("rating_mdblist", "MDbList score", "Show MDbList score."),
            _bool("rating_imdb", "IMDb", "Show IMDb rating."),
            _bool("rating_tmdb", "TMDb", "Show TMDb rating."),
            _bool("rating_trakt", "Trakt", "Show Trakt rating."),
            _bool("rating_tomatoes", "Rotten Tomatoes", "Show Rotten Tomatoes critic rating."),
            _bool("rating_metacritic", "Metacritic", "Show Metacritic rating."),
            _bool("rating_letterboxd", "Letterboxd", "Show Letterboxd rating."),
            _secret("tmdb_api_key", "TMDb API key", "Optional override used by trailer metadata lookup."),
        ]

    if category == "cache":
        from lib.cache_policy import GROUPS, setting_id, parse_duration, parse_size, format_duration, format_size
        from lib.maintenance import PRESETS, SIZES
        rows = []
        duration_labels = [format_duration(parse_duration(value)) for value in PRESETS]
        for group, label, default in GROUPS:
            current = ADDON.getSetting(setting_id(group)) or default
            selected = PRESETS.index(current) if current in PRESETS else 0
            rows.append(_choice("cache_ttl:" + group, label, duration_labels, PRESETS, selected,
                                "How long this response category stays cached before refresh."))
        current_size = ADDON.getSetting("cache_max_mb") or "64"
        size_labels = [format_size(parse_size(value)) for value in SIZES]
        size_selected = SIZES.index(current_size) if current_size in SIZES else 2
        rows.append(_choice("cache_size", "Maximum response data", size_labels, SIZES, size_selected,
                            "Maximum disk space used by addon response data."))
        rows += [
            _action("cache_clear_selected_custom", "Clear one cache category",
                    "Choose a response cache to clear. Login, library and playback data are kept.", "Choose"),
            _action("cache_clear_all_custom", "Clear all response caches",
                    "Clear catalogs, search, metadata and ratings only.", "Clear"),
        ]
        return rows
    if category == "support":
        return [
            _action("support", "Support development", "Optional support for ongoing MKGA development.", "Open"),
            _bool("error_reporting_auto", "Anonymous error reports", "Automatically send sanitized anonymous crash reports."),
            _action("report_issue", "Report a bug / request a feature", "Send a reviewed bug report or feature request.", "Open"),
            _action("report_last_error", "Report last error", "Review and retry the most recent sanitized error report.", "Open"),
            _action("send_performance_report", "Send performance report", "Review and send Home timing data only; no Kodi log, account data, URLs or keys.", "Send"),
        ]
    return []


def _index_value(setting, values):
    try:
        index = int(ADDON.getSetting(setting) or "0")
    except (TypeError, ValueError):
        index = 0
    return values[index] if 0 <= index < len(values) else values[0]


def summary(row):
    kind = row["kind"]
    if kind == "bool":
        return "On" if ADDON.getSetting(row["id"]).lower() == "true" else "Off"
    if kind == "enum":
        return _index_value(row["id"], row["values"])
    if kind == "secret":
        return "Configured" if ADDON.getSetting(row["id"]).strip() else "Not set"
    if kind == "text":
        value = ADDON.getSetting(row["id"]).strip()
        if row["id"] == "manifest":
            return "Official Cinemeta" if "v3-cinemeta.strem.io" in value else ("Custom" if value else "Default")
        return value or "Not set"
    if kind == "choice":
        return row.get("summary", "Choose")
    if kind == "kodi":
        definition = _kodi_definition(row["id"])
        if not definition:
            return "Unavailable"
        value = definition.get("value")
        options = _kodi_options(definition)
        match = next((str(option.get("label")) for option in options
                      if option.get("value") == value), None)
        if match:
            return match
        if isinstance(value, bool):
            return "On" if value else "Off"
        return str(value)
    return row.get("summary", "")


def _set_bool(row):
    current = ADDON.getSetting(row["id"]).lower() == "true"
    ADDON.setSetting(row["id"], "false" if current else "true")


def _set_text(row):
    current = ADDON.getSetting(row["id"]).strip()
    value = themed_dialog().input(row["label"], defaultt=current, type=xbmcgui.INPUT_ALPHANUM)
    if not value.strip():
        return False
    if row["id"] == "manifest":
        from protocol import base_url
        try:
            base_url(value.strip())
        except Exception:
            themed_dialog().ok("Catalog manifest", "Use an HTTP(S) URL ending in /manifest.json.")
            return False
    ADDON.setSetting(row["id"], value.strip())
    return True


def run_action(action, owner=None):
    if action == "account_signin":
        from lib.signin import show_signin
        show_signin()
    elif action == "account_refresh":
        try:
            from account import pull_library
            store = Store(PROFILE)
            state = store.load()
            if state.get("token"):
                state["library"] = pull_library(state["token"])
                store.save(state)
                themed_dialog().notification("Stremio for Kodi", "Library refreshed.")
        except Exception:
            themed_dialog().notification("Stremio for Kodi", "Library refresh unavailable.")
    elif action == "account_disconnect" and owner is not None:
        owner.open_command(
            "account_disconnect", "Disconnect this device",
            ["Disconnect this device", "Cancel"], ["disconnect", "cancel"],
            "Removes this device login and account-synced addons. Your online Stremio account is unchanged."
        )
    elif action == "addons":
        if owner is not None:
            owner.request_page = "addons"
            owner.close()
    elif action == "subtitle_sync_now":
        try:
            from lib.signin import account_store
            from lib.vortexo_premium import hub_state
            hub = hub_state(account_store(), refresh_remote=True, max_age=0)
            if not hub.get("linked") or not isinstance(hub.get("settings"), dict):
                themed_dialog().notification("MKGA.TV", "No linked MKGA Stremio profile found.")
            else:
                from ai_subtitles import _apply_remote_style
                remote = hub["settings"]
                _apply_remote_style({"remote": True, "subtitle_size": remote.get("subtitleSize", "medium"), "subtitle_position": remote.get("subtitlePosition", "bottom"), "subtitle_color": remote.get("subtitleColor", "white")})
                themed_dialog().notification("MKGA.TV", "Subtitle profile synced.")
        except Exception:
            themed_dialog().notification("MKGA.TV", "Subtitle sync unavailable.")
    elif action == "weather_postal" and owner is not None:
        owner.open_weather_search(True)
    elif action == "weather_city" and owner is not None:
        owner.open_weather_search(False)
    elif action == "weather_refresh":
        try:
            from weather import refresh
            refresh(force=True)
            themed_dialog().notification("Weather", "Weather refreshed.")
        except Exception:
            themed_dialog().notification("Weather", "Weather refresh unavailable.")
    elif action == "cache_clear_selected_custom" and owner is not None:
        from lib.cache_policy import GROUPS
        labels = [label for _, label, _ in GROUPS] + ["Older entries", "Cancel"]
        values = [key for key, _, _ in GROUPS] + ["legacy", "cancel"]
        owner.open_command(
            "cache_clear_one", "Clear one cache category", labels, values,
            "Only the selected response cache is cleared. Login, library and playback data stay."
        )
    elif action == "cache_clear_all_custom" and owner is not None:
        owner.open_command(
            "cache_clear_all", "Clear all response caches",
            ["Clear all response caches", "Cancel"], ["clear", "cancel"],
            "Clears catalogs, search, metadata and ratings. Login, library and playback data stay."
        )
    elif action == "support":
        import support_development
        support_development.main()
    elif action == "report_issue" and owner is not None:
        owner.open_feedback_type()
    elif action == "report_last_error" and owner is not None:
        owner.open_last_error_custom()
    elif action == "send_performance_report":
        from lib.perf_report import build_payload
        from lib.error_report import show_report_dialog
        payload = build_payload(PROFILE)
        if payload:
            timings = payload.get("performance") or {}
            lines = ["{}: {} ms".format(stage, values.get("ms", 0))
                     for stage, values in timings.items() if "ms" in values]
            show_report_dialog(payload, "Home performance report\n" + "\n".join(lines), replay=True)
        else:
            themed_dialog().notification("Performance report", "No Home performance sample is available yet. Open Home first.")


class SettingsWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.category_index = 0
        self.rows = []
        self.appearance_changed = False
        self.request_page = None
        self.subpage = None
        self.subpage_row = None
        self.subpage_options = []
        self.subpage_values = []
        self.return_position = 0
        self.feedback_kind = None
        self.feedback_category = None
        self.feedback_title = None
        self.feedback_description = None
        super().__init__(*args, **kwargs)

    def onInit(self):
        categories = self.getControl(100)
        categories.reset()
        for label, key in CATEGORIES:
            item = xbmcgui.ListItem(label)
            item.setProperty("key", key)
            categories.addItem(item)
        categories.selectItem(self.category_index)
        self.load_category(self.category_index)
        self.setFocusId(100)

    def load_category(self, index):
        if not 0 <= index < len(CATEGORIES):
            return
        self.category_index = index
        label, key = CATEGORIES[index]
        self.getControl(301).setLabel(label)
        self.rows = rows_for(key)
        listing = self.getControl(200)
        listing.reset()
        for row in self.rows:
            item = xbmcgui.ListItem(row["label"], summary(row))
            item.setProperty("help", row.get("help", ""))
            item.setProperty("kind", row["kind"])
            listing.addItem(item)
        if self.rows:
            listing.selectItem(0)

    def refresh_rows(self):
        listing = self.getControl(200)
        position = max(0, listing.getSelectedPosition())
        self.load_category(self.category_index)
        if self.rows:
            listing.selectItem(min(position, len(self.rows) - 1))

    def open_subpage(self, row, labels, values=None, selected=0, help_text=None):
        self.return_position = max(0, self.getControl(200).getSelectedPosition())
        self.subpage = "picker"
        self.subpage_row = row
        self.subpage_options = list(labels)
        self.subpage_values = list(values if values is not None else range(len(labels)))
        self.getControl(301).setLabel(row["label"])
        listing = self.getControl(200)
        listing.reset()
        for index, label in enumerate(self.subpage_options):
            item = xbmcgui.ListItem(str(label), "Selected" if index == selected else "")
            item.setProperty("help", help_text or row.get("help", ""))
            listing.addItem(item)
        if self.subpage_options:
            listing.selectItem(max(0, min(selected, len(self.subpage_options) - 1)))
        self.setFocusId(200)

    def close_subpage(self):
        self.subpage = None
        self.subpage_row = None
        self.subpage_options = []
        self.subpage_values = []
        self.load_category(self.category_index)
        if self.rows:
            self.getControl(200).selectItem(min(self.return_position, len(self.rows) - 1))
            self.setFocusId(200)

    def open_enum(self, row):
        try:
            current = int(ADDON.getSetting(row["id"]) or "0")
        except (TypeError, ValueError):
            current = 0
        self.open_subpage(row, row["values"], selected=current)

    def open_choice(self, row):
        self.open_subpage(row, row["labels"], values=row["values"],
                          selected=row.get("selected", 0))

    def open_command(self, identity, label, labels, values, help_text):
        row = {"kind": "command", "id": identity, "label": label, "help": help_text}
        self.open_subpage(row, labels, values=values, selected=0, help_text=help_text)

    def open_feedback_type(self):
        self.open_command(
            "feedback_type", "Report a bug / request a feature",
            ["Bug report", "Feature request", "Report last error", "Cancel"],
            ["bug", "feature", "last", "cancel"],
            "Feedback is public on GitHub after the final addon-owned review screen. Never include credentials, links or personal details."
        )

    def open_last_error_custom(self):
        from lib.last_error import load_last_error
        from lib.error_report import show_report_dialog
        record = load_last_error()
        if record is None:
            themed_dialog().notification("Report last error", "No saved error is available.")
            return
        payload = record["payload"]
        summary = "{}: {}\nAddon {} | {}".format(
            payload.get("context", "Last error"), payload.get("errorType", "Error"),
            payload.get("addonVersion", "unknown"), payload.get("platform", "unknown")
        )
        show_report_dialog(payload, summary, replay=True)

    def finish_feedback(self, frequency):
        from lib.report_feedback import CATEGORIES, attach_feedback, report_labels
        from lib.error_report import build_payload, show_report_dialog
        payload = attach_feedback(build_payload("Manual report"), {
            "kind": self.feedback_kind,
            "category": self.feedback_category,
            "title": self.feedback_title,
            "description": self.feedback_description,
            "frequency": frequency,
        })
        labels = ", ".join(report_labels(payload, initial=True))
        kind = "Feature request" if self.feedback_kind == "feature" else "Bug report"
        show_report_dialog(payload, "{}\n{}\n\n{}".format(kind, self.feedback_title, labels))

    def open_weather_search(self, postal):
        from lib.weather_setup import resolve_country, postcode
        from weather import search
        code = resolve_country(ADDON.getSetting("weather_country_code") or
                               ADDON.getSetting("weather_country_name"))
        if not code:
            themed_dialog().notification("Weather", "Choose a country first.")
            return
        heading = "ZIP / postal code" if postal else "City / suburb"
        query = themed_dialog().input(heading)
        if not query or not query.strip():
            return
        try:
            query = postcode(query) if postal else query.strip()
            rows = search(query, code, postal=postal)
        except Exception:
            themed_dialog().notification("Weather", "Location search unavailable.")
            return
        if not rows:
            themed_dialog().notification("Weather", "No matching places found.")
            return
        row = {
            "kind": "weather_result", "id": "weather_result",
            "label": "Choose weather location",
            "help": "Choose the exact matching place. This selection stays inside Stremio for Kodi.",
            "country": code, "query": query, "postal": postal,
        }
        self.open_subpage(row, [item["label"] for item in rows], values=rows, selected=0)

    def open_secret(self, row):
        configured = bool(ADDON.getSetting(row["id"]).strip())
        labels = ["Replace key", "Remove key"] if configured else ["Add key"]
        self.open_subpage(row, labels, values=labels, selected=0,
                          help_text="API keys stay hidden. Typing uses the Stremio for Kodi secure hidden-input keyboard.")

    def open_kodi(self, row):
        definition = _kodi_definition(row["id"])
        if not definition or not definition.get("enabled", True):
            themed_dialog().notification("Stremio for Kodi", "This setting is unavailable on this device.")
            return
        value = definition.get("value")
        if isinstance(value, bool):
            from setup_profile import rpc
            rpc("Settings.SetSettingValue", {"setting": row["id"], "value": not value})
            self.refresh_rows()
            return
        options = _kodi_options(definition)
        if not options:
            themed_dialog().notification("Stremio for Kodi", "No supported choices were reported for this setting.")
            return
        labels = [str(option.get("label")) for option in options]
        values = [option.get("value") for option in options]
        selected = next((i for i, option in enumerate(options) if option.get("value") == value), 0)
        self.open_subpage(row, labels, values=values, selected=selected)

    def execute_command(self, identity, value):
        if value in ("cancel", None):
            return
        if identity == "account_disconnect" and value == "disconnect":
            state = Store(PROFILE).load()
            local = [item for item in state.get("addons", []) if item.get("account") is not True]
            disabled = set(state.get("disabledAddons", []))
            Store(PROFILE).save({
                "addons": local,
                "disabledAddons": sorted(disabled & {item.get("id") for item in local}),
            })
            for folder in ("streams", "playback", "subtitle-results"):
                Store(PROFILE / folder).forget()
            return
        if identity == "cache_clear_one":
            from lib.maintenance import _cache
            _cache().clear(str(value))
            return
        if identity == "cache_clear_all" and value == "clear":
            from lib.maintenance import _cache
            _cache().clear()
            return
        if identity == "feedback_type":
            if value == "last":
                self.open_last_error_custom()
                return
            if value in ("bug", "feature"):
                from lib.report_feedback import CATEGORIES
                self.feedback_kind = value
                self.open_command(
                    "feedback_category", "Feedback category",
                    [label for _, label in CATEGORIES] + ["Cancel"],
                    [key for key, _ in CATEGORIES] + ["cancel"],
                    "Choose the area that best matches this feedback."
                )
            return
        if identity == "feedback_category" and value != "cancel":
            from lib.report_feedback import feedback_text
            self.feedback_category = value
            title = themed_dialog().input(
                "Feature request title" if self.feedback_kind == "feature" else "Bug title"
            )
            if not title:
                return
            description = themed_dialog().input(
                "Describe the idea and why it helps" if self.feedback_kind == "feature"
                else "Steps to reproduce, expected result and what happens instead"
            )
            if not description:
                return
            try:
                self.feedback_title = feedback_text(title, 5, 100)
                self.feedback_description = feedback_text(description, 10, 1000)
            except ValueError:
                themed_dialog().notification("Feedback", "Check the title/description and remove links or credentials.")
                return
            if self.feedback_kind == "feature":
                self.finish_feedback("not-applicable")
            else:
                self.open_command(
                    "feedback_frequency", "How often does it happen?",
                    ["Every time", "Sometimes", "After restart", "Not retested", "Cancel"],
                    ["always", "sometimes", "after-restart", "not-retested", "cancel"],
                    "Choose how consistently the bug can be reproduced."
                )
            return
        if identity == "feedback_frequency" and value != "cancel":
            self.finish_feedback(str(value))
            return

    def apply_choice(self, row, value):
        identity = row.get("id", "")
        if identity in ("locale_language", "locale_region"):
            # This is an addon preference. Never switch Kodi's global language
            # while an addon-owned modal window is open: Kodi unloads/reloads the
            # skin and invalidates the active Stremio for Kodi windows.
            from lib.settings import load_setup, save_setup
            setup = load_setup()
            setup["language" if identity == "locale_language" else "region"] = tuple(value)
            save_setup(setup)
            return
        if identity == "weather_country":
            code, name = value
            old_code = ADDON.getSetting("weather_country_code").strip()
            ADDON.setSetting("weather_country_code", code)
            ADDON.setSetting("weather_country_name", name)
            if old_code and old_code != code:
                for key in ("weather_postcode", "weather_location", "weather_lat", "weather_lon"):
                    ADDON.setSetting(key, "")
            return
        if identity.startswith("cache_ttl:"):
            from lib.cache_policy import setting_id
            ADDON.setSetting(setting_id(identity.split(":", 1)[1]), str(value))
            from lib.maintenance import apply_settings
            apply_settings()
            return
        if identity == "cache_size":
            ADDON.setSetting("cache_max_mb", str(value))
            from lib.maintenance import apply_settings
            apply_settings()
            return

    def apply_subpage(self, index):
        if not self.subpage_row or not 0 <= index < len(self.subpage_values):
            return
        row = self.subpage_row
        value = self.subpage_values[index]
        if row["kind"] == "enum":
            ADDON.setSetting(row["id"], str(index))
            if row.get("id", "").startswith("ui_"):
                self.appearance_changed = True
            self.close_subpage()
            return
        if row["kind"] == "choice":
            self.apply_choice(row, value)
            self.close_subpage()
            return
        if row["kind"] == "command":
            identity = row.get("id", "")
            self.close_subpage()
            self.execute_command(identity, value)
            return
        if row["kind"] == "weather_result":
            from lib.weather_setup import save_place
            save_place(ADDON, row["country"], row["query"], value, row["postal"])
            try:
                from weather import refresh
                refresh(force=True)
            except Exception:
                pass
            self.close_subpage()
            return
        if row["kind"] == "secret":
            action = str(value)
            if action == "Remove key":
                ADDON.setSetting(row["id"], "")
                self.close_subpage()
                return
            entered = themed_dialog().input(
                row["label"], type=xbmcgui.INPUT_ALPHANUM,
                option=xbmcgui.ALPHANUM_HIDE_INPUT
            )
            if entered.strip():
                ADDON.setSetting(row["id"], entered.strip())
            self.close_subpage()
            return
        if row["kind"] == "kodi":
            from setup_profile import rpc
            rpc("Settings.SetSettingValue", {"setting": row["id"], "value": value})
            self.close_subpage()
            return

    def onClick(self, control_id):
        if control_id == 100:
            if self.subpage:
                return
            position = self.getControl(100).getSelectedPosition()
            self.load_category(position)
            if self.rows:
                self.setFocusId(200)
            return
        if control_id != 200:
            return
        position = self.getControl(200).getSelectedPosition()
        if self.subpage:
            self.apply_subpage(position)
            return
        if not 0 <= position < len(self.rows):
            return
        row = self.rows[position]
        changed = False
        if row["kind"] == "bool":
            _set_bool(row)
            changed = True
        elif row["kind"] == "enum":
            self.open_enum(row)
            return
        elif row["kind"] == "choice":
            self.open_choice(row)
            return
        elif row["kind"] == "secret":
            self.open_secret(row)
            return
        elif row["kind"] == "kodi":
            self.open_kodi(row)
            return
        elif row["kind"] == "text":
            changed = _set_text(row)
        elif row["kind"] == "action":
            run_action(row["action"], self)
            changed = True
        if changed and row.get("id", "").startswith("ui_"):
            self.appearance_changed = True
        try:
            visible = self.isVisible()
        except Exception:
            visible = True
        if visible:
            self.refresh_rows()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in BACK:
            if self.subpage:
                self.close_subpage()
            elif self.getFocusId() == 200:
                self.setFocusId(100)
            else:
                self.close()
            return
        if self.subpage:
            return
        if action_id == 1 and self.getFocusId() == 200:
            self.setFocusId(100)
            return
        if action_id == 2 and self.getFocusId() == 100:
            position = self.getControl(100).getSelectedPosition()
            self.load_category(position)
            if self.rows:
                self.setFocusId(200)


def show():
    window = themed_window(
        SettingsWindow, "script-stremio-settings.xml",
        ADDON.getAddonInfo("path"), "Main", "1080i"
    )
    window.doModal()
    result = {
        "appearance_changed": window.appearance_changed,
        "request_page": window.request_page,
    }
    del window
    return result
