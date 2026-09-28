"""Stremio account integration. Never log tokens or configured addon URLs."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

from protocol import base_url


class AccountError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise AccountError('Account endpoint redirected; request stopped.')


def request(url, payload=None):
    # Only these two official origins may receive account requests.
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc not in ('api.strem.io', 'link.stremio.com'):
        raise AccountError('Invalid account endpoint.')
    body = json.dumps(payload).encode() if payload is not None else None
    try:
        with build_opener(NoRedirect()).open(Request(url, data=body, headers={
                'Content-Type': 'application/json', 'User-Agent': 'StremioELEC/0.2'}), timeout=12) as response:
            data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError()
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except HTTPError as error:
        # A non-2xx response is an upstream/API failure, not necessarily a device
        # connectivity problem. Keep the message useful without exposing response data.
        raise AccountError('Stremio service returned HTTP {}. Please retry shortly.'.format(error.code)) from None
    except URLError:
        raise AccountError('Could not reach the Stremio service. Check your connection and retry.') from None
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        raise AccountError('Stremio returned an unexpected response. Please retry shortly.') from None
    except AccountError:
        raise
    except Exception:
        raise AccountError('Stremio request failed. Please retry shortly.') from None


def create_link():
    code, link, _ = create_link_details()
    return code, link


def create_link_details():
    response = request('https://link.stremio.com/api/create?type=Create')
    data = response.get('result') if isinstance(response.get('result'), dict) else response
    if not isinstance(data, dict) or not isinstance(data.get('code'), str):
        raise AccountError('Unable to create a sign-in link.')
    link = data.get('link', '')
    parsed = urlsplit(link)
    if parsed.scheme != 'https' or parsed.netloc not in ('stremio.com', 'www.stremio.com', 'link.stremio.com'):
        raise AccountError('Unexpected sign-in link.')
    qr = data.get('qrcode', '')
    parsed_qr = urlsplit(qr)
    if parsed_qr.scheme != 'https' or parsed_qr.netloc != 'link.stremio.com' or parsed_qr.path != '/qr':
        qr = ''  # Link remains usable if QR format changes.
    return data['code'], link, qr


def read_link(code):
    data = request('https://link.stremio.com/api/read?' + urlencode({'type': 'Read', 'code': code}))
    candidates = []
    if isinstance(data.get('result'), dict):
        candidates.append(data['result'])
    candidates.append(data)
    for result in candidates:
        for key in ('authKey', 'auth_key'):
            token = result.get(key)
            if isinstance(token, str) and token.strip():
                return token.strip()
    return None


def pull_addons(token):
    data = request('https://api.strem.io/api/addonCollectionGet', {
        'type': 'AddonCollectionGet', 'authKey': token, 'update': False})
    result = data.get('result')
    if not isinstance(result, dict) or not isinstance(result.get('addons'), list):
        raise AccountError('Unable to read account addons. Reconnect your account if needed.')
    addons, seen, skipped = [], set(), 0
    for descriptor in result['addons']:
        try:
            url = descriptor['transportUrl']
            base_url(url)
            if urlsplit(url).scheme != 'https':
                raise ValueError()
            manifest = descriptor['manifest']
            if not isinstance(manifest, dict):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        item = {'id': hashlib.sha256(url.encode()).hexdigest(),
                'transportUrl': url, 'manifest': manifest, 'account': True}
        if isinstance(descriptor.get('flags'), dict):
            item['flags'] = descriptor['flags']
        addons.append(item)
    return addons, skipped


def pull_library(token):
    result = request('https://api.strem.io/api/datastoreGet', {
        'authKey': token, 'collection': 'libraryItem', 'ids': [], 'all': True}).get('result')
    if not isinstance(result, list):
        raise AccountError('Unable to read the Stremio library. Existing local data was kept.')
    return [entry for entry in result if isinstance(entry, dict)
            and isinstance(entry.get('_id'), str) and isinstance(entry.get('state'), dict)]


def library_rows(entries, continuing=False):
    def eligible(entry):
        if entry.get('type') not in ('movie', 'series'):
            return False
        if continuing:
            offset = entry['state'].get('timeOffset', 0)
            return (not entry.get('removed') or entry.get('temp')) and isinstance(offset, (int, float)) and offset > 0
        return not entry.get('removed') and not entry.get('temp')
    return sorted((entry for entry in entries if eligible(entry)),
                  key=lambda entry: str(entry['state'].get('lastWatched') or entry.get('_mtime') or ''), reverse=True)


class Store:
    """Owner-only local file, not encrypted. Exclude Kodi addon_data from backups."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'account.json'

    def load(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except Exception:
            raise AccountError('Local account data cannot be read. Disconnect and reconnect.') from None

    def save(self, data):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=self.directory, prefix='.account-')
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            # On Windows, antivirus/indexing or another short-lived file handle can
            # temporarily deny os.replace(). Retry the atomic replacement briefly
            # instead of turning a successful Stremio authentication into a login failure.
            last_error = None
            for attempt in range(6):
                try:
                    os.replace(name, self.path)
                    name = None
                    break
                except PermissionError as error:
                    last_error = error
                    if attempt == 5:
                        raise AccountError(
                            'Could not save Stremio account data on this device. '
                            'Check Kodi profile-folder permissions and retry.'
                        ) from None
                    time.sleep(0.05 * (attempt + 1))
            if last_error is not None and name is not None:
                raise AccountError('Could not save Stremio account data on this device.') from None
        finally:
            if name and os.path.exists(name):
                try:
                    os.unlink(name)
                except OSError:
                    pass

    def forget(self):
        # Clear this device only; never alter the remote collection/session.
        self.save({})
