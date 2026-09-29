"""Manual episode watched-state actions for Stremio accounts."""
from copy import deepcopy
from datetime import datetime, timezone

from account import AccountError, pull_library, request
from playback_progress import _encode_watched, _video_ids, _watched_bits


def _regular(videos):
    rows = []
    for video in videos or []:
        if not isinstance(video, dict) or not video.get('id'):
            continue
        try:
            season = int(video.get('season'))
            episode = int(video.get('episode') if video.get('episode') is not None
                          else video.get('number'))
        except (TypeError, ValueError):
            continue
        if season > 0 and episode > 0:
            rows.append((season, episode, str(video['id']), video))
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def range_through(videos, target_id):
    rows = _regular(videos)
    index = next((i for i, row in enumerate(rows) if row[2] == str(target_id)), None)
    if index is None:
        raise AccountError('Selected episode is not available in this series.')
    return [row[2] for row in rows[:index + 1]]


def through_is_watched(videos, target_id, watched):
    """True only when every regular episode through target is already watched."""
    selected = range_through(videos, target_id)
    watched = set(str(value) for value in (watched or ()))
    return bool(selected) and all(identity in watched for identity in selected)


def apply_through(entries, meta, target_id, watched=True, now=None):
    """Return one updated series library item; no network side effects."""
    if meta.get('type') != 'series' or not meta.get('id'):
        raise AccountError('Episode watched state requires a series.')
    videos = meta.get('videos') or []
    selected = set(range_through(videos, target_id))
    ids = _video_ids(videos)
    if not ids:
        raise AccountError('No episode metadata is available.')

    old = next((row for row in entries if isinstance(row, dict)
                and row.get('_id') == meta['id'] and row.get('type') == 'series'), None)
    stamp = (now or datetime.now(timezone.utc)).isoformat(
        timespec='milliseconds').replace('+00:00', 'Z')
    item = deepcopy(old) if old else {
        '_id': meta['id'], 'type': 'series', 'name': meta.get('name') or meta['id'],
        'poster': meta.get('poster'), 'posterShape': meta.get('posterShape') or 'poster',
        'removed': True, 'temp': True, '_ctime': stamp, 'behaviorHints': {},
        'state': {'timeWatched': 0, 'timeOffset': 0, 'overallTimeWatched': 0,
                  'timesWatched': 0, 'flaggedWatched': 0, 'duration': 0},
    }
    state = item.setdefault('state', {})
    bits = _watched_bits(state.get('watched'), ids)
    for index, identity in enumerate(ids):
        if identity in selected:
            bits[index] = bool(watched)
    state['watched'] = _encode_watched(bits, ids)
    state['video_id'] = str(target_id)
    state['timeOffset'] = 0
    state['timeWatched'] = 0
    state['flaggedWatched'] = 1 if watched else 0
    if watched:
        state['timesWatched'] = max(1, int(state.get('timesWatched') or 0))
        # Mirror normal playback completion: if the immediate next episode has
        # already aired, point Continue Watching at it with Stremio's 1ms sentinel.
        regular = _regular(videos)
        target_index = next((i for i, row in enumerate(regular) if row[2] == str(target_id)), None)
        if target_index is not None and target_index + 1 < len(regular):
            candidate = regular[target_index + 1][3]
            released = candidate.get('released') or candidate.get('firstAired')
            try:
                release = datetime.fromisoformat(str(released).replace('Z', '+00:00'))
                if release.tzinfo is None:
                    release = release.replace(tzinfo=timezone.utc)
                instant = now or datetime.now(timezone.utc)
                if release <= instant:
                    state['video_id'] = str(candidate.get('id'))
                    state['timeOffset'] = 1
                    state['flaggedWatched'] = 0
            except (TypeError, ValueError):
                pass
    state['lastWatched'] = stamp
    item['_mtime'] = stamp
    return item, selected


def sync_through(store, meta, target_id, watched=True,
                 request_func=None, pull_func=None):
    request_func = request_func or request
    pull_func = pull_func or pull_library
    local = store.load()
    token = local.get('token')
    if not token:
        raise AccountError('Connect your Stremio account in Settings first.')
    latest = pull_func(token)
    item, selected = apply_through(latest, meta, target_id, watched)
    response = request_func('https://api.strem.io/api/datastorePut', {
        'authKey': token, 'collection': 'libraryItem', 'changes': [item]})
    if not isinstance(response, dict) or response.get('error'):
        raise AccountError('Stremio rejected the episode watched-state update.')
    verified = pull_func(token)
    remote = next((row for row in verified if isinstance(row, dict)
                   and row.get('_id') == meta['id'] and row.get('type') == 'series'), None)
    if remote is None:
        raise AccountError('Stremio did not confirm the episode watched-state update.')
    local['library'] = verified
    store.save(local)
    return remote, selected


def apply_single(entries, meta, target_id, watched=True, now=None):
    """Change only one episode while preserving every other watched bit."""
    videos = meta.get('videos') or []
    ids = _video_ids(videos)
    if str(target_id) not in ids:
        raise AccountError('Selected episode is not available in this series.')
    old = next((row for row in entries if isinstance(row, dict)
                and row.get('_id') == meta.get('id') and row.get('type') == 'series'), None)
    original = _watched_bits(((old or {}).get('state') or {}).get('watched'), ids)
    item, _ = apply_through(entries, meta, target_id, watched, now)
    bits = list(original)
    bits[ids.index(str(target_id))] = bool(watched)
    item['state']['watched'] = _encode_watched(bits, ids)
    return item, {str(target_id)}


def sync_single(store, meta, target_id, watched=True,
                request_func=None, pull_func=None):
    request_func = request_func or request
    pull_func = pull_func or pull_library
    local = store.load()
    token = local.get('token')
    if not token:
        raise AccountError('Connect your Stremio account in Settings first.')
    latest = pull_func(token)
    item, selected = apply_single(latest, meta, target_id, watched)
    response = request_func('https://api.strem.io/api/datastorePut', {
        'authKey': token, 'collection': 'libraryItem', 'changes': [item]})
    if not isinstance(response, dict) or response.get('error'):
        raise AccountError('Stremio rejected the episode watched-state update.')
    verified = pull_func(token)
    remote = next((row for row in verified if isinstance(row, dict)
                   and row.get('_id') == meta['id'] and row.get('type') == 'series'), None)
    if remote is None:
        raise AccountError('Stremio did not confirm the episode watched-state update.')
    local['library'] = verified
    store.save(local)
    return remote, selected
