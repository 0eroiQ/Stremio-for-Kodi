"""Private, offline configure QR and explicit pull-only Stremio addon sync."""
import copy
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


class ConfigureError(Exception):
    """Safe user-facing failure; never includes a configured URL or token."""


def configure_target(entry):
    from addons_core import configure_url
    value = entry.get('transportUrl') if isinstance(entry, dict) else None
    if not isinstance(value, str) or not 1 <= len(value) <= 2400:
        raise ConfigureError('The configuration link is missing or too long for a QR code.')
    if any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ConfigureError('The configuration link is invalid.')
    try:
        target = configure_url(value)
        parsed = urlsplit(target)
        if not parsed.hostname or parsed.port == 0:
            raise ValueError()
        return target
    except Exception:
        raise ConfigureError('This addon has no valid HTTPS configuration link.') from None


def public_site(entry):
    """Only the origin is displayable; paths often contain private configuration."""
    parsed = urlsplit(configure_target(entry))
    return parsed.scheme + '://' + parsed.netloc


def write_qr(entry, directory):
    from lib.vendor import segno
    target = configure_target(entry)
    directory = Path(directory)
    fd, path = None, None
    try:
        qr = segno.make_qr(target, error='m', boost_error=False)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix='configure-', suffix='.png', dir=str(directory))
        path = Path(name)
        with os.fdopen(fd, 'wb') as output:
            fd = None
            qr.save(output, kind='png', scale=8, border=4, dark='#000', light='#fff')
        return path
    except Exception:
        if fd is not None:
            os.close(fd)
        if path is not None:
            remove_qr(path)
        raise ConfigureError('QR could not be created. Select Refresh QR to try again.') from None


def remove_qr(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def find_updated_entry(entries, previous):
    exact = next((e for e in entries if e.get('id') == previous.get('id')), None)
    if exact is not None:
        return exact
    identity = (previous.get('manifest') or {}).get('id')
    matches = [e for e in entries if identity and (e.get('manifest') or {}).get('id') == identity]
    try:
        origin = urlsplit(previous.get('transportUrl', '')).netloc
        same_origin = [e for e in matches if urlsplit(e.get('transportUrl', '')).netloc == origin]
        if len(same_origin) == 1:
            return same_origin[0]
    except ValueError:
        pass
    return matches[0] if len(matches) == 1 else None


def sync_addons(store, entry, fetcher=None, cancelled=lambda: False, commit=None):
    """Fetch account addons, then merge into fresh local state; never push account."""
    from account import pull_addons
    fetcher = fetcher or pull_addons
    try:
        token = store.load().get('token')
        if not isinstance(token, str) or not token:
            raise ConfigureError('Connect your Stremio account in Settings before syncing.')
        if cancelled():
            raise ConfigureError('Sync cancelled. Existing addons were kept.')
        remote, skipped = fetcher(token)
        if skipped or not isinstance(remote, list):
            raise ConfigureError('Some account addons could not be read. Existing addons were kept.')
        remote = copy.deepcopy(remote)
        from addons_core import normalize_manifest_url
        for row in remote:
            normalize_manifest_url(row['transportUrl'])
            if not row.get('id') or not isinstance(row.get('manifest'), dict):
                raise ValueError()
            row['account'] = True
        def finish():
            if cancelled():
                raise ConfigureError('Sync cancelled. Existing addons were kept.')
            latest = store.load()
            if latest.get('token') != token:
                raise ConfigureError('The Stremio account changed during sync. Please retry.')
            updated = copy.deepcopy(latest)
            # Keep local-only installations; deduplicate an exact account URL.
            remote_urls = {r['transportUrl'] for r in remote}
            local = [r for r in latest.get('addons', []) if r.get('account') is not True
                     and r.get('transportUrl') not in remote_urls]
            updated['addons'] = local + remote
            disabled = set(latest.get('disabledAddons', []))
            for old in latest.get('addons', []):
                if old.get('id') in disabled:
                    replacement = find_updated_entry(updated['addons'], old)
                    if replacement:
                        disabled.add(replacement['id'])
            if disabled != set(latest.get('disabledAddons', [])):
                updated['disabledAddons'] = sorted(disabled)
            selected = find_updated_entry(updated['addons'], entry)
            changed = updated != latest
            if changed:
                store.save(updated)
            return {'changed': changed, 'entry': selected,
                    'count': len(updated['addons']), 'account_count': len(remote)}
        return commit(finish) if commit else finish()
    except ConfigureError:
        raise
    except Exception:
        raise ConfigureError('Sync failed. Your existing addons were kept. Check the connection and try again.') from None
