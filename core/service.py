"""Early Kodi startup launcher for Stremio for Kodi.

Kodi initializes its active skin before Python services are scheduled, so this
cannot run literally before skin initialization. It launches the addon at the
earliest supported service point and uses a per-Kodi-session guard to avoid
duplicate launches.
"""
import xbmc
import xbmcgui

from addon_state import get_addon

ADDON = get_addon()
SESSION_WINDOW_ID = 10000
STARTUP_LAUNCHED = "stremioforkodi.startup.launched"
APP_RUNNING = "stremioforkodi.running"
DELAYS = (0, 1, 2, 3, 5)


def configured_delay():
    try:
        index = int(ADDON.getSetting("startup_delay") or "0")
    except (TypeError, ValueError):
        index = 0
    return DELAYS[index] if 0 <= index < len(DELAYS) else 0


def main():
    if ADDON.getSetting("startup_autostart") != "true":
        return

    monitor = xbmc.Monitor()
    session = xbmcgui.Window(SESSION_WINDOW_ID)

    # Run only once per Kodi process, even if the service is restarted after an
    # addon update. Manual launches remain available normally.
    if session.getProperty(STARTUP_LAUNCHED) == "true":
        return
    session.setProperty(STARTUP_LAUNCHED, "true")

    delay = configured_delay()
    if delay and monitor.waitForAbort(delay):
        return
    if monitor.abortRequested() or session.getProperty(APP_RUNNING) == "true":
        return

    xbmc.executebuiltin("RunScript(script.stremioelec,startup)")


if __name__ == "__main__":
    main()
