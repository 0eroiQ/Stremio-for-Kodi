"""Small HTTP adapter; independent of Kodi and without account credentials."""
import json
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


def base_url(manifest):
    parsed = urlsplit(manifest)
    if (parsed.scheme not in ('https', 'http') or not parsed.netloc
            or not parsed.path.endswith('/manifest.json')
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError('Use an HTTP(S) URL ending in /manifest.json')
    return manifest[:-len('/manifest.json')]


def resource_url(manifest, resource, kind, identity, extras=None):
    if resource not in ('catalog', 'meta', 'stream', 'subtitles'):
        raise ValueError('Unsupported resource')
    url = base_url(manifest) + '/' + '/'.join(
        quote(str(part), safe='') for part in (resource, kind, identity))
    if extras:
        url += '/' + urlencode(extras, quote_via=quote)
    return url + '.json'


def fetch(url, timeout=15):
    request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'StremioELEC/0.1'})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('Addon response is too large')
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError('Expected an object from addon')
    return result


def catalogs(manifest):
    """Only catalogs usable without mandatory search/genre filters."""
    return [c for c in manifest.get('catalogs', [])
            if c.get('id') and c.get('type')
            and not any(e.get('isRequired') for e in c.get('extra', []))]
