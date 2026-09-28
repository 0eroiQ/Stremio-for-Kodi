"""Stremio addon collection management for the Stremio for Kodi SYSTEM runtime."""
import hashlib
from urllib.parse import urlsplit, urlunsplit

from account import AccountError, request
from protocol import fetch

COMMUNITY_CATALOG = 'https://v3-cinemeta.strem.io/addon_catalog/all/community.json'
COMMUNITY_LIMIT = 2000


def normalize_manifest_url(value):
    value = (value or '').strip()
    if value.startswith('stremio://'):
        value = 'https://' + value[len('stremio://'):]
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.endswith('/manifest.json')):
        raise ValueError('Use an HTTPS Stremio manifest URL ending in /manifest.json')
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ''))


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError('Invalid addon manifest')
    for key in ('id', 'name', 'version', 'resources', 'types'):
        if key not in manifest:
            raise ValueError('Addon manifest is missing ' + key)
    if not isinstance(manifest['id'], str) or not manifest['id'].strip():
        raise ValueError('Invalid addon id')
    if not isinstance(manifest['name'], str) or not manifest['name'].strip():
        raise ValueError('Invalid addon name')
    if not isinstance(manifest['resources'], list) or not isinstance(manifest['types'], list):
        raise ValueError('Invalid addon capabilities')
    return manifest


def descriptor_id(url):
    return hashlib.sha256(url.encode()).hexdigest()


def make_descriptor(url, manifest, flags=None):
    result = {'id': descriptor_id(url), 'transportUrl': url, 'manifest': validate_manifest(manifest)}
    if isinstance(flags, dict):
        result['flags'] = flags
    return result


def install_descriptor_local(state, url, manifest):
    url = normalize_manifest_url(url)
    manifest = validate_manifest(manifest)
    descriptor = make_descriptor(url, manifest)
    descriptor['account'] = False
    addons = list(state.get('addons', []))
    # A configured URL for the same addon replaces the old configuration.
    same_id = manifest.get('id')
    addons = [item for item in addons if item.get('manifest', {}).get('id') != same_id]
    addons.append(descriptor)
    state['addons'] = addons
    disabled = set(state.get('disabledAddons', []))
    disabled.discard(descriptor['id'])
    state['disabledAddons'] = sorted(disabled)
    return descriptor


def install_local(state, url, fetcher=fetch):
    url = normalize_manifest_url(url)
    return install_descriptor_local(state, url, fetcher(url))


def _resource_names(manifest):
    result = set()
    for item in manifest.get('resources', []):
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, dict) and isinstance(item.get('name'), str):
            result.add(item['name'])
    return result


def community_catalog(fetcher=fetch):
    payload = fetcher(COMMUNITY_CATALOG)
    rows = payload.get('addons') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > COMMUNITY_LIMIT:
        raise ValueError('Invalid community addon catalog')
    valid, seen = [], set()
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise ValueError()
            url = normalize_manifest_url(row.get('transportUrl', ''))
            manifest = validate_manifest(row.get('manifest'))
            key = (manifest.get('id'), url)
            if key in seen:
                continue
            seen.add(key)
            valid.append({'transportUrl': url, 'manifest': manifest})
        except (TypeError, ValueError):
            continue
    return sorted(valid, key=lambda item: item['manifest'].get('name', '').casefold())


def filter_community(rows, category='all', query=''):
    query = (query or '').strip().casefold()
    result = []
    for row in rows:
        manifest = row.get('manifest', {})
        resources = _resource_names(manifest)
        types = {str(v).casefold() for v in manifest.get('types', []) if isinstance(v, str)}
        if category == 'movies' and not types.intersection({'movie', 'series', 'anime'}):
            continue
        if category == 'subtitles' and 'subtitles' not in resources:
            continue
        if category == 'catalogs' and 'catalog' not in resources:
            continue
        if category == 'live' and not types.intersection({'tv', 'channel'}):
            continue
        if category == 'streams' and 'stream' not in resources:
            continue
        haystack = ' '.join([
            str(manifest.get('name', '')),
            str(manifest.get('description', '')),
            ' '.join(sorted(resources)),
            ' '.join(sorted(types)),
        ]).casefold()
        if query and query not in haystack:
            continue
        result.append(row)
    return result


def remove_local(state, identity):
    state['addons'] = [item for item in state.get('addons', []) if item.get('id') != identity]
    state['disabledAddons'] = sorted(set(state.get('disabledAddons', [])) - {identity})


def set_enabled(state, identity, enabled):
    if not any(item.get('id') == identity for item in state.get('addons', [])):
        raise ValueError('Unknown addon')
    disabled = set(state.get('disabledAddons', []))
    if enabled:
        disabled.discard(identity)
    else:
        disabled.add(identity)
    state['disabledAddons'] = sorted(disabled)


def active_addons(state):
    disabled = set(state.get('disabledAddons', []))
    return [item for item in state.get('addons', []) if item.get('id') not in disabled]



def account_addons(state):
    return [item for item in state.get('addons', []) if item.get('account') is True]


def merge_account(state, remote):
    """Replace account-owned entries while preserving local-only installs."""
    local = [item for item in state.get('addons', []) if item.get('account') is not True]
    remote_ids = {item.get('manifest', {}).get('id') for item in remote}
    local = [item for item in local if item.get('manifest', {}).get('id') not in remote_ids]
    return local + remote


def mark_account(state, identity, value=True):
    for item in state.get('addons', []):
        if item.get('id') == identity:
            item['account'] = bool(value)
            return
    raise ValueError('Unknown addon')


def account_descriptors(addons):
    rows = []
    for item in addons:
        url = normalize_manifest_url(item.get('transportUrl', ''))
        manifest = validate_manifest(item.get('manifest'))
        row = {'transportUrl': url, 'manifest': manifest}
        # Stremio descriptors always carry flags. Preserve account values;
        # new/local addons default to ordinary non-protected descriptors.
        flags = item.get('flags') if isinstance(item.get('flags'), dict) else {}
        row['flags'] = {
            'official': bool(flags.get('official', False)),
            'protected': bool(flags.get('protected', False)),
        }
        rows.append(row)
    return rows


def push_account(token, addons):
    if not token:
        raise AccountError('Connect your Stremio account first.')
    payload = {'type': 'AddonCollectionSet',
               'authKey': token,
               'addons': account_descriptors(addons)}
    data = request('https://api.strem.io/api/addonCollectionSet', payload)
    if data.get('error'):
        raise AccountError('Stremio rejected the addon collection update.')
    if 'result' not in data:
        raise AccountError('Stremio did not confirm the addon collection update.')
    return data['result']


def configure_url(url):
    parsed = urlsplit(normalize_manifest_url(url))
    path = parsed.path[:-len('/manifest.json')] + '/configure'
    return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def configuration_state(manifest):
    hints = manifest.get('behaviorHints') if isinstance(manifest.get('behaviorHints'), dict) else {}
    return {
        'configurable': bool(hints.get('configurable')),
        'required': bool(hints.get('configurationRequired')),
        'schema': manifest.get('config') if isinstance(manifest.get('config'), list) else [],
    }
