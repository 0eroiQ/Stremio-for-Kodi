"""Anonymous, privacy-minimised error reporting for Stremio for Kodi.

Reports contain only addon/Kodi/Python versions, broad platform, error class,
context, and basename/function/line stack frames. They never include raw
exception messages, account tokens, addon/provider URLs, API keys, media URLs,
account identifiers, device identifiers, or local filesystem paths.
"""
from lib.ui_dialogs import dialog as themed_dialog
import hashlib
import json
import os
import sys
import traceback
from urllib.request import Request, urlopen

REPORT_ENDPOINT = 'https://vortexo.app/api/stremio-kodi/v1/report'
REPORT_VERSION = 1
MAX_FRAMES = 8


from lib.theme import window as themed_window


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
        themed_dialog().notification(
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
        payload = None
        summary = ''
        sent = False

        def onInit(self):
            manual = self.payload.get('feedback')
            heading = 'Feature request' if manual and manual['kind'] == 'feature' else 'Bug report' if manual else 'Something went wrong'
            if getattr(self, 'replay', False):
                heading = 'Report last error'
            self.getControl(101).setLabel(heading)
            if manual or getattr(self, 'replay', False) or self.payload.get('errorType') == 'PerformanceReport':
                self.getControl(201).setLabel('Send to GitHub')
            self.getControl(102).setText(self.summary)
            self.getControl(103).setLabel('Error ID: ' + self.payload['fingerprint'])
            self.getControl(104).setText(
                'Only anonymous technical diagnostics are sent. '
                'No tokens, addon URLs, API keys, media URLs, account details or local paths.')
            if manual:
                self.getControl(104).setText('Your reviewed title and description will be public on GitHub. Cancel sends nothing.')
            elif self.payload.get('errorType') == 'PerformanceReport':
                self.getControl(104).setText('Only Home stage timings, item/row counts and broad software/platform versions are sent. No Kodi log, URLs, account data, titles, API keys or device IDs.')

            self.setFocusId(202 if getattr(self, 'replay', False) else 201)

        def onClick(self, control_id):
            if control_id == 201:
                self.getControl(105).setLabel('Sending report…')
                if send_report(self.payload):
                    self.sent = True
                    self.getControl(105).setLabel('Error reported · ' + self.payload['fingerprint'])
                    try:
                        themed_dialog().notification(
                            'Stremio for Kodi',
                            'Error reported · ' + self.payload['fingerprint'],
                            time=5000)
                    except Exception:
                        pass
                    self.close()
                else:
                    self.getControl(105).setLabel('Report not sent. The reporting service could not accept it. Please try again later.')
            elif control_id == 202:
                self.close()

        def onAction(self, action):
            if action.getId() in (10, 92, 216, 247):
                self.close()

    return ReportWindow, get_addon


def show_report_dialog(payload, summary, replay=False):
    try:
        ReportWindow, get_addon = _report_window_class()
        window = themed_window(ReportWindow,
            'script-stremio-error-report.xml',
            get_addon().getAddonInfo('path'),
            'Main',
            '1080i')
        window.payload = payload
        window.replay = replay
        window.summary = summary
        window.sent = False
        window.doModal()
        if window.sent and not payload.get('feedback'):
            from lib.last_error import mark_sent
            mark_sent(payload['fingerprint'])
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
    if error is not None:
        from lib.last_error import remember_error
        remember_error(payload)
    _safe_log(payload)
    if automatic_enabled() and send_report(payload):
        from lib.last_error import mark_sent
        mark_sent(payload['fingerprint'])
        try:
            import xbmcgui
            themed_dialog().notification(
                'Stremio for Kodi',
                'Error reported · ' + payload['fingerprint'],
                time=5000)
        except Exception:
            pass
        return True
    return show_report_dialog(payload, summary)


def report_last_error(dialog=None):
    """Review and explicitly resend the last captured v1 diagnostic, not a log."""
    import time
    from lib.last_error import load_last_error
    from lib.report_feedback import report_labels
    if dialog is None:
        import xbmcgui
        dialog = themed_dialog()
    record = load_last_error()
    if record is None:
        dialog.ok('Report last error',
            'No saved error is available. This option records errors caught after this update. '
            'Reproduce the problem, or choose Bug report to describe it manually.')
        return False
    payload = record['payload']
    captured = time.strftime('%d %b %Y %H:%M', time.localtime(record['savedAt']))
    sent = 'Already sent. Sending again updates the same Error ID.' if record['sentAt'] else 'Not confirmed as sent.'
    labels = ', '.join(report_labels(payload))
    review = '\n'.join([
        'Last captured error: ' + captured, sent,
        'Context: ' + payload['context'], 'Error type: ' + payload['errorType'],
        'Original addon version: ' + payload['addonVersion'],
        'Original Kodi version: ' + payload['kodiVersion'],
        'Platform: ' + payload['platform'], 'Python: ' + payload['pythonVersion'],
        'Error ID: ' + payload['fingerprint'], 'Labels: ' + labels, '',
        'Sanitized stack:', '\n'.join(payload['stack']) or 'No stack was captured.', '',
        'Only this anonymous diagnostic will be sent for a public GitHub issue. '
        'No raw exception message, log file, login, provider URLs or account data is included.',
        'Close this preview to choose Send to GitHub or Cancel.'])
    dialog.textviewer('Review last error', review)
    return show_report_dialog(payload,
        '{}\n{}: {}\nAddon {} | {}\n{}'.format(
            captured, payload['context'], payload['errorType'],
            payload['addonVersion'], payload['platform'], sent), replay=True)


def _valid_choice(value, choices):
    return type(value) is int and 0 <= value < len(choices)


def _feedback_input(dialog, heading, minimum, maximum):
    from lib.report_feedback import feedback_text
    previous = ''
    while True:
        value = dialog.input(heading, defaultt=previous)
        if not value or not value.strip():
            return None
        try:
            return feedback_text(value, minimum, maximum)
        except ValueError as error:
            dialog.ok('Check your message', str(error))
            previous = value[:maximum]


def manual_report(dialog=None):
    """Explicit public feedback: cancel at any step sends nothing."""
    from lib.report_feedback import CATEGORIES, attach_feedback, report_labels
    if dialog is None:
        import xbmcgui
        dialog = themed_dialog()
    types = ('Bug report', 'Feature request', 'Report last error')
    selected = dialog.select('Stremio for Kodi - feedback', list(types))
    if not _valid_choice(selected, types):
        return False
    if selected == 2:
        return report_last_error(dialog)
    category = dialog.select('Choose a category', [label for key, label in CATEGORIES])
    if not _valid_choice(category, CATEGORIES):
        return False
    if not dialog.yesno('Public GitHub feedback',
            'Your title, description, category and device versions will be public on GitHub. '
            'Do not include personal details, passwords, account keys, links or logs. '
            'You can review the message before sending.', nolabel='Cancel', yeslabel='Continue'):
        return False
    title = _feedback_input(dialog, 'Feature request title (5-100 characters)' if selected else
                            'Bug title (5-100 characters)', 5, 100)
    if title is None:
        return False
    description = _feedback_input(dialog,
        'Describe the idea and why it helps' if selected else
        'Steps to reproduce, expected result and what happens instead', 10, 1000)
    if description is None:
        return False
    frequency = 'not-applicable'
    if not selected:
        choices = ('Every time', 'Sometimes', 'After restart', 'Not retested')
        repeat = dialog.select('How often does it happen?', list(choices))
        if not _valid_choice(repeat, choices):
            return False
        frequency = ('always', 'sometimes', 'after-restart', 'not-retested')[repeat]
    payload = attach_feedback(build_payload('Manual report'), {
        'kind': 'feature' if selected else 'bug', 'category': CATEGORIES[category][0],
        'title': title, 'description': description, 'frequency': frequency})
    labels = ', '.join(report_labels(payload, initial=True))
    review = '{}\n\n{}\n\nLabels: {}\nFrequency: {}\n\nNo account data or raw logs are attached.'.format(
        title, description, labels, frequency)
    dialog.textviewer('Review public ' + types[selected].lower(), review)
    # The existing addon-owned dialog performs the final, explicit Send action.
    return show_report_dialog(payload, '{}\n{}\n\n{}'.format(types[selected], title, labels))
