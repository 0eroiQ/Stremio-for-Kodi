"""Stremio for Kodi program entry."""
import sys
from pathlib import Path
_CORE = Path(__file__).resolve().parent / 'core'
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))


def main():
    from lib.playback_settings import apply
    from lib.error_report import show_reporting_notice_once
    apply()
    show_reporting_notice_once()
    if 'cache_configure' in sys.argv[1:]:
        from lib.maintenance import configure_cache
        configure_cache()
    elif 'cache_clear_selected' in sys.argv[1:]:
        from lib.maintenance import clear_selected
        clear_selected()
    elif any(arg in ('cache_info', 'cache_clear') for arg in sys.argv[1:]):
        from lib.maintenance import cache_action
        cache_action('cache_clear' in sys.argv[1:])
    elif 'import_mdblist' in sys.argv[1:]:
        from lib.mdblist import import_nimbus_key
        import_nimbus_key()
    elif any(arg in ('weather_setup', 'weather_country', 'weather_postcode', 'weather_city') for arg in sys.argv[1:]):
        from lib.weather_setup import configure_weather
        action = next((arg[8:] for arg in sys.argv[1:] if arg.startswith('weather_')), 'menu')
        configure_weather('menu' if action == 'setup' else action)
    elif 'locale' in sys.argv[1:]:
        from lib.settings import locale_menu
        locale_menu()
    elif 'report_last_error' in sys.argv[1:]:
        from lib.error_report import report_last_error
        report_last_error()
    elif 'report_issue' in sys.argv[1:]:
        from lib.error_report import manual_report
        manual_report()
    elif 'premium_status' in sys.argv[1:]:
        from lib.vortexo_premium import show_status
        show_status()
    elif 'premium_buy' in sys.argv[1:]:
        from lib.vortexo_premium import show_purchase
        show_purchase()
    else:
        from lib.app import run
        run()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        from lib.error_report import handle_error
        handle_error('Program entry', error, 'Stremio for Kodi stopped unexpectedly.')
