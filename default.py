"""Stremio for Kodi program entry."""
import sys

if __name__ == '__main__':
    if 'locale' in sys.argv[1:]:
        from lib.settings import locale_menu
        locale_menu()
    else:
        from lib.app import run
        run()
