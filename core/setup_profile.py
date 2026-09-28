"""One-time Stremio for Kodi setup. No external skin helper is required."""
import json
import os
import shutil
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

HOME_ROWS = (
    ('Continue Watching', 'plugin://script.stremioelec/?action=continue'),
    ('My Library', 'plugin://script.stremioelec/?action=library'),
    ('Popular Movies', 'plugin://script.stremioelec/?action=home_catalog&kind=movie&id=top'),
    ('Popular Series', 'plugin://script.stremioelec/?action=home_catalog&kind=series&id=top'),
    ('New Movies', 'plugin://script.stremioelec/?action=home_catalog&kind=movie&id=year'),
    ('New Series', 'plugin://script.stremioelec/?action=home_catalog&kind=series&id=year'),
    ('Featured Movies', 'plugin://script.stremioelec/?action=home_catalog&kind=movie&id=imdbRating'),
    ('Featured Series', 'plugin://script.stremioelec/?action=home_catalog&kind=series&id=imdbRating'),
    ('Action Movies', 'plugin://script.stremioelec/?action=home_catalog&kind=movie&id=top&genre=Action'),
    ('Comedy Series', 'plugin://script.stremioelec/?action=home_catalog&kind=series&id=top&genre=Comedy'),
)


def home_xml():
    """Compatibility description of the built-in rows; runtime Home is skin-owned."""
    root = ET.Element('shortcuts')
    for name, route in HOME_ROWS:
        row = ET.SubElement(root, 'shortcut')
        for key, value in [('label', name), ('label2', ''), ('icon', 'DefaultShortcut.png'),
                           ('thumb', ''), ('action', route)]:
            ET.SubElement(row, key).text = value
        ET.SubElement(row, 'additional-properties').text = "[('widgetlimit', '20')]"
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def replace_backed_up(path, payload, backups):
    path = Path(path)
    key = path.parent.name + '--' + path.name
    destination = Path(backups) / key
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not destination.exists():
        shutil.copy2(path, destination)
    atomic_write(path, payload)


def rpc(method, params=None):
    import xbmc
    response = json.loads(xbmc.executeJSONRPC(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})))
    if 'error' in response:
        raise RuntimeError('Kodi settings request failed')
    return response.get('result')


def get_setting(name, fallback=None):
    try:
        return rpc('Settings.GetSettingValue', {'setting': name}).get('value', fallback)
    except Exception:
        return fallback


def prepare(profile, addon_path=None, force_home=False):
    import xbmc
    from account import Store
    state_store = Store(Path(profile) / 'setup')
    state = state_store.load()
    if state.get('completed') and not force_home:
        return state
    if not state:
        state = {'completed': False, 'device_policy': 'safe-unverified-hdmi',
                 'before': {}, 'applied': {}}
        for key in ('filelists.showparentdiritems', 'audiooutput.passthrough',
                    'videoplayer.adjustrefreshrate', 'videoplayer.usedisplayasclock',
                    'subtitles.movie', 'subtitles.tv'):
            state['before'][key] = get_setting(key)
        state_store.save(state)
    if not state.get('completed'):
        for key, value in [('filelists.showparentdiritems', False),
                           ('audiooutput.passthrough', False),
                           ('videoplayer.adjustrefreshrate', 0),
                           ('videoplayer.usedisplayasclock', False)]:
            if state['before'].get(key) is not None:
                try:
                    if rpc('Settings.SetSettingValue', {'setting': key, 'value': value}):
                        state['applied'][key] = value
                except Exception:
                    pass
    state['platform'] = next((name for name in ('linux', 'osx', 'android', 'windows')
                              if xbmc.getCondVisibility('System.Platform.' + name)), 'unknown')
    for key in ('subtitles.movie', 'subtitles.tv'):
        if not get_setting(key, ''):
            state['before'].setdefault(key, '')
            state_store.save(state)
            try:
                if rpc('Settings.SetSettingValue', {'setting': key, 'value': 'script.stremioelec'}):
                    state['applied'][key] = 'script.stremioelec'
            except Exception:
                pass
    state['home_model'] = 'stremioelec-native'
    state['completed'] = True
    state_store.save(state)
    return state
