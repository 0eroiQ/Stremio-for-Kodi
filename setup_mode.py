"""Coordinate Stremio for Kodi onboarding modes without exposing Kodi UI."""
import sys
from pathlib import Path
import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcvfs
from account import Store

ADDON = get_addon()
PROFILE = Path(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')))
OWNED_STORES = ('', 'streams', 'playback', 'subtitle-results', 'community', 'setup')
ONBOARDING_FLAGS = ('StremioHomeDefaults', 'StremioOnboardingDone', 'BingieFirstStartupDone', 'BingieSecondStartupDone')


def skin_bool(name, enabled):
    xbmc.executebuiltin(('Skin.SetBool(' if enabled else 'Skin.Reset(') + name + ')')


def clean_stremio_state():
    for folder in OWNED_STORES:
        Store(PROFILE / folder).forget()
    for flag in ONBOARDING_FLAGS:
        xbmc.executebuiltin('Skin.Reset(' + flag + ')')


def apply(mode):
    if mode not in ('clean', 'keep', 'advanced', 'developer'):
        raise ValueError('Unknown setup mode')
    if mode in ('clean', 'advanced', 'developer'):
        clean_stremio_state()
    skin_bool('StremioAdvancedPlayback', mode in ('advanced', 'developer'))
    skin_bool('StremioDeveloperMode', mode == 'developer')
    xbmc.executebuiltin('Skin.SetString(StremioSetupMode,' + mode + ')')
    xbmc.executebuiltin('ReplaceWindow(1193)')


if __name__ == '__main__':
    apply(sys.argv[1] if len(sys.argv) > 1 else 'clean')
