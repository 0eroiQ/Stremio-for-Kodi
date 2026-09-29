"""Single-instance launch recovery, without persistent locks or new threads.

A live Kodi-owned lease window protects startup. Window existence, not a stale
Home property, is authoritative. Hidden addon windows are brought forward.
"""
import uuid

RUNNING = 'stremioforkodi.running'
TOKEN = 'stremioforkodi.launch.token'
OWNER = 'stremioforkodi.window.owner'
ROLE = 'stremioforkodi.window.role'
ADDON_ID = 'script.stremioelec'


def mark_window(window, role):
    window.setProperty(OWNER, ADDON_ID)
    window.setProperty(ROLE, role)


def unmark_window(window):
    if window is not None:
        try:
            window.clearProperty(OWNER)
            window.clearProperty(ROLE)
        except Exception:
            pass

class LaunchGuard:
    def __init__(self, gui=None, kodi=None):
        if gui is None:
            import xbmcgui as gui
        if kodi is None:
            import xbmc as kodi
        self.gui, self.kodi = gui, kodi
        self.session = gui.Window(10000)
        self.lease = None
        self.token = ''

    def _windows(self):
        legacy = self.session.getProperty(RUNNING) == 'true'
        found = []
        for identity in range(13000, 13200):
            try:
                window = self.gui.Window(identity)
                owner = window.getProperty(OWNER)
                role = window.getProperty(ROLE) if owner == ADDON_ID else ''
                if not owner and legacy and window.getProperty('first_row'):
                    page = window.getProperty('page')
                    if page in ('Home', 'Discover', 'Library', 'Addons') or page.startswith('Search:'):
                        window.getControl(9000)  # Verify the legacy Stremio sidebar.
                        role = 'home'
                if role in ('home', 'info', 'signin', 'lease'):
                    found.append((identity, role))
            except Exception:
                continue
        return found

    def acquire(self):
        windows = self._windows()
        views = [(wid, role) for wid, role in windows if role != 'lease']
        if views:
            if not any(self.kodi.getCondVisibility('Window.IsActive({})'.format(wid))
                       for wid, role in views):
                rank = {'home': 0, 'signin': 1, 'info': 2}
                wid, _ = max(views, key=lambda pair: (rank[pair[1]], pair[0]))
                self.kodi.executebuiltin('ActivateWindow({})'.format(wid))
            return False
        if windows:
            self.gui.Dialog().notification('Stremio for Kodi',
                'The addon is still loading. Please wait.', time=3000)
            return False
        # An orphan running flag is not a live instance. Start a fresh owner.
        self.lease = self.gui.Window()
        mark_window(self.lease, 'lease')
        self.token = uuid.uuid4().hex
        self.session.setProperty(TOKEN, self.token)
        self.session.setProperty(RUNNING, 'true')
        return True

    def release(self):
        if self.token and self.session.getProperty(TOKEN) == self.token:
            self.session.clearProperty(RUNNING)
            self.session.clearProperty(TOKEN)
        unmark_window(self.lease)
        self.lease = None
