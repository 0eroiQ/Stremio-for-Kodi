"""Account-link welcome window; never treats setup completion as authentication."""
import threading
import time
import xbmc
import xbmcgui
import xbmcvfs
from addon_state import get_addon
from account import Store, create_link_details, read_link, pull_user_id, pull_addons, pull_library
from addons_core import merge_account


def account_store():
    return Store(xbmcvfs.translatePath(get_addon().getAddonInfo('profile')))


def signed_in():
    token = account_store().load().get('token')
    return isinstance(token, str) and bool(token.strip())


class WelcomeWindow(xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cancel = threading.Event()
        self.refresh = threading.Event()
        self.worker = None
        self.authenticated = False
        self.last_error = None

    def onInit(self):
        self.setFocusId(103)
        self.start_link()

    def label(self, cid, text):
        if not self.cancel.is_set():
            control = self.getControl(cid)
            if cid == 112:
                control.setText(text)
            else:
                control.setLabel(text)

    def start_link(self):
        if self.worker and self.worker.is_alive():
            return
        self.cancel.clear()
        self.worker = threading.Thread(target=self.link_account, daemon=True)
        self.worker.start()

    def link_account(self):
        self.last_error = None
        try:
            self.label(110, 'Creating a sign-in link…')
            self.label(111, '')
            self.getControl(120).setImage('')
            code, link, qr = create_link_details()
            if self.cancel.is_set() or self.refresh.is_set():
                return
            self.getControl(120).setImage(qr)
            self.label(110, link)
            self.label(112, '1. Scan the QR code or open the link on your phone.\n2. Log in to your Stremio account.')
            deadline = time.monotonic() + 300
            monitor = xbmc.Monitor()
            next_poll = 0
            while not self.cancel.is_set() and not self.refresh.is_set() and not monitor.abortRequested():
                remaining = max(0, int(deadline - time.monotonic()))
                self.label(111, 'Expires in {:02d}:{:02d}'.format(*divmod(remaining, 60)))
                if remaining == 0:
                    self.label(111, 'Link expired. Request a new link.')
                    self.getControl(120).setImage('')
                    return
                if time.monotonic() >= next_poll:
                    token = read_link(code)
                    if self.cancel.is_set() or self.refresh.is_set():
                        return
                    if token:
                        store = account_store()
                        state = store.load()
                        state['token'] = token
                        store.save(state)
                        self.label(111, 'Connected. Importing your library and add-ons…')
                        try:
                            # The UID is the only Stremio profile field we persist. Premium will
                            # later use the same verified identity on Kodi and the website.
                            state['uid'] = pull_user_id(token)
                            store.save(state)
                            addons, _ = pull_addons(token)
                            state['addons'] = merge_account(state, addons)
                            store.save(state)
                            state['library'] = pull_library(token)
                            store.save(state)
                        except Exception:
                            # Authentication succeeded; identity/sync failures must not invent a logout.
                            xbmc.log('Stremio for Kodi: account linked; initial identity/sync incomplete', xbmc.LOGWARNING)
                        if not self.cancel.is_set():
                            self.authenticated = True
                            self.close()
                        return
                    next_poll = time.monotonic() + 3
                self.cancel.wait(0.25)
        except Exception as error:
            self.last_error = error
            self.label(111, 'Unable to connect. Preparing an anonymous error report…')
            self.close()

        finally:
            if self.refresh.is_set() and not self.cancel.is_set():
                self.refresh.clear()
                self.worker = threading.Thread(target=self.link_account, daemon=True)
                self.worker.start()

    def onClick(self, cid):
        if cid == 103:
            if self.worker and self.worker.is_alive():
                self.refresh.set()
            else:
                self.start_link()
        elif cid == 104:
            self.close()

    def onAction(self, action):
        if action.getId() in (10, 92, 216, 247):
            self.close()

    def close(self):
        self.cancel.set()
        super().close()


def show_signin():
    window = WelcomeWindow('script-stremio-welcome.xml', get_addon().getAddonInfo('path'), 'Main', '1080i')
    try:
        window.doModal()
        authenticated = window.authenticated
        error = window.last_error
        if error is not None and not authenticated:
            from lib.error_report import handle_error
            handle_error('Stremio sign-in', error, 'Stremio sign-in failed on this device.')
        return authenticated
    finally:
        window.cancel.set()
