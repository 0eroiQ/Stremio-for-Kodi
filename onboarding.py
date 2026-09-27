"""First-run link sign-in. Only official account endpoints receive credentials."""
import time
import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcgui
import xbmcvfs
from account import AccountError, Store, create_link_details, read_link, pull_addons, pull_library, library_rows
from addons_core import merge_account


def run():
    home = xbmcgui.Window(10000)
    if home.getProperty('StremioOnboardingBusy'):
        return
    home.setProperty('StremioOnboardingBusy', '1')
    home.clearProperty('StremioOnboardingCancel')
    monitor = xbmc.Monitor()
    def cancelled():
        return monitor.abortRequested() or bool(home.getProperty('StremioOnboardingCancel'))
    def status(message):
        home.setProperty('StremioOnboardingStatus', message)
    try:
        for key in ('Ready', 'Link', 'QR'):
            home.clearProperty('StremioOnboarding' + key)
        store = Store(xbmcvfs.translatePath(get_addon().getAddonInfo('profile')))
        state = store.load()
        if not state.get('token'):
            status('Creating a secure Stremio sign-in link...')
            code, link, qr = create_link_details()
            home.setProperty('StremioOnboardingLink', link)
            home.setProperty('StremioOnboardingQR', qr)
            status('Scan the QR code or open the link on your phone. Waiting for sign-in...')
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                if cancelled():
                    return
                token = read_link(code)
                if cancelled():
                    return
                if token:
                    state['token'] = token
                    state.setdefault('addons', [])
                    store.save(state)
                    break
                if monitor.waitForAbort(3):
                    return
            else:
                status('This link expired. Go back and select Connect Stremio to try again.')
                return
        home.clearProperty('StremioOnboardingQR')
        home.clearProperty('StremioOnboardingLink')
        status('Connected. Importing your addons and library...')
        account_addons, skipped = pull_addons(state['token'])
        state['addons'] = merge_account(state, account_addons)
        if cancelled():
            return
        store.save(state)
        state['library'] = pull_library(state['token'])
        if cancelled():
            return
        store.save(state)
        status('Preparing your Bingie Home and safe playback defaults...')
        from setup_profile import prepare
        prepare(store.directory, xbmcvfs.translatePath(get_addon().getAddonInfo('path')))
        if cancelled():
            return
        status('Your account is ready. {} addons, {} library titles, {} Continue Watching. {} unsupported addons skipped.'.format(
            len(state['addons']), len(library_rows(state['library'])), len(library_rows(state['library'], True)), skipped))
        home.setProperty('StremioOnboardingReady', '1')
        for flag in ('StremioHomeDefaults', 'StremioOnboardingDone', 'BingieFirstStartupDone', 'BingieSecondStartupDone'):
            xbmc.executebuiltin('Skin.SetBool({})'.format(flag))
        xbmc.executebuiltin('ClearProperty(StartupMask,Home)')
        xbmc.executebuiltin('ReplaceWindow(Home)')
        xbmc.executebuiltin('ReloadSkin()')
    except AccountError:
        status('Could not finish connecting. Go back and retry. Any imported data was kept.')
    except Exception:
        status('Setup could not finish. Go back and retry.')
    finally:
        home.clearProperty('StremioOnboardingBusy')
        if cancelled():
            home.clearProperty('StremioOnboardingQR')
            home.clearProperty('StremioOnboardingLink')


if __name__ == '__main__':
    run()
