"""TMDb trailer discovery and embedded playback resolver. No Kodi video addon."""
import re
from urllib.parse import urlencode, urlsplit, parse_qs
from protocol import fetch


def video_identity(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if parsed.scheme == 'plugin' and parsed.netloc == 'plugin.video.youtube':
        value = (query.get('video_id') or query.get('videoid') or [''])[0]
    elif parsed.scheme == 'https' and parsed.hostname in ('www.youtube.com', 'youtube.com'):
        value = (query.get('v') or [''])[0]
    elif parsed.scheme == 'https' and parsed.hostname == 'youtu.be':
        value = parsed.path.strip('/')
    else:
        value = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        raise ValueError('Unsupported trailer link')
    return value


def discover(key, kind, tmdb='', imdb='', language='en-US', fetcher=fetch):
    if kind not in ('movie', 'tv'):
        raise ValueError('Unsupported media type')
    def request(path, **params):
        return fetcher('https://api.themoviedb.org/3/' + path + '?' +
                       urlencode(dict(api_key=key, **params)))
    if not re.fullmatch(r'[1-9][0-9]*', tmdb):
        if not re.fullmatch(r'tt[0-9]+', imdb):
            return []
        matches = request('find/' + imdb, external_source='imdb_id').get(kind + '_results', [])
        if len(matches) != 1:
            return []
        tmdb = str(matches[0]['id'])
    rows = request(kind + '/' + tmdb + '/videos', language=language).get('results', [])
    if not rows and language != 'en-US':
        rows = request(kind + '/' + tmdb + '/videos', language='en-US').get('results', [])
    rows = [r for r in rows if isinstance(r, dict) and r.get('site') == 'YouTube'
            and r.get('type') in ('Trailer', 'Teaser')
            and re.fullmatch(r'[A-Za-z0-9_-]{11}', r.get('key', ''))]
    return sorted(rows, key=lambda r: (not r.get('official', False), r['type'] != 'Trailer'))


class QuietLog:
    # Provider URLs / expiring playback tokens must not enter Kodi logs.
    def debug(self, *_): pass
    def warning(self, *_): pass
    def error(self, *_): pass


def resolve(video_id, factory=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('Invalid trailer identity')
    if factory is None:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent / 'vendor'))
        from yt_dlp import YoutubeDL
        factory = YoutubeDL
    # A single muxed stream works in Kodi without merging files or FFmpeg.
    options = dict(format='best[height<=720][vcodec!=none][acodec!=none]',
                   quiet=True, no_warnings=True, logger=QuietLog(),
                   noplaylist=True, skip_download=True, cachedir=False,
                   socket_timeout=12, retries=1, extractor_retries=1)
    with factory(options) as extractor:
        result = extractor.extract_info('https://www.youtube.com/watch?v=' + video_id, download=False)
    url = result.get('url', '')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.netloc or '|' in url or any(ord(c) < 32 for c in url):
        raise ValueError('No supported trailer stream')
    if result.get('vcodec') == 'none' or result.get('acodec') == 'none':
        raise ValueError('Trailer requires separate audio/video')
    return url
