"""Exact saved-episode labels and bounded resume offsets, without title guessing."""
import math
import re


def resume_seconds(value):
    try:
        seconds = float(value) / 1000
        return seconds if math.isfinite(seconds) and 0 < seconds < 604800 else 0
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
