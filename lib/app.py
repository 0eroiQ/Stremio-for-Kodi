import xbmcaddon
from addon_state import get_addon
import xbmcgui
from lib.settings import load_setup, save_setup
from lib.windows import WelcomeWindow
from lib.nimbus import HomeWindow

ADDON = get_addon()
ADDON_PATH = ADDON.getAddonInfo('path')
SKIN = 'Main'
RES = '1080i'


def run():
    setup = load_setup()
    if not setup.get('welcome_done'):
        window = WelcomeWindow('script-stremio-welcome.xml', ADDON_PATH, SKIN, RES)
        window.doModal()
        del window
        setup = load_setup()
        if not setup.get('welcome_done'):
            return
    window = HomeWindow('script-stremio-nimbus.xml', ADDON_PATH, SKIN, RES)
    window.doModal()
    del window
