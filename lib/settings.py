import json
from pathlib import Path
import xbmcaddon
from addon_state import get_addon
import xbmcvfs

ADDON = get_addon()


def _path():
    profile = Path(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')))
    profile.mkdir(parents=True, exist_ok=True)
    return profile / 'setup.json'


def load_setup():
    path = _path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_setup(data):
    path = _path()
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def apply_kodi_locale(language_id, region_name, audio_code, subtitle_code):
    import json as js
    import xbmc

    def rpc(method, params):
        xbmc.executeJSONRPC(js.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}))

    for key, value in (
            ('locale.language', language_id),
            ('locale.country', region_name),
            ('locale.audiolanguage', audio_code),
            ('locale.subtitlelanguage', subtitle_code),
    ):
        try:
            rpc('Settings.SetSettingValue', {'setting': key, 'value': value})
        except Exception:
            pass


def locale_menu():
    import xbmcgui
    from lib.windows import LANGUAGES, REGIONS
    setup = load_setup()
    choice = xbmcgui.Dialog().select('Language and location', ['Language', 'Location'])
    rows = LANGUAGES if choice == 0 else REGIONS
    if choice < 0:
        return
    selected = xbmcgui.Dialog().select('Language' if choice == 0 else 'Location', [row[0] for row in rows])
    if selected < 0:
        return
    setup['language' if choice == 0 else 'region'] = rows[selected]
    save_setup(setup)
    language = setup.get('language') or LANGUAGES[0]
    region = setup.get('region') or REGIONS[0]
    apply_kodi_locale(language[1], region[1], language[2], language[2])
