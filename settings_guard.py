"""Hide the native Add-ons category in the appliance's System screen.

Kodi creates category buttons dynamically (-200 onward), so removing an item
from Settings.xml alone does not affect them. This is UI protection only.
"""
import xbmc
import xbmcgui


def blocked(label, translated):
    return label.strip().casefold() in {translated.strip().casefold(), 'add-ons', 'addons'}


def main():
    monitor = xbmc.Monitor()
    while xbmc.getCondVisibility('Window.IsActive(SystemSettings)'):
        window = xbmcgui.Window(xbmcgui.getCurrentWindowId())
        for identity in range(-200, -180):
            try:
                control = window.getControl(identity)
                if blocked(control.getLabel(), xbmc.getLocalizedString(24001)):
                    if window.getFocusId() == identity:
                        window.setFocusId(-200)
                    control.setEnabled(False)
                    control.setVisible(False)
            except (RuntimeError, AttributeError):
                continue
        if monitor.waitForAbort(0.25):
            break


if __name__ == '__main__':
    main()
