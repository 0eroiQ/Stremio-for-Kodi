"""Stremio for Kodi program entry."""
import sys

if __name__ == '__main__':
    if 'import_mdblist' in sys.argv[1:]:
        from lib.mdblist import import_nimbus_key
        import_nimbus_key()
    elif 'locale' in sys.argv[1:]:
        from lib.settings import locale_menu
        locale_menu()
    else:
        from lib.app import run
        run()
