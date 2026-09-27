"""Addon-owned, reversible fullscreen Back-to-stop keymap."""
from pathlib import Path

KEYMAP = '''<keymap>
  <FullscreenVideo>
    <keyboard><escape>Stop</escape><backspace>Stop</backspace><browser_back>Stop</browser_back></keyboard>
    <remote><back>Stop</back></remote>
    <joystick profile="game.controller.default"><b>Stop</b></joystick>
  </FullscreenVideo>
</keymap>
'''


def write_keymap(directory, enabled):
    target = Path(directory) / 'zz-stremio-for-kodi-back.xml'
    if enabled:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_text() == KEYMAP:
            return False
        target.write_text(KEYMAP)
        return True
    if target.exists():
        target.unlink()
        return True
    return False


def apply():
    import xbmc
    import xbmcvfs
    from addon_state import get_addon
    if write_keymap(xbmcvfs.translatePath('special://profile/keymaps/'),
                    get_addon().getSetting('playback_back_stops') != 'false'):
        xbmc.executebuiltin('Action(ReloadKeymaps)')
