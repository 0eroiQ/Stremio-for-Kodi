"""Stremio for Kodi program entry."""
import sys


def main():
    from lib.playback_settings import apply
    from lib.error_report import show_reporting_notice_once
    apply()
    show_reporting_notice_once()
    if any(arg in ('cache_info', 'cache_clear') for arg in sys.argv[1:]):
        from lib.maintenance import cache_action
        cache_action('cache_clear' in sys.argv[1:])
    elif 'import_mdblist' in sys.argv[1:]:
        from lib.mdblist import import_nimbus_key
        import_nimbus_key()
    elif 'locale' in sys.argv[1:]:
        from lib.settings import locale_menu
        locale_menu()
    elif 'report_issue' in sys.argv[1:]:
        from lib.error_report import manual_report
        manual_report()
    elif 'premium_status' in sys.argv[1:]:
        from lib.vortexo_premium import show_status
        show_status()
    else:
        from lib.app import run
        run()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        from lib.error_report import handle_error
        handle_error('Program entry', error, 'Stremio for Kodi stopped unexpectedly.')
