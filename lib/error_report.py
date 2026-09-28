"""Anonymous, privacy-minimised error reporting for Stremio for Kodi.

Reports contain only addon/Kodi/Python versions, broad platform, error class,
context, and basename/function/line stack frames. They never include raw
exception messages, account tokens, addon/provider URLs, API keys, media URLs,
account identifiers, device identifiers, or local filesystem paths.
"""
import hashlib
import json
import os
import sys
import traceback
from urllib.request import Request, urlopen

REPORT_ENDPOINT = 'https://vortexo.app/api/stremio-kodi/v1/report'
REPORT_VERSION = 1
MAX_FRAMES = 8


def _safe_frames(error, limit=MAX_FRAMES):
    if error is None or getattr(error, '__traceback__', None) is None:
        return []
    rows = []
    for frame in traceback.extract_tb(error.__traceback__)[-limit:]:
        filename = os.path.basename(str(frame.filename or 'unknown.py'))
        filename = ''.join(ch for ch in filename if ch.isalnum() or ch in '._-') or 'unknown.py'
        function = ''.join(ch for ch in str(frame.name or 'unknown') if ch.isalnum() or ch in '._<>-') or 'unknown'
        rows.append('{}:{} in {}'.format(filename[:80], int(frame.lineno or 0), function[:80]))
    return rows


def _environment():
    result = {
        'addonVersion': 'unknown',
        'kodiVersion': 'unknown',
        'platform': 'unknown',
        'pythonVersion': '{}.{}.{}'.format(*sys.version_info[:3]),
    }
    try:
        from addon_state import get_addon
        result['addonVersion'] = get_addon().getAddonInfo('version') or 'unknown'
    except Exception:
        pass
    try:
        import xbmc
        result['kodiVersion'] = xbmc.getInfoLabel('System.BuildVersion') or 'unknown'
        for condition, label in (
                ('System.Platform.Android', 'Android'),
                ('System.Platform.OSX', 'macOS'),
                ('System.Platform.Windows', 'Windows'),
                ('System.Platform.Linux', 'Linux'),
                ('System.Platform.IOS', 'iOS')):
            if xbmc.getCondVisibility(condition):
                result['platform'] = label
                break
    except Exception:
        pass
    return result


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def build_payload(context, error=None, environment=None):
    environment = dict(environment or _environment())
    report = {
        'context': str(context or 'Unknown error')[:80],
        'errorType': type(error).__name__ if error is not None else 'ManualReport',
        'addonVersion': str(environment.get('addonVersion') or environment.get('addon') or 'unknown')[:40],
        'kodiVersion': str(environment.get('kodiVersion') or environment.get('kodi') or 'unknown')[:80],
        'platform': str(environment.get('platform') or 'unknown')[:40],
        'pythonVersion': str(environment.get('pythonVersion') or environment.get('python') or 'unknown')[:40],
        'stack': _safe_frames(error),
    }
    fingerprint = hashlib.sha256(_canonical(report).encode('utf-8')).hexdigest()[:12]
    return dict({'reportVersion': REPORT_VERSION, 'fingerprint': fingerprint}, **report)


def send_report(payload, timeout=6):
    """Submit a sanitized report. No credentials are sent and failures stay local."""
    try:
        body = _canonical(payload).encode('utf-8')
        request = Request(
            REPORT_ENDPOINT,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'Stremio-for-Kodi/{}'.format(payload.get('addonVersion', 'unknown')),
            },
            method='POST')
        with urlopen(request, timeout=timeout) as response:
            if int(getattr(response, 'status', 0) or response.getcode()) != 202:
                return False
            data = json.loads(response.read(16 * 1024))
        return bool(data.get('accepted')) and data.get('errorId') == payload.get('fingerprint')
    except Exception:
        return False


def _addon():
    try:
        from addon_state import get_addon
        return get_addon()
    except Exception:
        return None


def automatic_enabled():
    addon = _addon()
    if addon is None:
        return True
    try:
        return addon.getSettingBool('error_reporting_auto')
    except Exception:
        return str(addon.getSetting('error_reporting_auto')).strip().lower() not in ('false', '0', 'no', 'off')


def show_reporting_notice_once():
    """One-time disclosure for the default-on anonymous reporting preference."""
    addon = _addon()
    if addon is None or not automatic_enabled():
        return
    try:
        if addon.getSettingBool('error_reporting_notice_shown'):
            return
    except Exception:
        if str(addon.getSetting('error_reporting_notice_shown')).lower() == 'true':
            return
    try:
        import xbmcgui
        xbmcgui.Dialog().notification(
            'Stremio for Kodi',
            'Anonymous error reporting is on. You can turn it off in Settings > Support.',
            time=7000)
        addon.setSetting('error_reporting_notice_shown', 'true')
    except Exception:
        pass


class _ReportWindowBase:
    """Defined without xbmc at import time so privacy tests can load this module."""


def _report_window_class():
    import xbmcgui
    from addon_state import get_addon

    class ReportWindow(xbmcgui.WindowXMLDialog):
        def __init__(self, *args, **kwargs):
            self.payload = kwargs.pop('payload')
            self.summary = kwargs.pop('summary')
            self.sent = False
            super().__init__(*args, **kwargs)

        def onInit(self):
            self.getControl(101).setLabel('Something went wrong')
            self.getControl(102).setText(self.summary)
            self.getControl(103).setLabel('Error ID: ' + self.payload['fingerprint'])
            self.getControl(104).setText(
                'Only anonymous technical diagnostics are sent. '
                'No tokens, addon URLs, API keys, media URLs, account details or local paths.')
            self.setFocusId(201)

        def onClick(self, control_id):
            if control_id == 201:
                self.getControl(105).setLabel('Sending report…')
                if send_report(self.payload):
                    self.sent = True
                    self.getControl(105).setLabel('Error reported · ' + self.payload['fingerprint'])
                    try:
                        xbmcgui.Dialog().notification(
                            'Stremio for Kodi',
                            'Error reported · ' + self.payload['fingerprint'],
                            time=5000)
                    except Exception:
                        pass
                    self.close()
                else:
                    self.getControl(105).setLabel('Could not send. Check your connection and try again.')
            elif control_id == 202:
                self.close()

        def onAction(self, action):
            if action.getId() in (10, 92, 216, 247):
                self.close()

    return ReportWindow, get_addon


def show_report_dialog(payload, summary):
    try:
        ReportWindow, get_addon = _report_window_class()
        window = ReportWindow(
            'script-stremio-error-report.xml',
            get_addon().getAddonInfo('path'),
            'Main',
            '1080i',
            payload=payload,
            summary=summary)
        window.doModal()
        return window.sent
    except Exception:
        return False


def _safe_log(payload):
    try:
        import xbmc
        xbmc.log(
            'Stremio for Kodi error {}: {} [{}]'.format(
                payload['fingerprint'],
                payload['errorType'],
                ' > '.join(payload['stack']) if payload['stack'] else payload['context']),
            xbmc.LOGERROR)
    except Exception:
        pass


def handle_error(context, error=None, summary='Stremio for Kodi encountered an unexpected error.'):
    """Auto-submit when enabled; otherwise show the one-click in-skin report dialog."""
    payload = build_payload(context, error)
    _safe_log(payload)
    if automatic_enabled() and send_report(payload):
        try:
            import xbmcgui
            xbmcgui.Dialog().notification(
                'Stremio for Kodi',
                'Error reported · ' + payload['fingerprint'],
                time=5000)
        except Exception:
            pass
        return True
    return show_report_dialog(payload, summary)


def manual_report():
    """Settings action: show the same in-skin, one-click report dialog."""
    payload = build_payload('Manual report')
    _safe_log(payload)
    return show_report_dialog(
        payload,
        'Send a small anonymous technical report to help diagnose a problem on this device.')
