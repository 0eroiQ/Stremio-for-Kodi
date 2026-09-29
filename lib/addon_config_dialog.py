"""Theme-owned configuration dialog with offline QR and explicit account pull."""
import threading
from pathlib import Path
import xbmcgui
from lib.addon_config import ConfigureError, public_site, write_qr, remove_qr, sync_addons

BACK, REFRESH, SYNC, DONE = 1, 2, 3, 4


class ConfigureWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.entry = kwargs.pop('entry')
        self.changed = False
        self.selected_identity = self.entry.get('id')
        self._initialized = False
        self._busy = False
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._qr_paths = []
        super().__init__(*args, **kwargs)

    def onInit(self):
        if self._initialized:
            return
        self._initialized = True
        from addons_ui import plain
        manifest = self.entry.get('manifest') or {}
        self.setProperty('config_name', plain(manifest.get('name') or 'Stremio addon', 100))
        self.setProperty('config_version', 'v' + plain(manifest.get('version') or '', 40))
        self.setProperty('config_icon', manifest.get('logo') or 'DefaultAddon.png')
        self.setProperty('config_help', '1. Scan with your phone.\n2. Save / install the configuration in the same Stremio account.\n3. Choose Sync addons to fetch changes.\n\nDone syncs and closes. Back closes only.')
        self.refresh_qr()
        self.setFocusId(BACK)

    def refresh_qr(self):
        if self._cancel.is_set() or self._busy:
            return
        self.setProperty('config_status', 'Creating QR code on this device...')
        try:
            from lib import backend as api
            import xbmcvfs
            self.setProperty('config_site', public_site(self.entry))
            profile = Path(xbmcvfs.translatePath(api.CORE.getAddonInfo('profile')))
            path = write_qr(self.entry, profile / 'temp' / 'configure-dialog')
            self._qr_paths.append(path)
            # Unique path and disabled image caching prevent stale/private QRs.
            self.getControl(101).setImage(str(path), False)
            self.setProperty('config_has_qr', 'true')
            self.setProperty('config_status', 'QR ready. Scan with your phone to open the addon website.')
        except ConfigureError as error:
            self.clearProperty('config_has_qr')
            self.setProperty('config_status', str(error))
        except Exception:
            self.clearProperty('config_has_qr')
            self.setProperty('config_status', 'QR unavailable. Select Refresh QR to try again.')
        while len(self._qr_paths) > 2:
            remove_qr(self._qr_paths.pop(0))

    def _commit(self, operation):
        with self._lock:
            if self._cancel.is_set():
                raise ConfigureError('Sync cancelled. Existing addons were kept.')
            return operation()

    def start_sync(self, close_after=False):
        with self._lock:
            if self._busy or self._cancel.is_set():
                return
            self._busy = True
            self.setProperty('config_busy', 'true')
            self.setProperty('config_status', 'Syncing addons from your Stremio account...')
            self.setFocusId(BACK)
        def worker():
            try:
                from lib import backend as api
                result = sync_addons(api.STORE, self.entry,
                                     cancelled=self._cancel.is_set, commit=self._commit)
                with self._lock:
                    if self._cancel.is_set():
                        return
                    self.changed = self.changed or result['changed']
                    if result['entry']:
                        self.entry = result['entry']
                        self.selected_identity = self.entry.get('id')
                    self._busy = False
                    self.clearProperty('config_busy')
                    self.refresh_qr()
                    message = ('Synced {} addons from Stremio.' if result['changed'] else
                               'Already up to date: {} addons. No new configuration was found.').format(result['account_count'])
                    if not result['entry']:
                        message += ' This addon is no longer in the collection.'
                    self.setProperty('config_status', message)
                    if close_after:
                        self.close()
                    else:
                        self.setFocusId(DONE)
            except Exception as error:
                with self._lock:
                    if self._cancel.is_set():
                        return
                    self._busy = False
                    self.clearProperty('config_busy')
                    self.setProperty('config_status', str(error) if isinstance(error, ConfigureError)
                                     else 'Sync failed. Existing addons were kept. Please retry.')
                    self.setFocusId(SYNC)
        try:
            self._worker = threading.Thread(target=worker, daemon=True)
            self._worker.start()
        except RuntimeError:
            self._busy = False
            self.clearProperty('config_busy')
            self.setProperty('config_status', 'Sync could not start. Select Sync addons to retry.')

    def onClick(self, cid):
        if cid == BACK:
            self.close()
        elif cid == REFRESH:
            self.refresh_qr()
        elif cid in (SYNC, DONE):
            self.start_sync(close_after=cid == DONE)

    def onAction(self, action):
        if action.getId() in (10, 92, 216, 247):
            self.close()

    def dispose(self):
        with self._lock:
            self._cancel.set()
            try:
                self.getControl(101).setImage('', False)
            except Exception:
                pass
            for path in self._qr_paths:
                remove_qr(path)
            self._qr_paths.clear()

    def close(self):
        self.dispose()
        super().close()
