"""Exact saved-episode labels and bounded resume offsets, without title guessing."""
import math
import re


def resume_seconds(value):
    try:
        seconds = float(value) / 1000
        return seconds if math.isfinite(seconds) and 1 <= seconds < 604800 else 0
    except (TypeError, ValueError):
        return 0


def button_label(saved):
    state = saved.get('state') or {}
    verb = 'Resume' if resume_seconds(state.get('timeOffset')) else 'Play'
    if saved.get('type') == 'series':
        match = re.fullmatch(re.escape(saved['_id']) + r':(\d+):(\d+)', str(state.get('video_id', '')))
        if match and int(match[2]) > 0:
            return '{} Season {}: Episode {}'.format(verb, int(match[1]), int(match[2]))
    return verb


def next_series_episode(videos, series_id, saved=None):
    """Return (video, resume_ms) for the episode the info dialog should offer.

    Active progress resumes the exact saved episode. A completed saved episode
    advances to the following regular episode. With no history, start at S1E1
    (or the first regular episode available). A fully completed series loops to
    its first regular episode for an explicit replay action.
    """
    rows = []
    for video in videos or []:
        if not isinstance(video, dict):
            continue
        try:
            season = int(video.get('season'))
            episode = int(video.get('episode') if video.get('episode') is not None
                          else video.get('number'))
        except (TypeError, ValueError):
            continue
        identity = str(video.get('id') or '')
        if season <= 0 or episode <= 0 or not identity:
            continue
        rows.append((season, episode, identity, video))
    rows.sort(key=lambda row: (row[0], row[1]))
    if not rows:
        return None, 0

    state = (saved or {}).get('state') or {}
    saved_id = str(state.get('video_id') or '')
    raw_offset = state.get('timeOffset')
    offset = resume_seconds(raw_offset)

    if saved_id:
        for index, (_, _, identity, video) in enumerate(rows):
            if identity != saved_id:
                continue
            # Stremio Core uses exactly 1ms as a Continue Watching pointer to
            # the next episode after completing the previous one. It means Play,
            # not Resume and must not advance again.
            try:
                sentinel = int(float(raw_offset)) == 1
            except (TypeError, ValueError):
                sentinel = False
            if sentinel:
                return video, 0
            if offset:
                try:
                    resume_ms = int(float(raw_offset))
                except (TypeError, ValueError):
                    resume_ms = 0
                return video, max(0, resume_ms)
            if index + 1 < len(rows):
                return rows[index + 1][3], 0
            return rows[0][3], 0

    return rows[0][3], 0

def continue_series_target(videos, saved, now=None):
    """Return the only episode eligible for Continue Watching.

    A partial saved episode remains visible. A completed/watched episode never
    does. Its immediate next regular episode is eligible only after its release
    time. Future/unknown next episodes and a finished final episode hide the
    series from Continue Watching.
    """
    from datetime import datetime, timezone
    from lib.episode_state import watched_ids

    rows = []
    for video in videos or []:
        if not isinstance(video, dict):
            continue
        try:
            season = int(video.get('season'))
            episode = int(video.get('episode') if video.get('episode') is not None
                          else video.get('number'))
        except (TypeError, ValueError):
            continue
        identity = str(video.get('id') or '')
        if season > 0 and episode > 0 and identity:
            rows.append((season, episode, identity, video))
    rows.sort(key=lambda row: (row[0], row[1]))
    if not rows:
        return None, 0

    state = (saved or {}).get('state') or {}
    saved_id = str(state.get('video_id') or '')
    raw_offset = state.get('timeOffset')
    watched = watched_ids([row[3] for row in rows], saved)
    current_watched = saved_id in watched or bool(state.get('flaggedWatched'))
    instant = now or datetime.now(timezone.utc)

    def aired(video):
        value = video.get('released') or video.get('firstAired')
        if not value:
            return False
        try:
            release = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if release.tzinfo is None:
                release = release.replace(tzinfo=timezone.utc)
            return release <= instant
        except (TypeError, ValueError):
            return False

    index = next((i for i, row in enumerate(rows) if row[2] == saved_id), None)
    if index is None:
        return None, 0

    try:
        raw_ms = max(0, int(float(raw_offset or 0)))
    except (TypeError, ValueError):
        raw_ms = 0

    # A genuine partial play is known to have been available because the user
    # already played it. Do not hide it merely because a provider omitted dates.
    if raw_ms > 1 and not current_watched:
        return rows[index][3], raw_ms

    # Stremio's 1ms sentinel points at the already-selected next episode.
    if raw_ms == 1 and not current_watched:
        return (rows[index][3], 0) if aired(rows[index][3]) else (None, 0)

    # If this episode is marked watched, only its immediate next unwatched,
    # already-aired episode may enter Continue Watching.
    if current_watched:
        next_index = index + 1
        if next_index >= len(rows):
            return None, 0
        candidate = rows[next_index]
        if candidate[2] in watched or not aired(candidate[3]):
            return None, 0
        return candidate[3], 0

    return None, 0
