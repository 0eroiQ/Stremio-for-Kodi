"""Versioned manual feedback and deterministic GitHub labels (no Kodi/network)."""
import hashlib
import json
import re

CATEGORIES = (
    ('login', 'Login'), ('catalogs', 'Home and catalogs'), ('playback', 'Playback'),
    ('subtitles', 'Subtitles'), ('library', 'Library and sync'),
    ('addons', 'Addons'), ('interface', 'Interface'), ('general', 'Other'),
)
FREQUENCIES = ('always', 'sometimes', 'after-restart', 'not-retested', 'not-applicable')
FEEDBACK_KEYS = {'kind', 'category', 'title', 'description', 'frequency'}
# Deliberately reject risky material instead of silently publishing redacted guesses.
SENSITIVE = re.compile(
    r'(?i)(?:[a-z][a-z0-9+.-]*://|www\.|@|(?:[a-z]:[\\/])|\\\\|'
    r'(?:^|\s)/(?:Users|home|mnt|storage|sdcard|private|tmp|var)/|'
    r'\b(?:authkey|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\s*[:=]|'
    r'\bBearer\s+\S+|\bgh[pousr]_[a-z0-9]+|\bgithub_pat_[a-z0-9_]+|'
    r'\bAIza[a-z0-9_-]{20,}|\bsk_(?:live|test)_[a-z0-9]+|'
    r'\beyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+|-----BEGIN|'
    r'\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|app|tv|me|dev)(?:[/:?]|\b))')


def feedback_text(value, minimum, maximum):
    if not isinstance(value, str):
        raise ValueError('Enter plain text.')
    if any(ord(ch) < 32 or ord(ch) == 127 or 0x202A <= ord(ch) <= 0x202E
           or 0x2066 <= ord(ch) <= 0x2069 or 0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise ValueError('Use plain text on one line, without formatting or control characters.')
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise ValueError('Use {} to {} characters.'.format(minimum, maximum))
    if SENSITIVE.search(value) or any(ch in value for ch in ('`', '<', '>')):
        raise ValueError('Remove links, email addresses, mentions, file paths or credentials before sending.')
    return value


def validate_feedback(value):
    if not isinstance(value, dict) or set(value) != FEEDBACK_KEYS:
        raise ValueError('Unexpected feedback fields.')
    kind = value['kind']
    category = value['category']
    if kind not in ('bug', 'feature') or category not in dict(CATEGORIES):
        raise ValueError('Choose a report type and category.')
    frequency = value['frequency']
    if frequency not in FREQUENCIES or (kind == 'feature') != (frequency == 'not-applicable'):
        raise ValueError('Choose a valid frequency.')
    return {'kind': kind, 'category': category,
            'title': feedback_text(value['title'], 5, 100),
            'description': feedback_text(value['description'], 10, 1000),
            'frequency': frequency}


def attach_feedback(payload, feedback):
    feedback = validate_feedback(feedback)
    result = dict(payload)
    result['reportVersion'] = 2
    result['feedback'] = feedback
    result['errorType'] = 'FeatureRequest' if feedback['kind'] == 'feature' else 'ManualReport'
    result['context'] = ('Feature request: ' if feedback['kind'] == 'feature' else 'Manual report: ') + dict(CATEGORIES)[feedback['category']]
    result['stack'] = []
    fields = {key: value for key, value in result.items() if key not in ('fingerprint', 'reportVersion')}
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    result['fingerprint'] = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]
    return result


def report_labels(report, initial=False):
    """Never accept client-supplied labels, priorities or lifecycle changes."""
    feedback = report.get('feedback')
    performance = report.get('errorType') == 'PerformanceReport'
    legacy_manual = feedback is None and report.get('errorType') == 'ManualReport'
    if feedback is not None:
        feedback = validate_feedback(feedback)
        category, kind, source = feedback['category'], feedback['kind'], 'manual'
    else:
        context = str(report.get('context') or '').lower()
        category = 'general'
        for key, prefixes in (
            ('login', ('stremio sign-in', 'account save', 'sign-in')),
            ('subtitles', ('subtitle',)), ('playback', ('playback', 'player', 'stream')),
            ('catalogs', ('home', 'catalog', 'discover', 'search')),
            ('library', ('library',)), ('addons', ('addon',)), ('interface', ('interface', 'ui'))):
            if context.startswith(prefixes):
                category = key
                break
        kind, source = ('unknown', 'manual') if legacy_manual else ('bug', 'auto')
    platform = {'Windows': 'windows', 'Android': 'android', 'macOS': 'macos',
                'Linux': 'linux', 'iOS': 'ios', 'tvOS': 'tvos'}.get(report.get('platform'), 'unknown')
    labels = (['performance', 'area:catalogs', 'platform:' + platform, 'source:manual'] if performance else
              ['feature-request' if kind == 'feature' else 'bug' if kind == 'bug' else 'needs-info',
               'area:' + category, 'platform:' + platform, 'source:' + source])
    if initial and not legacy_manual:
        labels.append('needs-triage')
    return labels
