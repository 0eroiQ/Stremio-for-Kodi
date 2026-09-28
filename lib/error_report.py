"""Privacy-preserving GitHub issue drafts for user-visible Stremio for Kodi errors.

Never include raw exception messages, account tokens, addon/provider URLs, API keys,
media URLs or other user data in generated reports.
"""
import hashlib
import os
import sys
import traceback
import webbrowser
from urllib.parse import urlencode

ISSUES_NEW = 'https://github.com/0eroiQ/Stremio-for-Kodi/issues/new'
SHORT_ISSUES = 'github.com/0eroiQ/Stremio-for-Kodi/issues/new'


def _safe_frames(error, limit=8):
    if error is None or getattr(error, '__traceback__', None) is None:
        return []
    frames = traceback.extract_tb(error.__traceback__)[-limit:]
    return [
        '{}:{} in {}'.format(os.path.basename(frame.filename), frame.lineno, frame.name)
        for frame in frames
    ]


def _environment():
    result = {
        'addon': 'unknown',
        'kodi': 'unknown',
        'platform': 'unknown',
        'python': '{}.{}.{}'.format(*sys.version_info[:3]),
    }
    try:
        from addon_state import get_addon
        result['addon'] = get_addon().getAddonInfo('version') or 'unknown'
    except Exception:
        pass
    try:
        import xbmc
        result['kodi'] = xbmc.getInfoLabel('System.BuildVersion') or 'unknown'
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


def build_issue_url(context, error=None, environment=None):
    """Build a pre-filled issue URL using only deliberately non-sensitive fields."""
    environment = dict(environment or _environment())
    error_type = type(error).__name__ if error is not None else 'Manual report'
    frames = _safe_frames(error)
    fingerprint_source = '|'.join([
        str(context), error_type, environment.get('addon', 'unknown'),
        environment.get('kodi', 'unknown'), *frames
    ])
    report_id = hashlib.sha256(fingerprint_source.encode('utf-8')).hexdigest()[:10]
    title = '[Bug] {} ({})'.format(context, report_id)
    stack = '\n'.join(frames) if frames else 'No automatic stack was captured.'
    body = """## What happened?

<!-- Please describe what you were doing immediately before the problem appeared. -->

## Automatically collected diagnostics

- Error ID: `{}`
- Context: `{}`
- Error type: `{}`
- Stremio for Kodi: `{}`
- Kodi: `{}`
- Platform: `{}`
- Python: `{}`

### Sanitized stack

```text
{}
```

> Privacy: this report intentionally does **not** include Stremio tokens, addon/provider URLs, API keys, media URLs, account details, or raw exception messages.
""".format(
        report_id, context, error_type,
        environment.get('addon', 'unknown'),
        environment.get('kodi', 'unknown'),
        environment.get('platform', 'unknown'),
        environment.get('python', 'unknown'),
        stack)
    return ISSUES_NEW + '?' + urlencode({'title': title, 'body': body}), report_id


def _open_issue_url(url, report_id):
    try:
        import xbmc
        import xbmcgui
        if xbmc.getCondVisibility('System.Platform.Android'):
            # Kodi exposes Android VIEW intents. Chrome is attempted when present;
            # the short URL below remains available if the device has no browser.
            xbmc.executebuiltin(
                'StartAndroidActivity(com.android.chrome,android.intent.action.VIEW,,"{}")'.format(url))
            xbmcgui.Dialog().notification(
                'GitHub issue',
                'If no browser opens: {}  Error ID {}'.format(SHORT_ISSUES, report_id),
                time=8000)
            return True
    except Exception:
        pass

    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass

    try:
        import xbmcgui
        xbmcgui.Dialog().textviewer(
            'Report this issue',
            'Open this address in a browser:\n\n{}\n\nError ID: {}\n\n'
            'The issue form will contain the safe diagnostics above automatically.'
            .format(SHORT_ISSUES, report_id))
    except Exception:
        pass
    return False


def offer_report(context, error=None, summary='Stremio for Kodi encountered an unexpected error.'):
    """Ask before opening GitHub. Nothing is uploaded automatically."""
    url, report_id = build_issue_url(context, error)
    try:
        import xbmc
        safe_frames = _safe_frames(error)
        xbmc.log(
            'Stremio for Kodi error {}: {} [{}]'.format(
                report_id,
                type(error).__name__ if error is not None else 'Manual report',
                ' > '.join(safe_frames) if safe_frames else context),
            xbmc.LOGERROR)
    except Exception:
        pass

    try:
        import xbmcgui
        dialog = xbmcgui.Dialog()
        if not dialog.yesno(
                'Report Stremio for Kodi error',
                '{}\n\nError ID: {}\n\nOpen a pre-filled GitHub issue? '
                'No tokens, addon URLs, API keys or media URLs will be included.'
                .format(summary, report_id),
                nolabel='Not now', yeslabel='Report issue'):
            return False
    except Exception:
        return False
    return _open_issue_url(url, report_id)


def manual_report():
    """Settings action for a user-initiated bug report."""
    url, report_id = build_issue_url('Manual report')
    return _open_issue_url(url, report_id)
