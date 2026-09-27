"""Presentation helpers for the Stremio for Kodi TV stream picker."""
import os
import re


QUALITY_RE = re.compile(r'(?i)(2160p|1080p|720p|480p|360p|4k)')
SIZE_RE = re.compile(r'(?i)(\d+(?:\.\d+)?\s*(?:TB|GB|MB))')
SEED_RE = re.compile(r'👤\s*(\d+)')
SOURCE_RE = re.compile(r'⚙️\s*([^\r\n]+)')
FLAG_RE = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')


def _clean(value):
    return re.sub(r'[\u200b-\u200f\u2060\ufeff]', '', str(value or '')).strip()


def _contains(text, *needles):
    low = text.lower()
    return any(needle.lower() in low for needle in needles)


def stream_card(stream):
    """Return normalized, display-only properties for one stream."""
    label = _clean(stream.get('label'))
    provider = _clean(stream.get('provider'))
    detail = _clean(stream.get('detail'))

    if not provider and ' · ' in label:
        provider = label.split(' · ', 1)[0].strip()
    if not detail and ' · ' in label:
        detail = label.split(' · ', 1)[1].strip()
    provider = provider or 'Stream'

    filename = _clean(stream.get('filename'))
    if filename:
        filename = os.path.basename(filename.replace('\\', '/'))
    if not filename:
        candidates = [line.strip() for line in detail.splitlines()
                      if re.search(r'(?i)\.(mkv|mp4|avi|m2ts|ts)\b', line)]
        filename = os.path.basename(candidates[-1]) if candidates else detail.splitlines()[0] if detail else 'Stream'

    corpus = '\n'.join(v for v in (detail, filename, label) if v)
    quality_match = QUALITY_RE.search(corpus)
    quality = quality_match.group(1).upper().replace('2160P', '4K') if quality_match else 'AUTO'
    quality = quality.replace('1080P', '1080p').replace('720P', '720p').replace('480P', '480p').replace('360P', '360p')

    size_match = SIZE_RE.search(corpus)
    size = size_match.group(1) if size_match else ''
    seed_match = SEED_RE.search(corpus)
    seeders = seed_match.group(1) if seed_match else ''
    source_match = SOURCE_RE.search(corpus)
    source = source_match.group(1).strip() if source_match else ''

    flags = []
    for line in corpus.splitlines():
        found = FLAG_RE.findall(line)
        if found:
            text = ' / '.join(found)
            if text not in flags:
                flags.append(text)
    languages = ' • '.join(flags)

    tech = []
    def add(value):
        if value and value not in tech:
            tech.append(value)

    if _contains(corpus, 'remux'):
        add('REMUX')
    if _contains(corpus, 'blu-ray', 'bluray', 'bdrip'):
        add('BluRay')
    elif _contains(corpus, 'web-dl', 'webdl'):
        add('WEB-DL')
    elif _contains(corpus, 'webrip', 'web-rip'):
        add('WEBRip')

    if _contains(corpus, 'dolby vision', ' dv ', '.dv.', 'dovi'):
        add('Dolby Vision')
    if _contains(corpus, 'hdr10'):
        add('HDR10')
    elif _contains(corpus, 'hdr'):
        add('HDR')

    if _contains(corpus, 'av1'):
        add('AV1')
    elif _contains(corpus, 'hevc', 'h265', 'h.265', 'x265'):
        add('H.265')
    elif _contains(corpus, 'avc', 'h264', 'h.264', 'x264'):
        add('H.264')

    if _contains(corpus, '10bit', '10-bit'):
        add('10bit')

    audio_patterns = (
        (r'(?i)dts[- .]?hd(?:[ .]?ma)?(?:[ .]?(\d\.\d))?', 'DTS-HD MA'),
        (r'(?i)truehd(?:[ .]?(\d\.\d))?', 'TrueHD'),
        (r'(?i)atmos', 'Atmos'),
        (r'(?i)dts[- .]?x', 'DTS-X'),
        (r'(?i)aac\s*([257]\.\d)', 'AAC'),
        (r'(?i)ac3\s*([257]\.\d)', 'AC3'),
    )
    for pattern, name in audio_patterns:
        match = re.search(pattern, corpus)
        if match:
            channels = match.group(1) if match.lastindex else ''
            add(name + ((' ' + channels) if channels else ''))

    meta = []
    if size:
        meta.append(size)
    if source:
        meta.append(source)
    if seeders:
        meta.append(seeders + ' seeders')
    if languages:
        meta.append(languages)

    return {
        'provider': provider,
        'quality': quality,
        'headline': '{} · {}'.format(provider, quality),
        'filename': filename,
        'tech': ' • '.join(tech),
        'meta': ' • '.join(meta),
        'size': size,
        'source': source,
        'seeders': seeders,
        'languages': languages,
    }
