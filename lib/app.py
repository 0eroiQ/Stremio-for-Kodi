from addon_state import get_addon
import xbmcgui
from lib.nimbus import HomeWindow

ADDON = get_addon()
ADDON_PATH = ADDON.getAddonInfo('path')
SKIN = 'Main'
RES = '1080i'


def run():
    from lib.signin import signed_in, show_signin
    if not signed_in() and not show_signin():
        return
    import xbmcvfs
    from lib import backend
    from lib.home_layout import build_layout
    progress = xbmcgui.DialogProgressBG()
    progress.create('Stremio for Kodi', 'Loading your account catalogs…')
    try:
        rows = backend.account_home()
        filename, path, count = build_layout(ADDON_PATH, xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), max(8, len(rows)))
    finally:
        progress.close()
    window = HomeWindow(filename, path, SKIN, RES, account_rows=rows, row_count=count)
    window.doModal()
    del window
