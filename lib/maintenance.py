"""Cache controls for addon-owned response data only; never clears login/library."""
from lib.ui_dialogs import dialog as themed_dialog
from lib.cache_policy import (GROUPS, DEFAULTS, read_policy, setting_id,
                              parse_duration, parse_size, format_duration, format_size)

PRESETS = ('off', '5m', '15m', '30m', '1h', '6h', '12h', '24h', '7d', '30d', 'unlimited')
SIZES = ('off', '32', '64', '128', '256', '512', '1024', 'unlimited')


def _cache(policy=None):
    from pathlib import Path
    import xbmcvfs
    from addon_state import get_addon
    from lib.disk_cache import DiskCache
    policy = policy or read_policy()
    directory = Path(xbmcvfs.translatePath(get_addon().getAddonInfo('profile'))) / 'cache'
    return DiskCache(directory, max_bytes=policy['max_bytes'])


def information(cache, policy):
    stats = cache.stats()
    lines = ['{} cached responses ({:.2f} MB of response data).'.format(
        stats['count'], stats['bytes'] / 1048576)]
    for group, label, _ in GROUPS:
        entry = stats['categories'].get(group, {'count': 0, 'bytes': 0})
        lines.append('{}: {} | {} responses, {:.2f} MB'.format(
            label, format_duration(policy[group]), entry['count'], entry['bytes'] / 1048576))
    legacy = stats['categories'].get('legacy')
    if legacy and legacy['count']:
        lines.append('Older entries: {} (assigned a category when read again).'.format(legacy['count']))
    lines += ['', 'Maximum response data: ' + format_size(policy['max_bytes']),
              'SQLite file including overhead: {:.2f} MB.'.format(stats['database_bytes'] / 1048576),
              '', 'Unlimited lifetime prevents time expiry, but the data-size cap can still evict old entries.',
              'Unlimited size uses available disk space; it is not unlimited storage.',
              'Changes affect the next data fetch. Reopen the addon to refresh an already open page.',
              'These settings do not change login, Premium tokens, playback links, subtitles or Kodi image caching.']
    if policy['errors']:
        lines += ['', 'Invalid settings (defaults used):'] + policy['errors']
    return '\n'.join(lines)


def apply_settings():
    policy = read_policy()
    cache = _cache(policy)
    cache.apply_policy({key: policy[key] for key in DEFAULTS})


def cache_action(clear=False):
    import xbmcgui
    dialog = themed_dialog()
    try:
        policy = read_policy()
        cache = _cache(policy)
        if clear:
            if not dialog.yesno('Clear response cache',
                    'Clear addon catalogs, search, metadata and ratings? Your login, library and playback data are kept.',
                    nolabel='Cancel', yeslabel='Clear cache'):
                return False
            cache.clear()
            dialog.ok('Stremio for Kodi cache', 'Response cache cleared. Reopen the addon to refresh the current page.')
        else:
            dialog.textviewer('Stremio for Kodi cache', information(cache, policy))
        return True
    except Exception:
        dialog.ok('Stremio for Kodi cache', 'Could not access the cache. Close the addon and try again.')
        return False


def clear_selected():
    import xbmcgui
    dialog = themed_dialog()
    choices = [(key, label) for key, label, _ in GROUPS] + [('legacy', 'Older entries (not yet classified)')]
    selected = dialog.select('Clear which cache?', [label for _, label in choices])
    if selected < 0 or selected >= len(choices):
        return False
    key, label = choices[selected]
    if not dialog.yesno('Clear ' + label,
                       'Clear only this response cache? Your login and library are kept.',
                       nolabel='Cancel', yeslabel='Clear'):
        return False
    try:
        _cache().clear(key)
        dialog.ok('Stremio for Kodi cache', label + ' cache cleared. Reopen the addon to refresh the current page.')
        return True
    except Exception:
        dialog.ok('Stremio for Kodi cache', 'Could not clear this cache. Please try again.')
        return False


def _choose_duration(dialog, label, current):
    choices = [format_duration(parse_duration(value)) for value in PRESETS] + ['Custom duration...']
    chosen = dialog.select(label + ' - cache lifetime', choices)
    if chosen < 0:
        return None
    if chosen < len(PRESETS):
        result = PRESETS[chosen]
    elif chosen == len(PRESETS):
        unit = dialog.select('Custom duration - unit', ['Minutes', 'Hours', 'Days'])
        if not 0 <= unit <= 2:
            return None
        raw = dialog.input('How many ' + ('minutes', 'hours', 'days')[unit] + '?')
        if not raw or not raw.strip():
            return None
        result = raw.strip() + ('m', 'h', 'd')[unit]
        try:
            parse_duration(result)
        except ValueError as error:
            dialog.ok('Invalid cache duration', str(error))
            return None
    else:
        return None
    if result == 'unlimited' and not dialog.yesno('Unlimited lifetime',
            'This data will not expire by time. It may become outdated until you clear the cache. The size limit still applies.',
            nolabel='Cancel', yeslabel='Use unlimited'):
        return None
    return result


def _choose_size(dialog):
    chosen = dialog.select('Maximum response data', [format_size(parse_size(value)) for value in SIZES] + ['Custom size in MB...'])
    if chosen < 0:
        return None
    if chosen < len(SIZES):
        result = SIZES[chosen]
    elif chosen == len(SIZES):
        result = dialog.input('Cache size in MB (e.g. 250)')
        if not result or not result.strip():
            return None
        try:
            parse_size(result)
        except ValueError as error:
            dialog.ok('Invalid cache size', str(error))
            return None
    else:
        return None
    if result == 'unlimited' and not dialog.yesno('Unlimited cache size',
            'No automatic response-data size cap. Cache data can fill available disk space. Continue?',
            nolabel='Cancel', yeslabel='Use unlimited'):
        return None
    return result


def configure_cache():
    import xbmcgui
    from addon_state import get_addon
    addon = get_addon()
    dialog = themed_dialog()
    while True:
        policy = read_policy(addon.getSetting)
        labels = [label + ': ' + format_duration(policy[key]) for key, label, _ in GROUPS]
        labels += ['Maximum response data: ' + format_size(policy['max_bytes']),
                   'Restore cache defaults', 'Done']
        chosen = dialog.select('Stremio for Kodi - cache settings', labels)
        if chosen < 0 or chosen >= len(GROUPS) + 2:
            return
        if chosen < len(GROUPS):
            group, label, default = GROUPS[chosen]
            result = _choose_duration(dialog, label, addon.getSetting(setting_id(group)) or default)
            if result is None:
                continue
            addon.setSetting(setting_id(group), result)
        elif chosen == len(GROUPS):
            result = _choose_size(dialog)
            if result is None:
                continue
            addon.setSetting('cache_max_mb', result)
        else:
            if not dialog.yesno('Restore cache defaults',
                    'Use 15 minutes for catalogs/search, 24 hours for metadata/ratings, and a 64 MB data cap?',
                    nolabel='Cancel', yeslabel='Restore'):
                continue
            for group, _, value in GROUPS:
                addon.setSetting(setting_id(group), value)
            addon.setSetting('cache_max_mb', '64')
        try:
            apply_settings()
        except Exception:
            dialog.ok('Cache settings saved', 'The values are saved. The cache is busy; they will apply on the next data fetch.')
