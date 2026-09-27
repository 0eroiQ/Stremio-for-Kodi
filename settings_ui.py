"""Curated appliance settings. Never opens the generic addon/settings browser."""
import sys
import ast
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcgui
import xbmcvfs
from account import Store
from setup_profile import rpc, get_setting, prepare, replace_backed_up, home_xml

ADDON = get_addon()
PROFILE = Path(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')))
DIALOG = xbmcgui.Dialog()
HOME = 'special://profile/addon_data/script.skinshortcuts/skin.stremioelec-10000-1.DATA.xml'
SETTINGS_COMMAND_WINDOW_ID = 1198
SETTINGS_RUNTIME_WINDOW_ID = 11198

COLORS = [('White', 'FFFFFFFF'), ('Yellow', 'FFFFFF00'), ('Light gray', 'FFCCCCCC'),
          ('Black', 'FF000000'), ('Cyan', 'FF00FFFF'), ('Green', 'FF00FF00'),
          ('Red', 'FFFF0000'), ('Blue', 'FF0000FF'), ('Orange', 'FFFFA500'),
          ('Pink', 'FFFFC0CB'), ('Magenta', 'FFFF00FF')]
APPEARANCE = [('StremioHideCardLabels', 'Hide card names and details'),
              ('StremioHideCardGenres', 'Hide genres / secondary text under cards'),
              ('PreferTvShowThumbWidget', 'Use show artwork for episodes'),
              ('EnableColorDetailsIcons', 'Colored detail icons'),
              ('EnableStudioLogo', 'Studio logos'),
              ('AutoCloseVideoOSD', 'Automatically hide playback controls'),
              ('ChapterMarks', 'Chapter markers'),
              ('EnableBufferingProgressOSD', 'Show buffering progress')]


def setting_options(setting):
    """Use device-provided choices, including list and numeric definitions."""
    options = setting.get('options') or setting.get('definition', {}).get('options', [])
    if options:
        return options
    if setting.get('id') in ('subtitles.colorpick', 'subtitles.bordercolorpick', 'subtitles.bgcolorpick', 'subtitles.shadowcolor'):
        return [{'label': label, 'value': value} for label, value in COLORS]
    if isinstance(setting.get('value'), (int, float)) and not isinstance(setting.get('value'), bool):
        if all(key in setting for key in ('minimum', 'maximum', 'step')):
            low, high, step = [Decimal(str(setting[k])) for k in ('minimum', 'maximum', 'step')]
            if step > 0 and high >= low and (high - low) / step <= 500:
                values = [low + step * i for i in range(int((high - low) / step) + 1)]
                return [{'label': format(v.normalize(), 'f'), 'value': int(v) if isinstance(setting['value'], int) else float(v)} for v in values]
    return []


def update_row_limit(row, limit):
    """Preserve all unrelated shortcut properties; never eval user data."""
    props = row.find('additional-properties')
    if props is None:
        props = ET.SubElement(row, 'additional-properties')
    pairs = ast.literal_eval(props.text) if props.text else []
    if not isinstance(pairs, list) or any(not isinstance(p, (tuple, list)) or len(p) != 2 for p in pairs):
        raise ValueError('Invalid shortcut properties')
    props.text = repr([(key, value) for key, value in pairs if key != 'widgetlimit'] + [('widgetlimit', str(limit))])


def choose(title, options):
    return DIALOG.select(title, options)


def edit_kodi(key, label):
    settings = rpc('Settings.GetSettings', {'level': 'expert'}).get('settings', [])
    setting = next((item for item in settings if item['id'] == key), None)
    if not setting or not setting.get('enabled', True):
        DIALOG.ok('Stremio for Kodi', 'This option is not available on this device.')
        return
    value = setting.get('value')
    previous = value
    options = setting_options(setting)
    if isinstance(value, bool):
        value = not value
    elif options:
        if isinstance(value, list):
            selected = DIALOG.multiselect(label, [str(o['label']) for o in options],
                                          preselect=[i for i, o in enumerate(options) if o['value'] in value])
            if selected is None:
                return
            value = [options[i]['value'] for i in selected]
        else:
            index = DIALOG.select(label, [str(o['label']) for o in options],
                                  preselect=next((i for i, o in enumerate(options) if o['value'] == value), 0))
            if index < 0:
                return
            value = options[index]['value']
    else:
        DIALOG.ok('Stremio for Kodi', 'No supported choices were reported by this device. Current value: ' + str(value))
        return
    if not rpc('Settings.SetSettingValue', {'setting': key, 'value': value}):
        raise RuntimeError('Setting was rejected')
    if key in ('videoscreen.resolution', 'videoscreen.screenmode'):
        if not DIALOG.yesno('Keep display mode?', 'Confirm within 15 seconds or the previous mode will be restored.', autoclose=15000):
            if not rpc('Settings.SetSettingValue', {'setting': key, 'value': previous}):
                raise RuntimeError('Could not restore previous display mode')


def kodi_menu(title, entries):
    while True:
        definitions = {s['id']: s for s in rpc('Settings.GetSettings', {'level': 'expert'}).get('settings', [])}
        available = [(key, name, definitions[key]) for key, name in entries if key in definitions and definitions[key].get('value') is not None]
        def summary(setting):
            value = setting['value']
            text = next((str(o['label']) for o in setting_options(setting) if o['value'] == value), display_value(value))
            return text + (' (unavailable)' if not setting.get('enabled', True) else '')
        if not available:
            DIALOG.ok(title, 'No supported settings were reported by this platform.')
            return
        index = choose(title, [name + ': ' + summary(setting) for key, name, setting in available])
        if index < 0:
            return
        key, name, _ = available[index]
        edit_kodi(key, name)


def display_value(value):
    if isinstance(value, bool):
        return 'On' if value else 'Off'
    if isinstance(value, list):
        return ', '.join(str(item) for item in value)
    return str(value)


SETTINGS_WINDOW_PROPERTIES = {
    'locale.country': 'Region',
    'locale.timezone': 'Timezone',
    'locale.keyboardlayouts': 'Keyboard',
    'locale.use24hourclock': 'Clock24',
    'locale.temperatureunit': 'TemperatureUnit',
    'locale.speedunit': 'SpeedUnit',
    'videoplayer.autoplaynextitem': 'AutoplayNext',
    'videoplayer.seeksteps': 'SeekSteps',
    'videoplayer.adjustrefreshrate': 'MatchRefresh',
    'videoplayer.usedisplayasclock': 'SyncDisplay',
    'audiooutput.audiodevice': 'AudioDevice',
    'audiooutput.channels': 'AudioChannels',
    'locale.audiolanguage': 'AudioLanguage',
    'audiooutput.passthrough': 'Passthrough',
    'audiooutput.guisoundmode': 'NavigationSounds',
    'locale.subtitlelanguage': 'SubtitleLanguage',
    'subtitles.languages': 'SubtitleDownloads',
    'subtitles.downloadfirst': 'SubtitleAuto',
    'videoscreen.resolution': 'Resolution',
    'videoscreen.screenmode': 'ScreenMode',
    'videoscreen.blankdisplays': 'BlankDisplays',
    'videoscreen.delayrefreshchange': 'RefreshDelay',
    'powermanagement.displaysoff': 'DisplayOff',
    'screensaver.time': 'ScreensaverTime',
}


def setting_summary(setting):
    value = setting.get('value')
    text = next((str(o['label']) for o in setting_options(setting)
                 if o.get('value') == value), display_value(value))
    return text + (' (Unavailable)' if not setting.get('enabled', True) else '')


def sync_window():
    window = xbmcgui.Window(SETTINGS_RUNTIME_WINDOW_ID)
    definitions = {s['id']: s for s in rpc('Settings.GetSettings', {'level': 'expert'}).get('settings', [])}
    for key, prop in SETTINGS_WINDOW_PROPERTIES.items():
        setting = definitions.get(key)
        window.setProperty('StremioSettings.' + prop,
                           setting_summary(setting) if setting and setting.get('value') is not None else 'Unavailable')
    try:
        connected = bool(Store(PROFILE).load().get('token'))
    except Exception:
        connected = False
    window.setProperty('StremioSettings.Account', 'Connected' if connected else 'Not connected')
    window.setProperty('StremioSettings.Weather', ADDON.getSetting('weather_location').strip() or 'Not set')
    manifest = ADDON.getSetting('manifest').strip() or 'https://v3-cinemeta.strem.io/manifest.json'
    window.setProperty('StremioSettings.CatalogSource',
                       'Official Cinemeta' if manifest == 'https://v3-cinemeta.strem.io/manifest.json' else 'Custom')
    window.setProperty('StremioSettings.KodiVersion', xbmc.getInfoLabel('System.BuildVersion'))
    window.setProperty('StremioSettings.Runtime',
                       'Portable Kodi' if xbmc.getCondVisibility('System.HasAddon(service.stremioelec.portable)') else 'StremioELEC OS')


def helper_menu():
    selection = choose('Catalogs & artwork', ['Catalog source', 'TMDb trailer API key', 'Ratings'])
    if selection < 0:
        return
    if selection == 2:
        ratings_menu()
        return
    if selection == 1:
        action = choose('TMDb trailer API key', ['Replace key (stored locally)', 'Remove key'])
        if action == 0:
            value = DIALOG.input('TMDb API key', type=xbmcgui.INPUT_ALPHANUM,
                                 option=xbmcgui.ALPHANUM_HIDE_INPUT)
            if value.strip():
                ADDON.setSetting('tmdb_api_key', value.strip())
        elif action == 1:
            ADDON.setSetting('tmdb_api_key', '')
        return
    current = ADDON.getSetting('manifest').strip() or 'https://v3-cinemeta.strem.io/manifest.json'
    action = choose('Catalog source', ['Use official Cinemeta', 'Change manifest URL', 'Current: ' + current])
    if action == 0:
        ADDON.setSetting('manifest', 'https://v3-cinemeta.strem.io/manifest.json')
    elif action == 1:
        value = DIALOG.input('Stremio catalog manifest URL', defaultt=current,
                             type=xbmcgui.INPUT_ALPHANUM)
        if value.strip():
            from protocol import base_url
            try:
                base_url(value.strip())
            except Exception:
                DIALOG.ok('Catalog source', 'Use an HTTP(S) URL ending in /manifest.json.')
                return
            ADDON.setSetting('manifest', value.strip())


def ratings_menu():
    toggles = [('EnableRatings', 'Show ratings'),
               ('EnableTop250WhiteLabel', 'White Top 250 label'),
               ('details_row_rating', 'Rating in details row'),
               ('DisableRatingsPlotCritics', 'Hide ratings / critics in plot'),
               ('videoinfo_button_myrating', 'My rating button in info')]
    while True:
        values = [xbmc.getCondVisibility('Skin.HasSetting(' + key + ')') for key, _ in toggles]
        labels = [label + ': ' + display_value(value) for (_, label), value in zip(toggles, values)]
        index = choose('Ratings', labels + ['Details rating color'])
        if index < 0:
            return
        if index < len(toggles):
            key = toggles[index][0]
            xbmc.executebuiltin(('Skin.Reset(' if values[index] else 'Skin.SetBool(') + key + ')')
        else:
            color = choose('Details rating color', [label for label, _ in COLORS])
            if color >= 0:
                xbmc.executebuiltin('Skin.SetString(BingieRatingInDetailsColor,' + COLORS[color][1] + ')')


def weather_menu():
    """Configure the built-in Stremio for Kodi weather provider."""
    from weather import search, refresh
    while True:
        location = ADDON.getSetting('weather_location').strip()
        index = choose('Weather', [
            'Location: ' + (location or 'Not set'),
            'Refresh weather now'
        ])
        if index < 0:
            return
        if index == 1:
            refresh(force=True)
            continue
        query = DIALOG.input('Search city or postcode', defaultt=location,
                             type=xbmcgui.INPUT_ALPHANUM)
        if not query.strip():
            continue
        try:
            region = rpc('Settings.GetSettingValue', {'setting': 'locale.country'}).get('value', '')
            rows = search(query.strip(), country=region)
        except Exception:
            DIALOG.ok('Weather', 'Location search failed. Check the network connection and retry.')
            continue
        if not rows:
            DIALOG.ok('Weather', 'No matching location was found.')
            continue
        selected = choose('Choose location', [row['label'] for row in rows])
        if selected < 0:
            continue
        row = rows[selected]
        ADDON.setSetting('weather_location', row['label'])
        ADDON.setSetting('weather_lat', str(row['latitude']))
        ADDON.setSetting('weather_lon', str(row['longitude']))
        payload = refresh(force=True) or {}
        timezone = str(payload.get('timezone') or '').strip()
        if timezone:
            result = rpc('Settings.SetSettingValue', {
                'setting': 'locale.timezone',
                'value': timezone,
            })
            if result is False:
                DIALOG.notification(
                    'Region & Location',
                    'Weather location saved, but Kodi rejected the time zone.')
            else:
                sync_window()


def home_menu():
    from setup_profile import HOME_ROWS
    current = [not xbmc.getCondVisibility('Skin.HasSetting(StremioHideHomeRow{})'.format(i))
               for i in range(len(HOME_ROWS))]
    selected = DIALOG.multiselect('Visible Home rows', [label for label, _ in HOME_ROWS],
                                  preselect=[i for i, enabled in enumerate(current) if enabled])
    if selected is None:
        return
    if not selected:
        DIALOG.ok('Home', 'Keep at least one Home row visible.')
        return
    chosen = set(selected)
    for i in range(len(HOME_ROWS)):
        xbmc.executebuiltin(('Skin.Reset(' if i in chosen else 'Skin.SetBool(') +
                            'StremioHideHomeRow{})'.format(i))
    xbmc.executebuiltin('ReloadSkin()')


def card_layout_menu():
    values = [('Landscape', 'landscape'), ('Posters', 'poster'), ('Square', 'square')]
    current = xbmc.getInfoLabel('Skin.String(widgetstyle)') or 'landscape'
    index = DIALOG.select('Card layout', [label for label, _ in values],
                          preselect=next((i for i, (_, value) in enumerate(values)
                                          if value == current), 0))
    if index >= 0:
        xbmc.executebuiltin('Skin.SetString(widgetstyle,' + values[index][1] + ')')
        xbmc.executebuiltin('ReloadSkin()')


def appearance_menu():
    while True:
        state = [xbmc.getCondVisibility('Skin.HasSetting(' + key + ')') for key, _ in APPEARANCE]
        index = choose('Appearance', [label + ': ' + display_value(value) for (_, label), value in zip(APPEARANCE, state)])
        if index < 0:
            return
        key = APPEARANCE[index][0]
        xbmc.executebuiltin(('Skin.Reset(' if state[index] else 'Skin.SetBool(') + key + ')')
        if key == 'StremioHideCardLabels':
            xbmc.executebuiltin('ReloadSkin()')
            return


def reset_account():
    if xbmc.Player().isPlaying():
        DIALOG.ok('Reset', 'Stop playback before resetting.')
        return
    if not DIALOG.yesno('Reset Stremio for Kodi', 'Remove this device login and imported data, restore default Home and return to QR sign-in? Your online account, network and Bluetooth stay unchanged.'):
        return
    # Restore Home before removing credentials; failed setup must not log out.
    prepare(PROFILE, xbmcvfs.translatePath(ADDON.getAddonInfo('path')), force_home=True)
    for folder in ('', 'streams', 'playback', 'subtitle-results', 'setup'):
        Store(PROFILE / folder).forget()
    for flag in ('StremioOnboardingDone', 'StremioHomeDefaults', 'BingieFirstStartupDone', 'BingieSecondStartupDone'):
        xbmc.executebuiltin('Skin.Reset(' + flag + ')')
    xbmc.executebuiltin('ReplaceWindow(1101)')


def account_menu():
    state = Store(PROFILE).load()
    options = ['Sign in'] if not state.get('token') else ['Account connected', 'Refresh library']
    if state.get('token'):
        options.append('Disconnect this device')
    index = choose('Stremio account', options)
    if index == 0:
        from lib.signin import show_signin
        if not state.get('token'):
            show_signin()
        else:
            DIALOG.ok('Stremio account', 'This device is signed in.')
    elif index == 1:
        xbmc.executebuiltin('RunPlugin(plugin://script.stremioelec/?action=sync_library)')
    elif index == 2 and state.get('token'):
        xbmc.executebuiltin('RunPlugin(plugin://script.stremioelec/?action=disconnect)')


def navigation_sounds_menu():
    while True:
        mode = get_setting('audiooutput.guisoundmode')
        if mode is None:
            DIALOG.ok('Navigation sounds', 'This option is not available on this device.')
            return
        index = choose('Navigation sounds', ['Navigation sounds: ' + ('Off' if mode == 0 else 'On'), 'Volume'])
        if index < 0:
            return
        if index == 0:
            # Kodi mode 1 plays UI sounds only when media playback is stopped.
            if not rpc('Settings.SetSettingValue', {'setting': 'audiooutput.guisoundmode', 'value': 1 if mode == 0 else 0}):
                raise RuntimeError('Navigation sound setting was rejected')
        else:
            edit_kodi('audiooutput.guisoundvolume', 'Navigation sound volume')


def remote_control_menu():
    entries = [('services.webserver', 'Allow remote control via HTTP'),
               ('services.esenabled', 'Application control'),
               ('services.esallinterfaces', 'Allow applications on other systems'),
               ('services.zeroconf', 'Announce device on local network')]
    while True:
        values = [get_setting(key) for key, _ in entries]
        index = choose('Remote control', [label + ': ' + display_value(value) for (_, label), value in zip(entries, values)] +
                       ['HTTP username', 'Change HTTP password', 'HTTP port', 'Connection information'])
        if index < 0:
            return
        if index < 4:
            key, label = entries[index]
            if values[index] is None:
                DIALOG.ok('Remote control', 'This service is not available on this device.')
                continue
            if not values[index] and index in (0, 2):
                if not DIALOG.yesno('Remote control', 'Allow control from your local network? Use only on a trusted network. Application control does not use the HTTP password. Do not forward these ports on your router.'):
                    continue
            if index == 0 and not values[index]:
                if not get_setting('services.webserverusername', '') or not get_setting('services.webserverpassword', ''):
                    DIALOG.ok('Remote control', 'Set an HTTP username and password before enabling HTTP control.')
                    continue
                if not rpc('Settings.SetSettingValue', {'setting': 'services.webserverauthentication', 'value': True}):
                    raise RuntimeError('Authentication could not be enabled')
            if index == 2 and not values[index]:
                if not rpc('Settings.SetSettingValue', {'setting': 'services.esenabled', 'value': True}):
                    raise RuntimeError('Application control could not be enabled')
            if not rpc('Settings.SetSettingValue', {'setting': key, 'value': not values[index]}):
                raise RuntimeError('Remote control setting rejected')
        elif index in (4, 5, 6):
            key = {4: 'services.webserverusername', 5: 'services.webserverpassword', 6: 'services.webserverport'}[index]
            value = DIALOG.input({4: 'HTTP username', 5: 'New HTTP password', 6: 'HTTP port'}[index],
                                 type=xbmcgui.INPUT_NUMERIC if index == 6 else xbmcgui.INPUT_ALPHANUM,
                                 option=xbmcgui.ALPHANUM_HIDE_INPUT if index == 5 else 0)
            if not value:
                continue
            if index == 6:
                if not value.isdigit() or not 1024 <= int(value) <= 65535:
                    DIALOG.ok('HTTP port', 'Choose a port from 1024 to 65535.')
                    continue
                value = int(value)
            if not rpc('Settings.SetSettingValue', {'setting': key, 'value': value}):
                raise RuntimeError('Remote control setting rejected')
        else:
            DIALOG.ok('Remote app connection', 'IP: ' + xbmc.getInfoLabel('Network.IPAddress') +
                      '\nHTTP port: ' + str(get_setting('services.webserverport')) +
                      '\nUsername: ' + str(get_setting('services.webserverusername', '')) +
                      '\nUse the password you set here. Connect the phone to the same local network.')


def developer_enabled():
    return xbmc.getCondVisibility('Skin.HasSetting(StremioDeveloperMode)')


def advanced_playback_enabled():
    return developer_enabled() or xbmc.getCondVisibility('Skin.HasSetting(StremioAdvancedPlayback)')


def playback_menu():
    entries = [
        ('videoplayer.autoplaynextitem', 'Autoplay next item'),
        ('videoplayer.seeksteps', 'Skip / seek steps'),
        ('videoplayer.adjustrefreshrate', 'Match display refresh rate'),
        ('videoplayer.usedisplayasclock', 'Sync playback to display'),
    ]
    if advanced_playback_enabled():
        entries += [
            ('videoplayer.usevtb', 'VideoToolbox hardware decoding'),
            ('videoplayer.usemediacodec', 'MediaCodec hardware decoding'),
            ('videoplayer.usemediacodecsurface', 'MediaCodec surface'),
            ('videoplayer.usevaapi', 'VAAPI hardware decoding'),
            ('videoplayer.usedxva2', 'DXVA hardware decoding'),
        ]
    kodi_menu('Playback', entries)


def audio_menu():
    index = choose('Audio', ['Navigation sounds', 'Playback audio'])
    if index == 0:
        navigation_sounds_menu()
    elif index == 1:
        kodi_menu('Playback audio', [
            ('audiooutput.audiodevice', 'Output device'), ('audiooutput.channels', 'Channels'),
            ('locale.audiolanguage', 'Preferred language'), ('audiooutput.passthrough', 'Passthrough'),
            ('audiooutput.passthroughdevice', 'Passthrough device'),
            ('audiooutput.ac3passthrough', 'Dolby Digital capable receiver'),
            ('audiooutput.eac3passthrough', 'Dolby Digital Plus capable receiver'),
            ('audiooutput.dtspassthrough', 'DTS capable receiver'),
            ('audiooutput.truehdpassthrough', 'TrueHD capable receiver'),
            ('audiooutput.dtshdpassthrough', 'DTS-HD capable receiver'),
        ])


def region_menu():
    kodi_menu('Region & Location', [
        ('locale.country', 'Country / region'),
        ('locale.timezonecountry', 'Time zone country'),
        ('locale.timezone', 'Time zone'),
        ('locale.keyboardlayouts', 'Keyboard layouts'),
        ('locale.use24hourclock', '24-hour clock'),
        ('locale.timeformat', 'Time format'),
        ('locale.shortdateformat', 'Short date format'),
        ('locale.longdateformat', 'Long date format'),
        ('locale.temperatureunit', 'Temperature unit'),
        ('locale.speedunit', 'Speed unit'),
    ])


def accessibility_menu():
    kodi_menu('Accessibility', [
        ('accessibility.audiovisual', 'Audio description'),
        ('accessibility.audiohearing', 'Hearing-impaired audio'),
        ('accessibility.subhearing', 'Hearing-impaired subtitles'),
        ('subtitles.parsecaptions', 'Parse closed captions'),
    ])


def power_menu():
    kodi_menu('Power & Screensaver', [
        ('powermanagement.displaysoff', 'Turn display off after'),
        ('powermanagement.shutdowntime', 'Shutdown timer'),
        ('powermanagement.shutdownstate', 'Shutdown action'),
        ('powermanagement.waitfornetwork', 'Wait for network on startup'),
        ('powermanagement.wakeonaccess', 'Wake on network access'),
        ('screensaver.time', 'Screensaver delay'),
        ('screensaver.disableforaudio', 'Disable screensaver during audio'),
        ('screensaver.usedimonpause', 'Dim screen when paused'),
    ])


def display_menu():
    kodi_menu('Display', [
        ('videoscreen.monitor', 'Display / monitor'),
        ('videoscreen.resolution', 'Resolution'),
        ('videoscreen.screenmode', 'Display mode'),
        ('videoscreen.blankdisplays', 'Blank other displays'),
        ('videoscreen.delayrefreshchange', 'Refresh-rate change delay'),
        ('videoplayer.adjustrefreshrate', 'Match display refresh rate'),
    ])


def remote_tv_menu():
    while True:
        options = ['Remote control apps', 'Navigation sounds', 'HDMI-CEC / TV remote']
        if developer_enabled():
            options.append('CEC backend controls')
        index = choose('Remote & TV', options)
        if index < 0:
            return
        if index == 0:
            remote_control_menu()
        elif index == 1:
            navigation_sounds_menu()
        elif index == 2:
            DIALOG.ok('HDMI-CEC / TV remote',
                      'Stremio for Kodi uses the playback engine and platform CEC support. TV-remote behavior is kept device-safe by default. Developer Mode can open backend peripheral controls when troubleshooting.')
        elif index == 3 and developer_enabled():
            xbmc.executebuiltin('ActivateWindow(peripherals)')


def diagnostics_menu():
    mode = xbmc.getInfoLabel('Skin.String(StremioSetupMode)') or 'standard'
    runtime = 'Portable' if xbmc.getCondVisibility('System.HasAddon(service.stremioelec.portable)') else 'StremioELEC OS'
    DIALOG.ok('Diagnostics', 'Runtime: ' + runtime + '\nSetup mode: ' + mode +
              '\nPlayback engine: Kodi ' + xbmc.getInfoLabel('System.BuildVersion') +
              '\nIP: ' + xbmc.getInfoLabel('Network.IPAddress'))


def maintenance_menu():
    options = ['Restore default Home', 'Reset Stremio for Kodi / return to Welcome']
    portable = xbmc.getCondVisibility('System.HasAddon(service.stremioelec.portable)')
    if portable:
        options.append('Restore previous interface')
    index = choose('Maintenance & Reset', options)
    if index == 0 and DIALOG.yesno('Restore Home', 'Replace your Home rows with the default Stremio for Kodi rows?'):
        prepare(PROFILE, xbmcvfs.translatePath(ADDON.getAddonInfo('path')), force_home=True)
        xbmc.executebuiltin('ReloadSkin()')
    elif index == 1:
        reset_account()
    elif portable and index == 2:
        xbmc.executebuiltin('RunScript(special://home/addons/service.stremioelec.portable/control.py,restore)')


def system_updates_menu():
    portable = xbmc.getCondVisibility('System.HasAddon(service.stremioelec.portable)')
    os_settings = xbmc.getCondVisibility('System.HasAddon(service.libreelec.settings)')
    os_updater = xbmc.getCondVisibility('System.HasAddon(service.stremioelec.updates)')
    actions = [('info', 'System information')]
    actions.append(('os_updates', 'System Updates') if os_updater else ('component_updates', 'Component Updates'))
    if os_settings:
        actions.append(('network', 'Network & Bluetooth'))
    actions.append(('power_settings', 'Power & Screensaver'))
    actions.append(('restart', 'Restart Stremio for Kodi'))
    actions.append(('restore', 'Restore previous interface') if portable else ('power', 'Power off device'))
    index = choose('System & Updates', [label for _, label in actions])
    if index < 0:
        return
    action = actions[index][0]
    if action == 'info':
        diagnostics_menu()
    elif action == 'os_updates':
        xbmc.executebuiltin('RunScript(special://xbmc/addons/service.stremioelec.updates/ui.py)')
    elif action == 'component_updates':
        xbmc.executebuiltin('UpdateAddonRepos')
        xbmc.executebuiltin('UpdateLocalAddons')
        DIALOG.notification('Stremio for Kodi', 'Checking component updates')
    elif action == 'network':
        xbmc.executebuiltin('RunScript(special://xbmc/addons/service.libreelec.settings/default.py)')
    elif action == 'power_settings':
        power_menu()
    elif action == 'restart' and DIALOG.yesno('Restart Stremio for Kodi?', 'Stop playback and restart the application now?'):
        xbmc.executebuiltin('RestartApp')
    elif action == 'restore':
        xbmc.executebuiltin('RunScript(special://home/addons/service.stremioelec.portable/control.py,restore)')
    elif action == 'power' and DIALOG.yesno('Power off?', 'Power off this Stremio for Kodi device?'):
        xbmc.executebuiltin('Powerdown')


def advanced_menu():
    while True:
        advanced = advanced_playback_enabled()
        developer = developer_enabled()
        options = ['Playback compatibility', 'Network services', 'Maintenance & Reset', 'Diagnostics',
                   'Advanced playback controls: ' + display_value(advanced),
                   'Developer Mode: ' + display_value(developer)]
        if developer:
            options.append('Open playback engine backend')
        index = choose('Advanced', options)
        if index < 0:
            return
        if index == 0:
            playback_menu()
        elif index == 1:
            remote_control_menu()
        elif index == 2:
            maintenance_menu()
        elif index == 3:
            diagnostics_menu()
        elif index == 4:
            xbmc.executebuiltin(('Skin.Reset(' if advanced else 'Skin.SetBool(') + 'StremioAdvancedPlayback)')
        elif index == 5:
            if developer:
                xbmc.executebuiltin('Skin.Reset(StremioDeveloperMode)')
            elif DIALOG.yesno('Enable Developer Mode?',
                    'Developer Mode exposes the native playback-engine backend and can bypass Stremio for Kodi safeguards. Continue?'):
                xbmc.executebuiltin('Skin.SetBool(StremioDeveloperMode)')
                xbmc.executebuiltin('Skin.SetBool(StremioAdvancedPlayback)')
        elif index == 6 and developer:
            xbmc.executebuiltin('ActivateWindow(1199)')


def run(section, *args):
    if section == 'sync':
        sync_window()
    elif section == 'setting' and len(args) >= 2:
        edit_kodi(args[0], args[1])
        sync_window()
    elif section == 'account':
        account_menu()
        sync_window()
    elif section == 'home':
        index = choose('Home & Appearance', ['Visible Home rows', 'Card layout', 'Appearance'])
        if index == 0:
            home_menu()
        elif index == 1:
            card_layout_menu()
        elif index == 2:
            appearance_menu()
    elif section == 'home_rows':
        home_menu()
    elif section == 'card_layout':
        card_layout_menu()
    elif section == 'appearance':
        appearance_menu()
    elif section == 'catalogs':
        helper_menu()
    elif section == 'weather':
        weather_menu()
        sync_window()
    elif section == 'region':
        region_menu()
    elif section == 'accessibility':
        accessibility_menu()
    elif section == 'power':
        power_menu()
    elif section == 'diagnostics':
        diagnostics_menu()
    elif section == 'playback':
        playback_menu()
    elif section == 'audio':
        audio_menu()
    elif section == 'display':
        display_menu()
    elif section == 'remote':
        remote_tv_menu()
    elif section == 'subtitles':
        index = choose('Subtitles & Accessibility', ['Subtitle settings', 'Accessibility'])
        if index == 0:
            kodi_menu('Subtitles', [
                ('locale.subtitlelanguage', 'Preferred language'), ('subtitles.languages', 'Download languages'),
                ('subtitles.downloadfirst', 'Automatically download first subtitle'),
                ('subtitles.fontsize', 'Text size'), ('subtitles.fontname', 'Font'),
                ('subtitles.style', 'Text style'), ('subtitles.colorpick', 'Subtitle color'),
                ('subtitles.align', 'Position'), ('subtitles.backgroundtype', 'Background style'),
                ('subtitles.bordercolorpick', 'Border color'), ('subtitles.bgcolorpick', 'Background color'),
                ('subtitles.shadowcolor', 'Shadow color'), ('subtitles.overridestyles', 'Override subtitle styles'),
            ])
        elif index == 1:
            accessibility_menu()
    elif section == 'system':
        system_updates_menu()
    elif section == 'advanced':
        advanced_menu()
    elif section == 'maintenance':
        maintenance_menu()
    elif section == 'about':
        DIALOG.ok('About Stremio for Kodi',
                  'Stremio for Kodi is a Stremio-first TV client.\nPlayback engine: Kodi ' +
                  xbmc.getInfoLabel('System.BuildVersion') +
                  '\nYour Stremio account, addons, library and interface are managed by Stremio for Kodi.\nOriginal component licences and credits remain included with their source.')


if __name__ == '__main__':
    try:
        run(sys.argv[1] if len(sys.argv) > 1 else 'account', *sys.argv[2:])
    except Exception:
        DIALOG.ok('Stremio for Kodi', 'The change could not be completed. Your current setup has been kept where possible. Please retry.')
