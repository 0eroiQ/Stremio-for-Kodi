"""Small local performance trace for startup/Home diagnostics.

Contains timings and counts only; never URLs, tokens, titles or account data.
"""
import time

PREFIX = "Stremio for Kodi PERF"


def now():
    return time.monotonic()


def ms(started):
    return max(0, int(round((time.monotonic() - started) * 1000.0)))


def log(stage, started=None, profile=None, **counts):
    elapsed = ms(started) if started is not None else None
    parts = [PREFIX, str(stage)]
    if elapsed is not None:
        parts.append("{}ms".format(elapsed))
    for key in sorted(counts):
        try:
            value = int(counts[key])
        except (TypeError, ValueError):
            continue
        parts.append("{}={}".format(key, value))
    if profile:
        try:
            from lib.perf_report import record
            record(profile, stage, elapsed, **counts)
        except Exception:
            pass
    try:
        import xbmc
        xbmc.log(" | ".join(parts), xbmc.LOGINFO)
    except ImportError:
        pass
    return elapsed
