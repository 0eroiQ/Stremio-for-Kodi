from addon_state import get_addon
import xbmcgui
from lib.nimbus import HomeWindow

ADDON = get_addon()
ADDON_PATH = ADDON.getAddonInfo('path')
SKIN = 'Main'
RES = '1080i'
SESSION_WINDOW_ID = 10000
APP_RUNNING = 'stremioforkodi.running'


def run():
    session = xbmcgui.Window(SESSION_WINDOW_ID)
    if session.getProperty(APP_RUNNING) == 'true':
        return
    session.setProperty(APP_RUNNING, 'true')
    try:
        from lib.signin import signed_in, show_signin
        if not signed_in() and not show_signin():
            return
        import xbmcvfs
        from lib import backend
        from lib.home_layout import build_layout
        from lib.appearance import options
        progress = xbmcgui.DialogProgressBG()
        progress.create('Stremio for Kodi', 'Loading your account catalogs…')
        try:
            rows = backend.account_home()
            filename, path, count = build_layout(
                ADDON_PATH,
                xbmcvfs.translatePath(ADDON.getAddonInfo('profile')),
                max(8, len(rows)),
                options(ADDON)
            )
        finally:
            progress.close()
        while True:
            window = HomeWindow(filename, path, SKIN, RES, account_rows=rows, row_count=count)
            window.doModal()
            reload_appearance = getattr(window, 'reload_appearance', False)
            del window
            if not reload_appearance:
                break
            filename, path, count = build_layout(
                ADDON_PATH, xbmcvfs.translatePath(ADDON.getAddonInfo('profile')),
                max(8, len(rows)), options(ADDON))
    finally:
        session.clearProperty(APP_RUNNING)
