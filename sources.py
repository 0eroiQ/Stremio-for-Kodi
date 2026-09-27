"""Read-only source aggregation; no account token is sent to providers."""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from protocol import fetch, resource_url


def supports(manifest, kind, identity, resource_name='stream'):
    for resource in manifest.get('resources', []):
        spec = manifest if resource == resource_name else resource
        if not isinstance(spec, dict):
            continue
        if resource != resource_name and spec.get('name') != resource_name:
            continue
        types = spec.get('types', manifest.get('types', []))
        prefixes = spec.get('idPrefixes')
        if kind in types and (prefixes is None or any(identity.startswith(p) for p in prefixes)):
            return True
    return False


def direct_url(stream):
    url = stream.get('url', '')
    if not isinstance(url, str) or '|' in url or any(ord(c) < 32 for c in url):
        return False
    parsed = urlsplit(url)
    hints = stream.get('behaviorHints') or {}
    return (parsed.scheme in ('http', 'https') and bool(parsed.netloc)
            and not parsed.username and not parsed.password
            and isinstance(hints, dict) and not hints.get('proxyHeaders')
            and not stream.get('externalUrl') and not stream.get('infoHash'))


def collect(providers, kind, identity, fetcher=fetch):
    selected, seen = [], set()
    for provider in providers:
        url = provider.get('transportUrl')
        if url and url not in seen and supports(provider.get('manifest', {}), kind, identity):
            seen.add(url)
            selected.append(provider)

    def query(provider):
        try:
            result = fetcher(resource_url(provider['transportUrl'], 'stream', kind, identity))
            streams = result.get('streams', [])
            if not isinstance(streams, list):
                raise ValueError('Invalid streams')
            good, skipped = [], 0
            for stream in streams:
                if not isinstance(stream, dict) or not direct_url(stream):
                    skipped += 1
                    continue
                name = provider['manifest'].get('name') or 'Addon'
                detail = stream.get('title') or stream.get('name') or 'Stream'
                hints = stream.get('behaviorHints') or {}
                good.append({'url': stream['url'],
                             'label': '{} · {}'.format(name, detail),
                             'provider': name,
                             'detail': detail,
                             'subtitles': stream.get('subtitles', []),
                             'filename': hints.get('filename', '')})
            return good, skipped, 0
        except Exception:
            # Never expose configured URLs or provider exception messages.
            return [], 0, 1

    output, skipped, failed = [], 0, 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for entries, ignored, errors in pool.map(query, selected):
            output.extend(entries)
            skipped += ignored
            failed += errors
    return output, skipped, failed
