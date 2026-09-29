"""Prepare sparse account entries before displaying their hero."""
from concurrent.futures import ThreadPoolExecutor


def prepare(rows, catalogs, fetch_details=None):
    known = {(r.get('type'), r.get('id')): r
             for catalog in catalogs for r in catalog.get('items', [])
             if r.get('background') and r.get('description')}

    def enrich(row):
        result = dict(row)
        full = known.get((row.get('type'), row.get('id')))
        if full is None:
            if fetch_details is None:
                return result
            try:
                full = fetch_details(row)
            except Exception:
                return result
        # Keep playback state and identity from the account entry.
        for field in ('name', 'background', 'logo', 'description', 'year', 'releaseInfo',
                      'imdbRating', 'runtime', 'genres', 'released', 'certification', 'mpaa'):
            if full.get(field):
                result[field] = full[field]
        return result

    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(enrich, rows))
