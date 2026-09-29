"""Manual watched and Continue Watching actions for media cards."""
from copy import deepcopy
from datetime import datetime, timezone

from account import AccountError, pull_library, request


def _stamp():
    return datetime.now(timezone.utc).isoformat(
        timespec='milliseconds').replace('+00:00', 'Z')


def _item(entries, meta):
    old = next((row for row in entries if isinstance(row, dict)
                and row.get('_id') == meta.get('id')
                and row.get('type') == meta.get('type')), None)
    if old:
        return deepcopy(old)
    stamp = _stamp()
    return {
        '_id': meta['id'], 'type': meta['type'],
        'name': meta.get('name') or meta['id'], 'poster': meta.get('poster'),
        'posterShape': meta.get('posterShape') or 'poster',
        'removed': True, 'temp': True, '_ctime': stamp, 'behaviorHints': {},
        'state': {'timeWatched': 0, 'timeOffset': 0, 'overallTimeWatched': 0,
                  'timesWatched': 0, 'flaggedWatched': 0, 'duration': 0}}


def apply_movie_watched(entries, meta, watched=True):
    if meta.get('type') != 'movie' or not meta.get('id'):
        raise AccountError('Movie watched state requires a movie.')
    item = _item(entries, meta)
    state = item.setdefault('state', {})
    state['timeOffset'] = 0
    state['timeWatched'] = 0
    state['flaggedWatched'] = 1 if watched else 0
    times = max(0, int(state.get('timesWatched') or 0))
    state['timesWatched'] = max(1, times) if watched else max(0, times - 1)
    state['lastWatched'] = _stamp()
    item['_mtime'] = state['lastWatched']
    return item


def apply_remove_continue(entries, meta):
    if not meta.get('id') or meta.get('type') not in ('movie', 'series'):
        raise AccountError('Continue Watching action requires a movie or series.')
    item = _item(entries, meta)
    state = item.setdefault('state', {})
    state['timeOffset'] = 0
    state['timeWatched'] = 0
    item['_mtime'] = _stamp()
    return item


def _sync(store, meta, mutate, request_func=None, pull_func=None):
    request_func = request_func or request
    pull_func = pull_func or pull_library
    local = store.load()
    token = local.get('token')
    if not token:
        raise AccountError('Connect your Stremio account in Settings first.')
    latest = pull_func(token)
    item = mutate(latest, meta)
    response = request_func('https://api.strem.io/api/datastorePut', {
        'authKey': token, 'collection': 'libraryItem', 'changes': [item]})
    if not isinstance(response, dict) or response.get('error'):
        raise AccountError('Stremio rejected the media action.')
    verified = pull_func(token)
    local['library'] = verified
    store.save(local)
    return verified


def sync_movie_watched(store, meta, watched=True):
    return _sync(store, meta, lambda rows, value: apply_movie_watched(rows, value, watched))


def sync_remove_continue(store, meta):
    return _sync(store, meta, apply_remove_continue)
