"""User-configurable lifetimes for non-sensitive browsing response caches.

None means unlimited; zero means disabled. Account sessions, Premium tokens,
signed streams, subtitle playback context and Kodi's own image cache are excluded.
"""
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, unquote, parse_qs

GROUPS = (
    ('catalog', 'Catalogs / Discover', '15m'),
    ('search', 'Search results', '15m'),
    ('metadata', 'Movie / series / episode metadata', '24h'),
    ('ratings', 'MDbList ratings', '24h'),
)
DEFAULTS = {key: value for key, _, value in GROUPS}
MAX_DURATION = 100 * 366 * 86400
UNITS = {'s': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
         'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
         'h': 3600, 'hr': 3600, 'hrs': 3600, 'hour': 3600, 'hours': 3600,
         'd': 86400, 'day': 86400, 'days': 86400,
         'w': 604800, 'week': 604800, 'weeks': 604800}


def setting_id(group):
    if group not in DEFAULTS:
        raise ValueError('Unknown cache category')
    return 'cache_' + group + '_ttl'


def _text(value):
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError('Enter a number, a duration, off or unlimited.')
    return value.strip().lower()


def parse_duration(value):
    text = _text(value)
    if text in ('unlimited', 'never', 'forever'):
        return None
    if text in ('off', 'disabled', 'disable', '0'):
        return 0
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([a-z]+)?', text)
    if not match or (match[2] or 'm') not in UNITS:
        raise ValueError('Use 15m, 2h, 7d, off or unlimited. A number alone means minutes.')
    seconds = Decimal(match[1]) * UNITS[match[2] or 'm']
    if seconds < 1 or seconds > MAX_DURATION or seconds != int(seconds):
        raise ValueError('Use a duration of at least one whole second, or unlimited.')
    return int(seconds)


def parse_size(value):
    text = _text(value)
    if text in ('unlimited', 'none'):
        return None
    if text in ('off', 'disabled', '0'):
        return 0
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(mb|mib|gb|gib)?', text)
    if not match:
        raise ValueError('Enter a size in MB, e.g. 128, 512 MB, 2 GB, or unlimited.')
    amount = Decimal(match[1]) * (1024 ** 3 if match[2] in ('gb', 'gib') else 1024 ** 2)
    if not 1 <= amount <= 1024 ** 5:
        raise ValueError('Enter a positive cache size, off or unlimited.')
    return int(amount)


def format_duration(seconds):
    if seconds is None:
        return 'Unlimited (no time expiry)'
    if seconds == 0:
        return 'Disabled'
    for suffix, unit in (('day', 86400), ('hour', 3600), ('minute', 60)):
        if seconds % unit == 0:
            count = seconds // unit
            return '{} {}{}'.format(count, suffix, '' if count == 1 else 's')
    return '{} seconds'.format(seconds)


def format_size(size):
    if size is None:
        return 'Unlimited (no data-size cap)'
    if size == 0:
        return 'Disabled'
    return '{:g} MB'.format(size / 1048576)


def _setting(key):
    try:
        from addon_state import get_addon
        return get_addon().getSetting(key)
    except Exception:
        return ''


def read_policy(get_setting=None):
    getter = get_setting or _setting
    values, errors = {}, []
    for group, label, default in GROUPS:
        key = setting_id(group)
        try:
            raw = getter(key) or default
            values[group] = parse_duration(raw)
        except (ValueError, TypeError, InvalidOperation):
            values[group] = parse_duration(default)
            errors.append(label + ': invalid duration; using ' + default)
    try:
        values['max_bytes'] = parse_size(getter('cache_max_mb') or '64')
    except (ValueError, TypeError, InvalidOperation):
        values['max_bytes'] = 64 * 1048576
        errors.append('Cache size: invalid value; using 64 MB')
    values['errors'] = errors
    return values


def resource_category(url):
    """Only Stremio catalog/meta resource paths are eligible here."""
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https'):
        return None
    parts = parsed.path.split('/')
    # A resource has an id, optional extras, and a .json suffix. Earlier path
    # components can be provider configuration; do not mistake them for resources.
    if not parts[-1].endswith('.json'):
        return None
    for index in range(len(parts) - 3, 0, -1):
        remaining = len(parts) - index
        resource = unquote(parts[index])
        if resource not in ('catalog', 'meta', 'stream', 'subtitles') or remaining not in (3, 4):
            continue
        if resource in ('stream', 'subtitles'):
            return None
        if resource == 'meta':
            return 'metadata'
        extras = parse_qs(parts[-1][:-5], keep_blank_values=True) if remaining == 4 else {}
        return 'search' if 'search' in extras or 'search' in parse_qs(parsed.query, keep_blank_values=True) else 'catalog'
    return None


def open_cache(group, policy=None):
    """Best-effort cache: unavailable storage must not break network retrieval."""
    policy = policy or read_policy()
    if group not in DEFAULTS or policy[group] == 0 or policy['max_bytes'] == 0:
        return None
    try:
        from pathlib import Path
        from addon_state import get_addon
        import xbmcvfs
        from lib.disk_cache import DiskCache
        directory = Path(xbmcvfs.translatePath(get_addon().getAddonInfo('profile'))) / 'cache'
        return DiskCache(directory, max_bytes=policy['max_bytes'], category=group,
                         ttl=policy[group], legacy_ttl=parse_duration(DEFAULTS[group]))
    except Exception:
        return None
