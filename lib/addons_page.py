"""Installed addon page interactions in Kodi."""
from lib.ui_dialogs import progress_bg as themed_progress_bg, dialog as themed_dialog
from lib.addons_layout import build
from lib.theme import window as themed_window

def short_description(value):
    from addons_ui import plain
    text = plain(value, 900)
    return text if len(text) <= 150 else text[:147].rsplit(' ', 1)[0] + '…'


class AddonsPage:
    def load_addons(self, identity=None):
        import xbmcgui
        from lib import backend as api
        from addons_ui import plain
        from addons_core import configuration_state
        self.cancel_trailer()
        self.hero_key = None
        self.hero_request = None
        self.set_hero({})
        self.setProperty('page', 'Addons')
        self.setProperty('next_row', '')
        self.report('')
        state = api.STORE.load()
        self.addon_entries = list(state.get('addons', []))
        disabled = set(state.get('disabledAddons', []))
        listing = self.getControl(9300)
        old_pos = max(0, listing.getSelectedPosition())
        listing.reset()
        for entry in self.addon_entries:
            manifest = entry.get('manifest') or {}
            li = xbmcgui.ListItem(plain(manifest.get('name') or 'Stremio addon', 120))
            li.setArt({'thumb': manifest.get('logo') or 'DefaultAddon.png'})
            config = configuration_state(manifest)
            status = 'Disabled' if entry.get('id') in disabled else ('Setup required' if config['required'] else 'Enabled')
            for key, value in {'version':'v'+str(manifest.get('version') or '—'),
                               'types':' · '.join(str(t).title() for t in manifest.get('types', [])),
                               'description':short_description(manifest.get('description')),
                               'status':status}.items():
                li.setProperty(key, value)
            listing.addItem(li)
        count = len(self.addon_entries)
        enabled = sum(e.get('id') not in disabled for e in self.addon_entries)
        self.setProperty('addons_summary', 'Installed  ·  {} addons  ·  {} enabled on this device'.format(count, enabled))
        self.setProperty('addons_empty', '' if count else 'No Stremio addons installed. Choose + Add addon to install from a manifest URL, or connect your account in Settings.')
        self.setProperty('first_row', '9300' if count else '9304')
        self.setProperty('addons_list_focus', '9300' if count else '9304')
        if count:
            pos = next((i for i,e in enumerate(self.addon_entries) if e.get('id') == identity), min(old_pos,count-1))
            listing.selectItem(pos)
        self.update_addon_selection()
        self.setFocusId(9300 if count else 9304)

    def update_addon_selection(self):
        from lib import backend as api
        from addons_core import configuration_state
        from addons_ui import plain
        entries = getattr(self, 'addon_entries', [])
        pos = self.getControl(9300).getSelectedPosition()
        entry = entries[pos] if 0 <= pos < len(entries) else None
        manifest = entry.get('manifest', {}) if entry else {}
        self.setProperty('addon_selected', plain(manifest.get('name'),120))
        self.setProperty('addon_configurable', 'true' if entry and any(configuration_state(manifest)[k] for k in ('configurable','required')) else '')
        disabled = api.STORE.load().get('disabledAddons', [])
        self.setProperty('addon_toggle', 'Enable' if entry and entry.get('id') in disabled else 'Disable')

    def addon_click(self, cid):
        import xbmcgui
        from lib import backend as api
        from addons_core import remove_local, set_enabled, configuration_state
        if cid == 9304:
            window = themed_window(AddWindow, 'stremio-addon-add.xml', api.CORE.getAddonInfo('path'), 'Main', '1080i')
            window.doModal()
            identity = window.installed_identity
            del window
            self.load_addons(identity)
            if identity is None:
                self.setFocusId(9304)
            return
        if cid == 9300:
            self.setFocusId(9301)
            return
        pos = self.getControl(9300).getSelectedPosition()
        entries = getattr(self, 'addon_entries', [])
        if not 0 <= pos < len(entries):
            return
        identity = entries[pos].get('id')
        state = api.STORE.load()
        entry = next((e for e in state.get('addons', []) if e.get('id') == identity), None)
        if entry is None:
            self.load_addons()
            return
        if cid == 9302:
            config = configuration_state(entry.get('manifest', {}))
            if config['configurable'] or config['required']:
                window = themed_window(ConfigureWindow, 'stremio-addon-config.xml', api.CORE.getAddonInfo('path'), 'Main', '1080i', entry=entry)
                try:
                    window.doModal()
                    changed = window.changed
                    selected_identity = window.selected_identity
                finally:
                    window.dispose()
                if changed:
                    self.load_addons(selected_identity)
                else:
                    self.update_addon_selection()
                self.setFocusId(9300 if self.addon_entries else 9304)
                del window
            return
        if cid == 9301:
            set_enabled(state, identity, identity in state.get('disabledAddons', []))
        elif cid == 9303:
            if not themed_dialog().yesno('Remove from this device?',
                    'Remove '+entry.get('manifest', {}).get('name','this addon')+'? Your Stremio account and other devices are unchanged.'):
                return
            remove_local(state, identity)
        api.STORE.save(state)
        self.load_addons(identity)


import xbmcgui
from lib.addon_config_dialog import ConfigureWindow


class AddWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.url = ''
        self.installed_identity = None
        super().__init__(*args, **kwargs)

    def onInit(self):
        if not self.url:
            self.setProperty('addon_url_label', 'Paste addon URL')
        self.setFocusId(1)

    def onClick(self, cid):
        if cid == 3:
            self.close()
        elif cid == 1:
            value = themed_dialog().input('Paste addon manifest URL', defaultt=self.url, type=xbmcgui.INPUT_ALPHANUM)
            if value.strip():
                self.url = value.strip()
                # Configured URLs may contain credentials; keep them out of the page preview.
                self.setProperty('addon_url_label', 'Manifest URL entered — select to edit')
                self.setProperty('add_error', '')
                self.setFocusId(2)
        elif cid == 2:
            from addons_core import install_local, normalize_manifest_url, configuration_state
            from lib import backend as api
            if not self.url:
                self.setProperty('add_error', 'Enter an addon manifest URL first.')
                self.setFocusId(1)
                return
            progress = themed_progress_bg()
            try:
                url = normalize_manifest_url(self.url)
                progress.create('Add addon', 'Reading addon manifest…')
                state = api.STORE.load()
                descriptor = install_local(state, url)
                if configuration_state(descriptor['manifest'])['required']:
                    self.setProperty('add_error', 'This addon needs configuration. Configure it first, then paste the configured manifest URL.')
                    progress.close()
                    window = themed_window(ConfigureWindow, 'stremio-addon-config.xml', api.CORE.getAddonInfo('path'), 'Main', '1080i', entry=descriptor)
                    try:
                        window.doModal()
                    finally:
                        window.dispose()
                    del window
                    return
                api.STORE.save(state)
                self.installed_identity = descriptor['id']
                self.close()
            except Exception:
                self.setProperty('add_error', 'Unable to add addon. Use a valid HTTPS or stremio:// link ending in /manifest.json.')
            finally:
                progress.close()

    def onAction(self, action):
        if action.getId() in (10,92,216,247):
            self.close()
