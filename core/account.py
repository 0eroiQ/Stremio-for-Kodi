"""Stremio account integration. Never log tokens or configured addon URLs."""
import errno
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



SAVE_ATTEMPTS = 6


def _retryable_storage_error(error):
    return (isinstance(error, PermissionError)
            or getattr(error, 'errno', None) in (errno.EACCES, errno.EPERM, errno.EBUSY, errno.EAGAIN)
            or getattr(error, 'winerror', None) in (5, 32, 33))


class AccountStorageError(AccountError):
    """Fixed diagnostic codes; never retain a filesystem path or OS message."""
    def __init__(self, stage, error):
        self.stage = stage if stage in ('prepare_profile', 'create_temp', 'write_temp', 'replace_state') else 'unknown'
        code = getattr(error, 'errno', None)
        if code == errno.ENOSPC:
            self.reason = 'disk_full'
            self.user_message = 'Kodi could not save the login because storage is full. Free some space and try again.'
        elif code == errno.EROFS:
            self.reason = 'read_only'
            self.user_message = 'Kodi could not save the login because its profile storage is read-only.'
        elif _retryable_storage_error(error):
            self.reason = 'permission_or_locked'
            self.user_message = 'Kodi could not save the login. Check write access to the Kodi profile folder and whether another program is locking it, then try again.'
        else:
            self.reason = 'io_failure'
            self.user_message = 'Kodi could not save the login. Check the device storage and try again.'
        super().__init__(self.user_message)

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
            state = entry.get('state') or {}
            offset = state.get('timeOffset', 0)
            if not ((not entry.get('removed') or entry.get('temp'))
                    and isinstance(offset, (int, float)) and offset > 0):
                return False
            if entry.get('type') == 'movie':
                duration = state.get('duration', 0)
                # Stremio Core treats the credits threshold as completion. Keep
                # genuine partial rewatches (even if flaggedWatched is still set)
                # but never leave a 90%+ completed movie in Continue Watching.
                if isinstance(duration, (int, float)) and duration > 0:
                    return float(offset) < float(duration) * 0.90
            return True
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
        # Retry the entire atomic write, including mkdir/mkstemp: a lock may
        # occur before os.replace. Never delete the last known-good state or
        # move credentials to a less protected fallback directory.
        for attempt in range(SAVE_ATTEMPTS):
            fd = None
            name = None
            stage = 'prepare_profile'
            try:
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                stage = 'create_temp'
                fd, name = tempfile.mkstemp(dir=self.directory, prefix='.account-')
                chmod = getattr(os, 'fchmod', None)
                if callable(chmod):
                    try:
                        chmod(fd, 0o600)
                    except OSError:
                        pass  # mkstemp already restricts permissions on POSIX.
                stage = 'write_temp'
                stream = os.fdopen(fd, 'w', encoding='utf-8')
                fd = None  # stream now owns and closes the descriptor.
                with stream:
                    json.dump(data, stream)
                    stream.flush()
                    sync = getattr(os, 'fsync', None)
                    if callable(sync):
                        try:
                            sync(stream.fileno())
                        except OSError as error:
                            unsupported = (errno.EINVAL, errno.ENOSYS, getattr(errno, 'ENOTSUP', -1))
                            if error.errno not in unsupported:
                                raise  # Never commit after a real disk-write failure.
                stage = 'replace_state'
                os.replace(name, self.path)
                name = None
                return
            except OSError as error:
                if not _retryable_storage_error(error) or attempt + 1 == SAVE_ATTEMPTS:
                    raise AccountStorageError(stage, error) from None
            finally:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if name is not None:
                    try:
                        os.unlink(name)
                    except OSError:
                        pass
            time.sleep(0.05 * (attempt + 1))

    def forget(self):
        # Clear this device only; never alter the remote collection/session.
        self.save({})
