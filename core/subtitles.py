"""Kodi-language filtered Stremio subtitles; download only the selected file."""
from lib.ui_dialogs import dialog as themed_dialog
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
from protocol import fetch, resource_url
from sources import supports, direct_url
from setup_profile import atomic_write, get_setting

ALIASES = {'hr': 'hrv', 'croatian': 'hrv', 'scr': 'hrv', 'hrv': 'hrv',
           'sr': 'srp', 'serbian': 'srp', 'scc': 'srp', 'srp': 'srp',
           'bs': 'bos', 'bosnian': 'bos', 'bos': 'bos',
           'en': 'eng', 'english': 'eng', 'eng': 'eng'}


def language(value):
    value = str(value or '').strip().lower()
    if value in ALIASES:
        return ALIASES[value]
    try:
        import xbmc
        return xbmc.convertLanguage(value, xbmc.ISO_639_2).lower() or value
    except (ImportError, AttributeError):
        return value


def preferences():
    allowed = get_setting('subtitles.languages', [])
    if isinstance(allowed, str):
        allowed = allowed.split(',')
    return ([language(value) for value in allowed],
            language(get_setting('locale.subtitlelanguage', '')),
            bool(get_setting('subtitles.downloadfirst', False)))


def collect_subtitles(providers, kind, identity, allowed, preferred, inline=None, filename='', fetcher=fetch):
    def query(provider):
        try:
            extras = {'filename': filename} if filename else None
            response = fetcher(resource_url(provider['transportUrl'], 'subtitles', kind, identity, extras))
            return response.get('subtitles', [])
        except Exception:
            return []
    selected, seen = [], set()
    for provider in providers:
        url = provider.get('transportUrl')
        if url and url not in seen and supports(provider.get('manifest', {}), kind, identity, 'subtitles'):
            selected.append(provider)
            seen.add(url)
    entries = list(inline) if isinstance(inline, list) else []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(query, selected):
            if isinstance(result, list):
                entries.extend(result)
    results, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or not direct_url(entry):
            continue
        lang = language(entry.get('lang'))
        if (allowed and lang not in allowed) or (lang, entry['url']) in seen:
            continue
        seen.add((lang, entry['url']))
        results.append({'lang': lang, 'url': entry['url'],
                        'label': '{} · {}'.format(lang, ' '.join(str(entry.get('label') or entry.get('id') or 'Subtitle').split()))})
    # Allowed languages are a set, NOT user-ranked fallback priorities.
    return sorted(results, key=lambda entry: (entry['lang'] != preferred, entry['lang']))


def ai_source_candidates(providers, kind, identity, inline=None, filename='', fetcher=fetch):
    """All Stremio subtitle results for AUTO AI fallback; target/source ranking is separate."""
    entries = collect_subtitles(
        providers, kind, identity, [], '', inline, filename, fetcher=fetcher
    )
    try:
        from ai_subtitles import local_settings, rank_external_entries
        settings = local_settings()
        return rank_external_entries(entries, settings['target'])
    except Exception:
        return entries


def download(entry, directory):
    with urlopen(Request(entry['url'], headers={'User-Agent': 'StremioELEC/0.5'}), timeout=10) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('Subtitle too large')
    # Reject archives, HTML/error documents and unsupported binary formats.
    probe = data.decode('utf-8-sig', errors='replace').lstrip()
    if probe.startswith('WEBVTT'):
        extension = 'vtt'
    elif '[Script Info]' in probe[:2048]:
        extension = 'ass'
    elif '-->' in probe and not probe.lower().startswith(('<!doctype', '<html')):
        extension = 'srt'
    else:
        raise ValueError('Unsupported subtitle file')
    digest = hashlib.sha256(data).hexdigest()
    lang = entry['lang'] if entry['lang'].isalpha() else 'und'
    target = Path(directory) / '{}.{}.{}'.format(digest, lang, extension)
    atomic_write(target, data)
    try:
        from ai_subtitles import maybe_translate
        return maybe_translate(target, Path(directory).parent, lang)
    except Exception:
        return str(target)


def remember_selection(profile, kind, identity, stream):
    from account import Store
    Store(Path(profile) / 'playback').save({'created': time.time(), 'kind': kind, 'id': identity,
        'url_hash': hashlib.sha256(stream['url'].encode()).hexdigest(),
        'subtitles': stream.get('subtitles', []), 'filename': stream.get('filename', '')})


def prepare_selected(profile, kind, identity, stream, providers, listitem):
    remember_selection(profile, kind, identity, stream)
    allowed, preferred, auto = preferences()
    if not auto or not allowed or preferred in ('none', 'off'):
        return
    results = collect_subtitles(providers, kind, identity, allowed, preferred,
                                stream.get('subtitles'), stream.get('filename', ''))
    # No synchronization claim: if no file hash is available, provider order wins
    # within a language. Try at most two files so a bad source cannot stall forever.
    for entry in results[:2]:
        try:
            listitem.setSubtitles([download(entry, Path(profile) / 'subtitles')])
            return
        except Exception:
            continue


def manual_selection(profile, providers):
    import xbmc
    import xbmcgui
    from account import Store
    player = xbmc.Player()
    context = Store(Path(profile) / 'playback').load()
    def matches():
        try:
            return (player.isPlayingVideo() and time.time() - context.get('created', 0) < 86400
                    and hashlib.sha256(player.getPlayingFile().encode()).hexdigest() == context.get('url_hash'))
        except Exception:
            return False
    if not matches():
        themed_dialog().ok('Stremio subtitles', 'Start a video through Stremio for Kodi first.')
        return
    allowed, preferred, _ = preferences()
    entries = collect_subtitles(providers, context['kind'], context['id'], allowed, preferred,
                                context.get('subtitles'), context.get('filename', ''))
    if not entries:
        themed_dialog().ok('Stremio subtitles', 'No subtitles found in the languages selected in Kodi Settings.')
        return
    index = themed_dialog().select('Stremio subtitles — Kodi languages', [entry['label'] for entry in entries])
    if index < 0 or index >= len(entries) or not matches():
        return
    path = download(entries[index], Path(profile) / 'subtitles')
    if matches():
        player.setSubtitles(path)
        player.showSubtitles(True)
