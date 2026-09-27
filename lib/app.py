import xbmcaddon
from addon_state import get_addon
import xbmcgui
from lib.settings import load_setup, save_setup
from lib.nimbus import HomeWindow

ADDON = get_addon()
ADDON_PATH = ADDON.getAddonInfo('path')
SKIN = 'Main'
RES = '1080i'


def run():
    from lib.signin import signed_in, show_signin
    if not signed_in() and not show_signin():
        return
    window = HomeWindow('script-stremio-nimbus.xml', ADDON_PATH, SKIN, RES)
    window.doModal()
    del window
