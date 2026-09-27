"""Self-contained IMDb trailer discovery and direct Kodi playback URLs.

The IMDb route in the user-supplied SlyGuy Trailers 0.2.0 package was
used as a protocol reference. No SlyGuy framework, credentials or code
are bundled; all requests and playback are implemented here.
"""
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ENDPOINT = 'https://api.graphql.imdb.com/'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.imdb.com/',
           'Origin': 'https://www.imdb.com', 'Content-Type': 'application/json'}


def imdb_id(meta):
    for value in (meta.get('imdb_id'), meta.get('imdbId'), meta.get('id')):
        value = str(value or '').split(':')[0]
        if re.fullmatch(r'tt\d+', value):
            return value
    return ''


def playback_url(identity, season=-1):
    if not re.fullmatch(r'tt\d+', str(identity)):
        return ''
    return 'plugin://script.stremioelec/?' + urlencode(
        {'action': 'play_trailer', 'id': identity, 'season': season})


def query(document, variables):
    request = Request(ENDPOINT, data=json.dumps(
        {'query': document, 'variables': variables}).encode('utf-8'), headers=HEADERS)
    with urlopen(request, timeout=12) as response:
        result = json.load(response)
    if result.get('errors') and not result.get('data'):
        raise ValueError('Trailer service unavailable')
    return result.get('data') or {}


def choose_trailer(nodes, season=-1):
    candidates = [n for n in nodes if re.fullmatch(r'vi\d+', str(n.get('id', '')))]
    def score(node):
        title = ((node.get('name') or {}).get('value') or '').lower()
        match = re.search(r'(?:season|series)\s*(\d+)', title)
        number = int(match.group(1)) if match else None
        return (number == season if season >= 0 else number is None,
                'official' in title, 'trailer' in title, 'teaser' not in title)
    return max(candidates, key=score) if candidates else None


def choose_stream(streams, quality='0'):
    # MP4 includes both video and audio; native Kodi also handles the HLS fallback.
    heights = {'DEF_1080p': 1080, 'DEF_720p': 720, 'DEF_480p': 480, 'DEF_SD': 272}
    limit = {'0': 1080, '1': 720, '2': 480}.get(quality, 1080)
    valid = [s for s in streams if urlsplit(s.get('url', '')).scheme == 'https']
    mp4 = [s for s in valid if s.get('videoMimeType') == 'MP4']
    under = [s for s in mp4 if 0 < heights.get(s.get('videoDefinition'), 0) <= limit]
    if under:
        return max(under, key=lambda s: heights[s['videoDefinition']])
    if mp4:
        return min(mp4, key=lambda s: heights.get(s.get('videoDefinition'), 9999))
    return next((s for s in valid if s.get('videoMimeType') == 'M3U8'), None)


def resolve(identity, season=-1, quality='0', request=query):
    if not re.fullmatch(r'tt\d+', str(identity)):
        raise ValueError('No IMDb identity for this title')
    data = request('''query($id: ID!){title(id:$id){
      videoStrip(first:100,filter:{types:[TRAILER]},sort:{by:DATE,order:DESC}){
        edges{node{id name{value}}}}
      latestTrailer{id name{value}}
    }}''', {'id': identity})
    title = data.get('title') or {}
    nodes = [e.get('node') or {} for e in (title.get('videoStrip') or {}).get('edges', [])]
    trailer = choose_trailer(nodes, season) or title.get('latestTrailer')
    if not trailer:
        return None
    data = request('''query($id: ID!){video(id:$id){playbackURLs{
      videoDefinition videoMimeType url}}}''', {'id': trailer['id']})
    stream = choose_stream((data.get('video') or {}).get('playbackURLs') or [], quality)
    if not stream:
        return None
    return {'url': stream['url'], 'title': (trailer.get('name') or {}).get('value') or 'Trailer',
            'mime': 'video/mp4' if stream['videoMimeType'] == 'MP4' else 'application/vnd.apple.mpegurl'}
