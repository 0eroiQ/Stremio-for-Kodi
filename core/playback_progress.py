"""Stremio library watch-progress updates driven by Kodi playback.

Pure state helpers live here so they can be regression-tested without Kodi.
Remote writes use the existing official Stremio datastore endpoints.
"""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import zlib

WATCHED_THRESHOLD = 0.70
CREDITS_THRESHOLD = 0.90

_STATE_DEFAULTS = {
    'timeWatched': 0, 'timeOffset': 0, 'overallTimeWatched': 0,
    'timesWatched': 0, 'flaggedWatched': 0, 'duration': 0,
    'video_id': None, 'watched': None, 'noNotif': False,
}


def _now_iso(now=None):
    value = now or datetime.now(timezone.utc)
    return value.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _released(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
def _video_sort_key(video):
    season = video.get('season')
    episode = video.get('episode')
    return (
        season if isinstance(season, int) else -1,
        episode if isinstance(episode, int) else -1,
        str(video.get('released') or video.get('firstAired') or ''),
    )


def _video_ids(videos):
    return [str(v.get('id')) for v in sorted(
        (v for v in videos if isinstance(v, dict) and v.get('id')),
        key=_video_sort_key)]


def _watched_bits(serialized, video_ids):
    bits = [False] * len(video_ids)
    if not serialized or not video_ids:
        return bits
    try:
        anchor, length, encoded = str(serialized).rsplit(':', 2)
        anchor_length = int(length)
        values = zlib.decompress(base64.b64decode(encoded))
        anchor_index = video_ids.index(anchor)
        offset = anchor_length - anchor_index - 1
        for index in range(len(video_ids)):
            previous = index + offset
            if previous >= 0 and previous // 8 < len(values):
                bits[index] = bool((values[previous // 8] >> (previous % 8)) & 1)
    except (ValueError, TypeError, zlib.error):
        pass
    return bits
def _encode_watched(bits, video_ids):
    if not video_ids:
        return None
    values = bytearray((len(video_ids) + 7) // 8)
    for index, watched in enumerate(bits[:len(video_ids)]):
        if watched:
            values[index // 8] |= 1 << (index % 8)
    watched_indexes = [i for i, value in enumerate(bits[:len(video_ids)]) if value]
    last = watched_indexes[-1] if watched_indexes else 0
    anchor = video_ids[last] if video_ids else 'undefined'
    encoded = base64.b64encode(zlib.compress(bytes(values), 6)).decode('ascii')
    return '{}:{}:{}'.format(anchor, last + 1, encoded)


def _mark_video_watched(state, videos, video_id):
    ids = _video_ids(videos)
    if video_id not in ids:
        return
    bits = _watched_bits(state.get('watched'), ids)
    bits[ids.index(video_id)] = True
    state['watched'] = _encode_watched(bits, ids)


def _next_video(videos, current_id, now=None):
    rows = [v for v in videos if isinstance(v, dict) and v.get('id')]
    index = next((i for i, row in enumerate(rows) if str(row.get('id')) == current_id), None)
    if index is None or index + 1 >= len(rows):
        return None
    current, candidate = rows[index], rows[index + 1]
    current_season = current.get('season') if isinstance(current.get('season'), int) else 0
    next_season = candidate.get('season') if isinstance(candidate.get('season'), int) else 0
    if next_season == 0 and current_season != 0:
        return None
    released = _released(candidate.get('released') or candidate.get('firstAired'))
    instant = now or datetime.now(timezone.utc)
    if released is not None:
        if released.tzinfo is None:
            released = released.replace(tzinfo=timezone.utc)
        if released > instant:
            return None
    return candidate


def playback_context(meta, kind, video_id):
    """Return privacy-bounded playback metadata; never include the stream URL."""
    title_id = meta.get('_stremio_meta_id')
    if not title_id:
        title_id = str(video_id).split(':', 1)[0] if kind == 'series' else meta.get('id')
    return {
        'meta_id': str(title_id or ''),
        'video_id': str(video_id or ''),
        'kind': kind,
        'name': str(meta.get('tvshowtitle') or meta.get('name') or meta.get('title') or ''),
        'poster': meta.get('poster'),
        'posterShape': meta.get('posterShape') or 'poster',
        'behaviorHints': deepcopy(meta.get('behaviorHints') or {}),
        'videos': deepcopy(meta.get('videos') or []),
    }


def _new_item(context, now):
    return {
        '_id': context['meta_id'], 'type': context['kind'],
        'name': context.get('name') or context['meta_id'],
        'poster': context.get('poster'), 'posterShape': context.get('posterShape') or 'poster',
        'removed': True, 'temp': True, '_ctime': now, '_mtime': now,
        'behaviorHints': deepcopy(context.get('behaviorHints') or {}),
        'state': deepcopy(_STATE_DEFAULTS),
    }
def apply_progress(entries, context, position_ms, duration_ms, watched_delta_ms,
                   ended=False, now=None):
    """Apply one finished Kodi playback session using Stremio Core thresholds."""
    if context.get('kind') not in ('movie', 'series') or not context.get('meta_id'):
        raise ValueError('Unsupported playback identity')
    position = max(0, int(position_ms or 0))
    duration = max(0, int(duration_ms or 0))
    watched_delta = max(0, int(watched_delta_ms or 0))
    stamp = _now_iso(now)

    old = next((row for row in entries if isinstance(row, dict)
                and row.get('_id') == context['meta_id']
                and row.get('type') == context['kind']), None)
    item = deepcopy(old) if old else _new_item(context, stamp)
    state = item.setdefault('state', {})
    for key, value in _STATE_DEFAULTS.items():
        state.setdefault(key, deepcopy(value))

    video_id = context['video_id']
    if state.get('video_id') != video_id:
        state['overallTimeWatched'] = max(0, int(state.get('overallTimeWatched') or 0))
        state['timeWatched'] = 0
        state['flaggedWatched'] = 0
    state['video_id'] = video_id
    state['timeWatched'] = max(0, int(state.get('timeWatched') or 0)) + watched_delta
    state['overallTimeWatched'] = max(0, int(state.get('overallTimeWatched') or 0)) + watched_delta
    state['timeOffset'] = position
    state['duration'] = duration
    state['lastWatched'] = stamp
    if (duration > 0 and not int(state.get('flaggedWatched') or 0)
            and state['timeWatched'] > duration * WATCHED_THRESHOLD):
        state['flaggedWatched'] = 1
        state['timesWatched'] = max(0, int(state.get('timesWatched') or 0)) + 1
        if context['kind'] == 'series':
            _mark_video_watched(state, context.get('videos') or [], video_id)

    if item.get('temp') and not int(state.get('timesWatched') or 0):
        item['removed'] = True
    if item.get('removed'):
        item['temp'] = True

    completed = bool(ended or (duration > 0 and position > duration * CREDITS_THRESHOLD))
    if completed:
        state['timeOffset'] = 0
        if context['kind'] == 'series':
            nxt = _next_video(context.get('videos') or [], video_id, now)
            if nxt is not None:
                state['video_id'] = str(nxt['id'])
                state['overallTimeWatched'] += max(0, int(state.get('timeWatched') or 0))
                state['timeWatched'] = 0
                state['flaggedWatched'] = 0
                state['timeOffset'] = 1

    item['_mtime'] = stamp
    return item


def sync_progress(store, context, position_ms, duration_ms, watched_delta_ms,
                  ended=False, request_func=None, pull_func=None):
    """Pull latest library, write one item, then verify and refresh local account state."""
    from account import AccountError, request, pull_library
    request_func = request_func or request
    pull_func = pull_func or pull_library
    local = store.load()
    token = local.get('token')
    if not token:
        return None
    latest = pull_func(token)
    item = apply_progress(latest, context, position_ms, duration_ms,
                          watched_delta_ms, ended=ended)
    response = request_func('https://api.strem.io/api/datastorePut', {
        'authKey': token, 'collection': 'libraryItem', 'changes': [item]})
    if not isinstance(response, dict) or response.get('error'):
        raise AccountError('Stremio rejected the watch-progress update.')
    verified = pull_func(token)
    remote = next((row for row in verified if isinstance(row, dict)
                   and row.get('_id') == item['_id'] and row.get('type') == item['type']), None)
    if remote is None:
        raise AccountError('Stremio did not confirm the watch-progress update.')
    local['library'] = verified
    store.save(local)
    return remote
