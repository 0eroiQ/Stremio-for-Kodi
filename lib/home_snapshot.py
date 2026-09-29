"""Fast Home snapshot for constrained Kodi devices.

Contains display rows only: never auth keys or configured addon transport URLs.
"""
import time
from account import Store, library_rows

MAX_ROWS = 40
CONTINUE = 'Continue Watching'


def _key(row):
    return '|'.join(str(row.get(name) or '') for name in ('provider', 'kind', 'catalog_id'))


def _display_row(row):
    items = row.get('items') if isinstance(row, dict) else []
    clean = {
        'label': str((row or {}).get('label') or ''),
        'items': [dict(item) for item in items[:MAX_ROWS] if isinstance(item, dict) and item.get('id')],
        'failed': bool((row or {}).get('failed')),
    }
    key = str((row or {}).get('_key') or _key(row or {}))
    if key != '||':
        clean['_key'] = key
    return clean


def load(directory):
    try:
        state = Store(directory / 'home-snapshot').load()
        rows = state.get('rows')
        if not isinstance(rows, list):
            return []
        return [_display_row(row) for row in rows if isinstance(row, dict)]
    except Exception:
        return []
def save(directory, rows):
    previous = load(directory)
    by_key = {row.get('_key'): row for row in previous if row.get('_key')}
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current = _display_row(row)
        old = by_key.get(current.get('_key'))
        if current['failed'] and not current['items'] and old and old.get('items'):
            current['items'] = old['items']
            current['failed'] = True
        clean.append(current)
    Store(directory / 'home-snapshot').save({'created': time.time(), 'rows': clean})
    return clean


def shell(directory, addons, library):
    """Return snapshot, or a network-free first-run skeleton."""
    cached = load(directory)
    if cached:
        return cached
    from lib.home_catalogs import descriptors
    rows = [dict(spec, items=[], failed=False) for spec in descriptors(addons)]
    return update_continue_rows(rows, library)


def update_continue_rows(rows, library):
    """Replace only Continue Watching using local account state and known artwork."""
    rows = [_display_row(row) for row in rows if isinstance(row, dict)]
    known = {}
    for row in rows:
        if row.get('label') == CONTINUE:
            continue
        for item in row.get('items', []):
            known[(item.get('type'), item.get('id'))] = item
    continuing = []
    for saved in library_rows(library, True):
        item = dict(saved, id=saved.get('_id') or saved.get('id'))
        full = known.get((item.get('type'), item.get('id')))
        if full:
            merged = dict(full)
            merged.update(item)
            item = merged
        continuing.append(item)
    rest = [row for row in rows if row.get('label') != CONTINUE]
    return ([{'label': CONTINUE, 'items': continuing, 'failed': False}] if continuing else []) + rest


def update_continue(directory, library):
    rows = update_continue_rows(load(directory), library)
    Store(directory / 'home-snapshot').save({'created': time.time(), 'rows': rows})
    return rows
