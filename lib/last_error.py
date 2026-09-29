"""Keep one validated, anonymous diagnostic for an explicit 'Report last error'.

No log file or exception message is copied. The saved diagnostic is exactly the
existing v1 technical report, so retries retain its original Error ID/versions.
"""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

MAX_BYTES = 16 * 1024
FIELDS = {'reportVersion', 'fingerprint', 'context', 'errorType', 'addonVersion',
          'kodiVersion', 'platform', 'pythonVersion', 'stack'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def validate_payload(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('Unexpected diagnostic fields')
    if type(value['reportVersion']) is not int or value['reportVersion'] != 1:
        raise ValueError('Not a technical report')
    if value['errorType'] in ('ManualReport', 'FeatureRequest'):
        raise ValueError('Feedback is not a captured error')
    patterns = {
        'context': (80, r'[A-Za-z0-9 ._+():-]+'),
        'errorType': (80, r'[A-Za-z_][A-Za-z0-9_.]*'),
        'addonVersion': (40, r'[A-Za-z0-9 ._+():~-]+'),
        'kodiVersion': (80, r'[A-Za-z0-9 ._+():~-]+'),
        'platform': (40, r'[A-Za-z0-9 ._+():~-]+'),
        'pythonVersion': (40, r'[A-Za-z0-9 ._+():~-]+'),
        'fingerprint': (12, r'[0-9a-f]{12}'),
    }
    from lib.report_feedback import SENSITIVE
    for key, (maximum, pattern) in patterns.items():
        text = value[key]
        if not isinstance(text, str) or not text or len(text) > maximum or not re.fullmatch(pattern, text):
            raise ValueError('Invalid diagnostic field')
        if key in ('context', 'addonVersion', 'kodiVersion') and SENSITIVE.search(text):
            raise ValueError('Sensitive diagnostic field')
    frames = value['stack']
    if not isinstance(frames, list) or len(frames) > 8:
        raise ValueError('Invalid diagnostic stack')
    for frame in frames:
        if not isinstance(frame, str) or not re.fullmatch(
                r'[A-Za-z0-9._-]{1,80}:[0-9]{1,7} in [A-Za-z0-9._<>-]{1,80}', frame):
            raise ValueError('Invalid diagnostic frame')
    canonical = _canonical({key: data for key, data in value.items() if key not in ('reportVersion', 'fingerprint')})
    expected = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]
    if not hmac.compare_digest(expected, value['fingerprint']):
        raise ValueError('Diagnostic fingerprint mismatch')
    return json.loads(_canonical(value))


def _path():
    import xbmcvfs
    from addon_state import get_addon
    profile = xbmcvfs.translatePath(get_addon().getAddonInfo('profile'))
    return Path(profile) / 'diagnostics' / 'last-error.json'


def _timestamp(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _write(path, value):
    raw = _canonical(value).encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('Diagnostic is too large')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError('Diagnostic path is a link')
    descriptor, temporary = tempfile.mkstemp(prefix='.last-error-', dir=str(path.parent))
    try:
        # mkstemp is owner-only on POSIX; avoid platform-specific chmod APIs.
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = None
            stream.write(raw)
        os.replace(temporary, str(path))
        temporary = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def remember_error(payload, path=None, now=None):
    """Best effort: failure to save diagnostics must not mask the real error."""
    try:
        checked = validate_payload(payload)
        timestamp = time.time() if now is None else now
        if not _timestamp(timestamp):
            return False
        target = Path(path) if path is not None else _path()
        _write(target, {'schemaVersion': 1, 'savedAt': timestamp, 'sentAt': None, 'payload': checked})
        return True
    except Exception:
        return False


def load_last_error(path=None):
    try:
        target = Path(path) if path is not None else _path()
        if target.is_symlink():
            return None
        with target.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {'schemaVersion', 'savedAt', 'sentAt', 'payload'}:
            return None
        if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or not _timestamp(value['savedAt']):
            return None
        if value['sentAt'] is not None and not _timestamp(value['sentAt']):
            return None
        value['payload'] = validate_payload(value['payload'])
        return value
    except Exception:
        return None


def mark_sent(fingerprint, path=None, now=None):
    try:
        target = Path(path) if path is not None else _path()
        value = load_last_error(target)
        if value is None or value['payload']['fingerprint'] != fingerprint:
            return False
        timestamp = time.time() if now is None else now
        if not _timestamp(timestamp):
            return False
        value['sentAt'] = timestamp
        _write(target, value)
        return True
    except Exception:
        return False
