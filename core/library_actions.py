"""Explicit account library changes; preserve existing playback state."""
from copy import deepcopy
from datetime import datetime, timezone
from account import request, pull_library, AccountError


def member(entries, identity, kind):
    return any(e.get('_id') == identity and e.get('type') == kind and
               not e.get('removed') and not e.get('temp') for e in entries)


def change(token, identity, kind, name, poster, add):
    if not token or kind not in ('movie', 'series') or not identity:
        raise AccountError('Missing account or exact title identity.')
    entries = pull_library(token)
    old = next((e for e in entries if e.get('_id') == identity and e.get('type') == kind), None)
    if member(entries, identity, kind) == add:
        return entries
    now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    item = deepcopy(old) if old else {
        '_id': identity, 'type': kind, 'name': name, 'poster': poster or None,
        'posterShape': 'poster', '_ctime': now, 'behaviorHints': {},
        'state': {'timeWatched': 0, 'timeOffset': 0, 'overallTimeWatched': 0,
                  'timesWatched': 0, 'flaggedWatched': 0, 'duration': 0}}
    item.update(removed=not add, temp=False, _mtime=now)
    response = request('https://api.strem.io/api/datastorePut', {
        'authKey': token, 'collection': 'libraryItem', 'changes': [item]})
    if 'error' in response:
        raise AccountError('Stremio rejected the library change.')
    verified = pull_library(token)
    if member(verified, identity, kind) != add:
        raise AccountError('Library change could not be confirmed. Reopen info to check before retrying.')
    return verified
