"""Read Stremio's anchored per-video watched bitmap without changing account state."""
import base64
import zlib


def watched_ids(videos, saved):
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1
    rows = sorted((v for v in videos or [] if isinstance(v, dict) and v.get('id')),
                  key=lambda v: (number(v.get('season')), number(v.get('episode', v.get('number'))), v.get('released') or ''))
    ids = [v['id'] for v in rows]
    value = ((saved or {}).get('state') or {}).get('watched')
    if not isinstance(value, str) or len(value) > 100000:
        return set()
    try:
        anchor, length, packed = value.rsplit(':', 2)
        length = int(length)
        if not 0 < length <= 1000000 or anchor not in ids:
            return set()
        inflater = zlib.decompressobj()
        bits = inflater.decompress(base64.b64decode(packed, validate=True), 125001)
        if not inflater.eof or len(bits) > 125000:
            return set()
        offset = length - 1 - ids.index(anchor)
        return {identity for i, identity in enumerate(ids)
                if 0 <= i + offset < (length if offset else len(bits) * 8)
                and (i + offset) // 8 < len(bits)
                and bits[(i + offset) // 8] & (1 << ((i + offset) % 8))}
    except (ValueError, TypeError, zlib.error):
        return set()
