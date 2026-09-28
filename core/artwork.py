"""Cached library artwork enrichment. Never changes account or playback state."""
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from account import Store
from protocol import fetch, resource_url
from sources import supports

FIELDS = ('background', 'landscape', 'logo', 'poster', 'description', 'genres')


def enrich(rows, providers, directory, fetcher=None):
    fetcher = fetcher or (lambda url: fetch(url, timeout=4))

    def one(saved):
        result = dict(saved, id=saved['_id'])
        kind, identity = saved['type'], saved['_id']
        candidates = [p for p in providers if supports(p.get('manifest', {}), kind, identity, 'meta')][:2]
        key = hashlib.sha256((kind + ':' + identity + repr([p.get('transportUrl') for p in candidates])).encode()).hexdigest()
        cache = Store(directory / key)
        try:
            cached = cache.load()
        except Exception:
            cached = {}
        details = cached.get('details', {})
        if cached.get('expires', 0) < time.time() or 'genres' not in details:
            details = dict(details)
            for provider in candidates:
                try:
                    meta = fetcher(resource_url(provider['transportUrl'], 'meta', kind, identity)).get('meta')
                    if not isinstance(meta, dict) or meta.get('id') != identity:
                        continue
                    for field in FIELDS:
                        value = meta.get(field)
                        if field == 'genres':
                            details[field] = [g for g in (value or []) if isinstance(g, str)] if isinstance(value, list) else []
                            continue
                        if isinstance(value, str) and value:
                            details.setdefault(field, value)
                    if details.get('background'):
                        break
                except Exception:
                    # Provider URLs may contain credentials; never log failures.
                    continue
            try:
                cache.save({'details': details, 'expires': time.time() + (86400 if details.get('background') else 900)})
            except OSError:
                pass
        for field in FIELDS:
            if not result.get(field) and details.get(field):
                result[field] = details[field]
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, rows))
