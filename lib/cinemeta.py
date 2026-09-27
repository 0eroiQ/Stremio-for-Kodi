"""Official Cinemeta catalogs. No Kodi video plugin."""
import json
import urllib.request

BASE = 'https://v3-cinemeta.strem.io'


def catalog(kind, catalog_id, limit=16):
    url = '{}/catalog/{}/{}.json'.format(BASE, kind, catalog_id)
    request = urllib.request.Request(url, headers={'User-Agent': 'Stremio for Kodi/0.1'})
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode('utf-8'))
    rows = []
    for meta in payload.get('metas') or []:
        if not meta.get('id'):
            continue
        rows.append({
            'id': meta['id'],
            'type': meta.get('type') or kind,
            'name': meta.get('name') or '',
            'poster': meta.get('poster') or '',
            'background': meta.get('background') or meta.get('poster') or '',
            'description': meta.get('description') or '',
        })
        if len(rows) >= limit:
            break
    return rows
