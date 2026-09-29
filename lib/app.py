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
    from lib.launch_guard import LaunchGuard, mark_window, unmark_window
    guard = LaunchGuard()
    if not guard.acquire():
        return
    try:
        from lib.signin import signed_in, show_signin
        if not signed_in() and not show_signin():
            return
        import xbmcvfs
        from lib import backend
        from lib.home_layout import build_layout
        from lib.appearance import options
        # Startup is stale-while-revalidate: never hold the UI behind catalog
        # network requests. HomeWindow refreshes account/catalog data in background.
        rows = backend.account_home(False)
        filename, path, count = build_layout(
            ADDON_PATH,
            xbmcvfs.translatePath(ADDON.getAddonInfo('profile')),
            max(8, len(rows), backend.account_home_capacity()),
            options(ADDON)
        )
        while True:
            window = HomeWindow(filename, path, SKIN, RES, account_rows=rows, row_count=count)
            mark_window(window, 'home')
            try:
                window.doModal()
                reload_appearance = getattr(window, 'reload_appearance', False)
            finally:
                unmark_window(window)
                del window
            if not reload_appearance:
                break
            filename, path, count = build_layout(
                ADDON_PATH, xbmcvfs.translatePath(ADDON.getAddonInfo('profile')),
                max(8, len(rows), backend.account_home_capacity()), options(ADDON))
    finally:
        guard.release()
