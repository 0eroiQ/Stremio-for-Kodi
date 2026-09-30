"""Account Home catalogs in server order, without UI or Kodi dependencies."""
from concurrent.futures import ThreadPoolExecutor

HOME_ITEM_LIMIT = 16
MAX_WORKERS = 2


def descriptors(addons):
    rows = []
    for addon in addons:
        manifest = addon.get('manifest') or {}
        if manifest.get('behaviorHints', {}).get('configurationRequired'):
            continue
        for catalog in manifest.get('catalogs', []):
            if not isinstance(catalog, dict) or not catalog.get('id') or not catalog.get('type'):
                continue
            extra = catalog.get('extra', [])
            if any(e.get('isRequired') for e in extra if isinstance(e, dict)) or catalog.get('extraRequired'):
                continue
            rows.append({'label': str(catalog.get('name') or catalog['id']),
                         'kind': catalog['type'], 'catalog_id': catalog['id'],
                         'url': addon['transportUrl'], 'provider': addon.get('id')})
    return rows


def load_rows(addons, fetch, resource_url, item_limit=HOME_ITEM_LIMIT, max_workers=MAX_WORKERS):
    def load(spec):
        try:
            payload = fetch(resource_url(spec['url'], 'catalog', spec['kind'], spec['catalog_id']))
            items = [dict(item, type=item.get('type') or spec['kind'])
                     for item in payload.get('metas', [])
                     if isinstance(item, dict) and item.get('id')]
            return dict(spec, items=items[:max(1, int(item_limit))], failed=False)
        except Exception:
            return dict(spec, items=[], failed=True)
    specs = descriptors(addons)
    if not specs:
        return []
    if len(specs) == 1:
        return [load(specs[0])]

    # Keep startup lightweight on constrained Kodi/Linux devices. If the
    # runtime cannot create another worker thread, fall back to sequential
    # loading instead of aborting the whole Program entry.
    workers = min(max(1, int(max_workers)), len(specs))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # map preserves account order even when requests finish out of order.
            return list(pool.map(load, specs))
    except RuntimeError:
        return [load(spec) for spec in specs]
