"""Explicit, privacy-safe Home performance report.

Only allowlisted PERF stage durations/counts plus broad environment versions are
submitted. kodi.log, URLs, account data, titles, keys and device IDs are never read.
"""
import hashlib
import json
from pathlib import Path

from account import Store
from lib.error_report import _environment, send_report

STAGES = (
    'home.cached', 'home.cached.total', 'ui.home.initial',
    'home.refresh.account', 'home.refresh.catalogs', 'home.refresh.library',
    'ui.home.repopulate', 'ui.home.background.total', 'home.refresh.total',
)
MAX_MS = 30 * 60 * 1000
MAX_COUNT = 10000


def _store(profile):
    return Store(Path(profile) / 'performance')


def record(profile, stage, elapsed=None, **counts):
    if stage not in STAGES:
        return
    row = {}
    if elapsed is not None:
        row['ms'] = max(0, min(MAX_MS, int(elapsed)))
    for key in ('rows', 'items'):
        if key in counts:
            row[key] = max(0, min(MAX_COUNT, int(counts[key])))
    state = _store(profile).load()
    timings = state.get('timings') if isinstance(state.get('timings'), dict) else {}
    timings[stage] = row
    _store(profile).save({'timings': timings})


def load(profile):
    state = _store(profile).load()
    timings = state.get('timings')
    if not isinstance(timings, dict):
        return {}
    return {stage: dict(timings[stage]) for stage in STAGES
            if stage in timings and isinstance(timings[stage], dict)}


def build_payload(profile, environment=None):
    timings = load(profile)
    if not timings:
        return None
    env = dict(environment or _environment())
    report = {
        'reportVersion': 1,
        'context': 'Home performance',
        'errorType': 'PerformanceReport',
        'addonVersion': str(env.get('addonVersion') or 'unknown')[:40],
        'kodiVersion': str(env.get('kodiVersion') or 'unknown')[:80],
        'platform': str(env.get('platform') or 'unknown')[:40],
        'pythonVersion': str(env.get('pythonVersion') or 'unknown')[:40],
        'stack': [],
        'performance': timings,
    }
    identity = dict(report)
    identity['performance'] = {k: sorted(v) for k, v in timings.items()}
    report['fingerprint'] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()[:12]
    return report


def send(profile):
    payload = build_payload(profile)
    return bool(payload and send_report(payload))
