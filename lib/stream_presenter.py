"""Display-only stream rows. Never change resolver data or expose stream URLs."""
import re
from core.stream_ui import stream_card


def line(value, limit=350):
    text = re.sub(r'<[^>]*>', '', str(value or ''))
    text = re.sub(r'\[/?(?:B|I|CR|TAB|LIGHT|COLOR[^\]]*|UPPERCASE|LOWERCASE)\]', '', text, flags=re.I)
    text = re.sub(r'(?:https?|plugin|magnet)://\S+', '[source]', text, flags=re.I)
    text = ''.join(' ' if ord(ch) < 32 or ord(ch) == 127 else ch for ch in text)
    return ' '.join(text.split())[:limit]


def presentation(row):
    raw = row.get('card')
    card = raw if isinstance(raw, dict) else stream_card(row)
    quality = line(card.get('quality') or 'AUTO', 24)
    provider = line(card.get('provider') or row.get('provider') or 'Stream', 70)
    tech = line(card.get('tech'))
    parts = [quality]
    parts.extend(p for p in tech.split(' • ') if p in
                 ('AV1', 'H.265', 'H.264', 'Dolby Vision', 'HDR10', 'HDR'))
    if card.get('size'):
        parts.append(line(card['size'], 24))
    if provider:
        parts.append(provider)
    title = ' · '.join(dict.fromkeys(parts))
    detail = line(card.get('filename') or row.get('filename') or row.get('detail') or row.get('label'))
    return {'title': title, 'detail': detail or provider, 'quality': quality}


def quality_choices(rows):
    values = {presentation(row)['quality'] for row in rows}
    order = ('4K', '1080p', '720p', '480p', '360p', 'AUTO')
    return ['All'] + sorted(values, key=lambda q: (order.index(q) if q in order else 99, q))


def target_label(meta, identity):
    if meta.get('type') != 'series':
        return line(meta.get('name') or meta.get('title'), 110)
    video = next((v for v in meta.get('videos', []) if v.get('id') == identity), {})
    season, episode = video.get('season'), video.get('episode')
    code = 'S{:02d}E{:02d}'.format(season, episode) if type(season) is int and type(episode) is int else ''
    return line(' · '.join(v for v in (code, video.get('name') or video.get('title') or meta.get('name')) if v), 110)


def playback_meta(meta, identity):
    result = dict(meta)
    if meta.get('type') == 'series':
        video = next((v for v in meta.get('videos', []) if v.get('id') == identity), {})
        result.update(id=identity, name=video.get('name') or video.get('title') or meta.get('name'),
                      season=video.get('season'), episode=video.get('episode'),
                      tvshowtitle=meta.get('name'), _media_type='episode')
    return result
