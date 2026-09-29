"""TV-friendly Stremio addon manager. Kodi addons remain internal."""
from lib.ui_dialogs import dialog as themed_dialog
import html
import re
import sys
from pathlib import Path

import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcgui
import xbmcvfs

from account import Store, pull_addons
from addons_core import (account_addons, active_addons, community_catalog, configure_url,
                         configuration_state, install_descriptor_local,
                         install_local, mark_account, merge_account, push_account,
                         remove_local, set_enabled)

WINDOW_ID = 1196
CONFIG_WINDOW_ID = 1195
COMMUNITY_WINDOW_ID = 1194
WINDOW_RUNTIME_ID = 11196
CONFIG_WINDOW_RUNTIME_ID = 11195
COMMUNITY_WINDOW_RUNTIME_ID = 11194
ADDON = get_addon()
PROFILE = Path(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')))
STORE = Store(PROFILE)


def publish(status=None):
    state = STORE.load()
    total = len(state.get('addons', []))
    enabled = len(active_addons(state))
    window = xbmcgui.Window(WINDOW_RUNTIME_ID)
    window.setProperty('StremioAddons.Count', str(total))
    window.setProperty('StremioAddons.Enabled', str(enabled))
    window.setProperty('StremioAddons.Status', status or
                       ('Connected to Stremio account' if state.get('token') else 'Local device only'))




def plain(value, limit=900):
    value = re.sub(r'<[^>]*>', ' ', str(value or ''))
    value = html.unescape(value)
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def finish_install(state, descriptor, dialog):
    manifest = descriptor['manifest']
    config = configuration_state(manifest)
    if config['required']:
        show_config(manifest, descriptor['transportUrl'], dialog)
        return False
    if not dialog.yesno('Install Stremio addon?',
            manifest.get('name', 'Stremio addon') + '\n\n' +
            plain(manifest.get('description', ''), 500) +
            '\n\nInstall on this Stremio for Kodi device?'):
        return False
    STORE.save(state)
    if state.get('token') and dialog.yesno('Sync to Stremio account?',
            'Also install this addon in your Stremio account so it appears on your other Stremio devices?'):
        try:
            remote = account_addons(state) + [descriptor]
            push_account(state['token'], remote)
            mark_account(state, descriptor['id'], True)
            STORE.save(state)
        except Exception:
            dialog.ok('Stremio Addons', 'Installed on this device, but the Stremio account update failed.')
    publish('Installed ' + manifest.get('name', 'addon'))
    return True



def refresh_community():
    window = xbmcgui.Window(COMMUNITY_WINDOW_RUNTIME_ID)
    try:
        window.setFocusId(50)
    except Exception:
        pass
    xbmc.executebuiltin('Container.Refresh')


def community_init():
    window = xbmcgui.Window(COMMUNITY_WINDOW_RUNTIME_ID)
    if not window.getProperty('StremioCommunity.Category'):
        window.setProperty('StremioCommunity.Category', 'all')
    if window.getProperty('StremioCommunity.Query') is None:
        window.setProperty('StremioCommunity.Query', '')
    window.setProperty('StremioCommunity.Status', 'Loading Stremio Community Addons…')


def community_filter(category):
    allowed = {'all', 'movies', 'streams', 'subtitles', 'catalogs', 'live'}
    if category not in allowed:
        return
    window = xbmcgui.Window(COMMUNITY_WINDOW_RUNTIME_ID)
    window.setProperty('StremioCommunity.Category', category)
    window.setProperty('StremioCommunity.Query', '')
    window.setProperty('StremioCommunity.Status', 'Loading ' + category + ' addons…')
    refresh_community()


def community_search(dialog):
    window = xbmcgui.Window(COMMUNITY_WINDOW_RUNTIME_ID)
    query = dialog.input('Search Community Addons',
                         defaultt=window.getProperty('StremioCommunity.Query'),
                         type=xbmcgui.INPUT_ALPHANUM).strip()
    if not query:
        return
    window.setProperty('StremioCommunity.Category', 'all')
    window.setProperty('StremioCommunity.Query', query)
    window.setProperty('StremioCommunity.Status', 'Searching for ' + query + '…')
    refresh_community()


def community_selected(row, dialog):
    if not isinstance(row, dict):
        return
    state = STORE.load()
    manifest = row.get('manifest') or {}
    transport_url = row.get('transportUrl', '')
    installed = next((item for item in state.get('addons', [])
                      if item.get('manifest', {}).get('id') == manifest.get('id')), None)
    if installed:
        addon_actions(dialog, installed.get('id'))
        return
    if configuration_state(manifest)['required']:
        show_config(manifest, transport_url, dialog)
        return
    try:
        descriptor = install_descriptor_local(state, transport_url, manifest)
    except Exception:
        dialog.ok('Community Addons', 'This catalog entry is not a supported Stremio addon.')
        return
    finish_install(state, descriptor, dialog)
    refresh_community()

def show_config(manifest, transport_url, dialog):
    url = configure_url(transport_url)
    try:
        import qrcode
        PROFILE.mkdir(parents=True, exist_ok=True)
        path = PROFILE / 'addon-configure-qr.png'
        qrcode.make(url).save(str(path))
        window = xbmcgui.Window(CONFIG_WINDOW_RUNTIME_ID)
        window.setProperty('StremioAddonConfig.Name', manifest.get('name', 'Stremio addon'))
        window.setProperty('StremioAddonConfig.URL', url)
        window.setProperty('StremioAddonConfig.QR', str(path))
        xbmc.executebuiltin('ActivateWindow(' + str(CONFIG_WINDOW_ID) + ')')
    except Exception:
        dialog.ok('Configure ' + manifest.get('name', 'addon'),
                  'Open this address on your phone/computer, finish setup, then install the configured manifest URL:\n\n' + url)


def sync_account(dialog):
    state = STORE.load()
    token = state.get('token')
    if not token:
        dialog.ok('Stremio Addons', 'Connect your Stremio account first.')
        return
    addons, skipped = pull_addons(token)
    state['addons'] = merge_account(state, addons)
    # Disabled-on-this-device state and local-only installs survive account sync.
    STORE.save(state)
    publish('Synced {} addons from Stremio'.format(len(addons)))
    dialog.notification('Stremio Addons', '{} addons synced; {} unsupported skipped.'.format(len(addons), skipped))


def install_url(dialog):
    value = dialog.input('Stremio addon manifest URL', type=xbmcgui.INPUT_ALPHANUM)
    if not value.strip():
        return
    state = STORE.load()
    try:
        descriptor = install_local(state, value.strip())
    except Exception:
        dialog.ok('Stremio Addons', 'Unable to read this manifest. Use an HTTPS URL ending in /manifest.json.')
        return
    finish_install(state, descriptor, dialog)


def addon_actions(dialog, identity=None):
    state = STORE.load()
    addons = list(state.get('addons', []))
    if not addons:
        dialog.ok('My Addons', 'No Stremio addons are installed on this device.')
        return
    disabled = set(state.get('disabledAddons', []))
    labels = []
    for item in addons:
        name = item.get('manifest', {}).get('name', 'Stremio addon')
        labels.append(('Disabled · ' if item.get('id') in disabled else '') + name)
    if identity is None:
        selected = dialog.select('My Stremio Addons', labels)
        if selected < 0:
            return
        item = addons[selected]
    else:
        item = next((row for row in addons if row.get('id') == identity), None)
        if item is None:
            return
    identity = item['id']
    manifest = item.get('manifest', {})
    enabled = identity not in disabled
    config = configuration_state(manifest)
    actions = [('disable' if enabled else 'enable', 'Disable on this device' if enabled else 'Enable on this device')]
    if config['configurable']:
        actions.append(('configure', 'Configure'))
    actions += [('remove_local', 'Remove from this device')]
    if state.get('token') and item.get('account') is True:
        actions.append(('remove_account', 'Remove from Stremio account'))
    actions.append(('info', 'Addon information'))
    choice = dialog.select(manifest.get('name', 'Stremio addon'), [label for _, label in actions])
    if choice < 0:
        return
    action = actions[choice][0]
    if action in ('enable', 'disable'):
        set_enabled(state, identity, action == 'enable')
        STORE.save(state)
        publish(('Enabled ' if action == 'enable' else 'Disabled ') + manifest.get('name', 'addon'))
    elif action == 'configure':
        show_config(manifest, item['transportUrl'], dialog)
    elif action == 'remove_local':
        if dialog.yesno('Remove from this device?',
                'This does not change your Stremio account or other devices.'):
            remove_local(state, identity)
            STORE.save(state)
            publish('Removed from this device')
    elif action == 'remove_account':
        if not dialog.yesno('Remove from Stremio account?',
                'This changes your Stremio addon collection and can affect your other Stremio devices. Continue?'):
            return
        remote = [row for row in account_addons(state) if row.get('id') != identity]
        try:
            push_account(state['token'], remote)
        except Exception:
            dialog.ok('Stremio Addons', 'Stremio account was not changed.')
            return
        state['addons'] = merge_account(state, remote)
        state['disabledAddons'] = sorted(set(state.get('disabledAddons', [])) - {identity})
        STORE.save(state)
        publish('Removed from Stremio account')
    else:
        resources = manifest.get('resources', [])
        dialog.ok(manifest.get('name', 'Stremio addon'),
                  'Version: ' + str(manifest.get('version', '')) +
                  '\nResources: ' + ', '.join(str(r.get('name') if isinstance(r, dict) else r) for r in resources) +
                  '\n\n' + str(manifest.get('description', ''))[:900])


def main(action='open', value=''):
    dialog = themed_dialog()
    if action == 'open':
        xbmc.executebuiltin('ActivateWindow(' + str(WINDOW_ID) + ')')
    elif action == 'refresh':
        publish()
    elif action == 'my':
        addon_actions(dialog)
        publish()
    elif action == 'install':
        install_url(dialog)
    elif action == 'sync':
        sync_account(dialog)
    elif action == 'community':
        xbmc.executebuiltin('ActivateWindow(' + str(COMMUNITY_WINDOW_ID) + ')')
    elif action == 'community_init':
        community_init()
    elif action == 'community_filter':
        community_filter(value)
    elif action == 'community_search':
        community_search(dialog)
    else:
        dialog.ok('Stremio Addons', 'Unknown addon manager action.')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'open',
         sys.argv[2] if len(sys.argv) > 2 else '')
