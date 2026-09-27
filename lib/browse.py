"""Discover choices and library views derived from account data."""
def discover_catalogs(addons):
    result = []
    for addon in addons:
        if not addon.get('account'):
            continue
        manifest = addon.get('manifest') or {}
        for catalog in manifest.get('catalogs', []):
            if not isinstance(catalog, dict) or not catalog.get('id') or not catalog.get('type'):
                continue
            extras = [e for e in catalog.get('extra', []) if isinstance(e, dict) and e.get('name')]
            # Search-only and special context catalogs do not belong in Discover.
            required = set(catalog.get('extraRequired') or []) | {e['name'] for e in extras if e.get('isRequired')}
            options = {e['name']: e for e in extras if e.get('options')}
            if any(name not in options for name in required):
                continue
            defaults = {name: str(options[name]['options'][0]) for name in required}
            result.append({'label': str(catalog.get('name') or catalog['id']),
                           'kind': catalog['type'], 'id': catalog['id'],
                           'addon': manifest.get('name') or 'Addon',
                           'url': addon['transportUrl'], 'extras': extras, 'defaults': defaults})
    return result


def library_sections(entries, kind='all', order='recent'):
    items = [dict(e, id=e.get('_id') or e.get('id')) for e in entries
             if isinstance(e, dict) and (e.get('_id') or e.get('id'))
             and not e.get('removed') and not e.get('temp')
             and (kind == 'all' or e.get('type') == kind)]
    if order == 'name':
        items.sort(key=lambda e: str(e.get('name') or '').casefold())
    elif order == 'watched':
        items.sort(key=lambda e: str((e.get('state') or {}).get('lastWatched') or ''), reverse=True)
    else:
        items.sort(key=lambda e: str(e.get('_ctime') or e.get('ctime') or e.get('_mtime') or ''), reverse=True)
    types = list(dict.fromkeys(['movie', 'series'] + [e.get('type') or 'other' for e in items]))
    labels = {'movie': 'Movies', 'series': 'Series'}
    return [{'label': labels.get(t, t.title()), 'items': [e for e in items if (e.get('type') or 'other') == t]}
            for t in types if any((e.get('type') or 'other') == t for e in items)]
