"""Strict TMDb Helper to Stremio identity mapping; no title guessing."""
import re


def stream_identity(params):
    imdb = params.get('imdb', '')
    if not re.fullmatch(r'tt[0-9]+', imdb):
        raise ValueError('A valid IMDb identity is required.')
    kind = params.get('kind')
    if kind == 'movie':
        return kind, imdb
    if kind != 'series':
        raise ValueError('Unsupported media type.')
    season, episode = params.get('season', ''), params.get('episode', '')
    if not re.fullmatch(r'[0-9]+', season) or not re.fullmatch(r'[0-9]+', episode):
        raise ValueError('An exact season and episode are required.')
    if int(episode) < 1:
        raise ValueError('Invalid episode.')
    return kind, '{}:{}:{}'.format(imdb, int(season), int(episode))


def resolve(params, providers, collector, dialog, plugin, gui, handle, prepare=None):
    """Resolve inside the Helper playback request, not a directory navigation."""
    try:
        kind, identity = stream_identity(params)
    except ValueError:
        dialog.ok('Stremio', 'Missing IMDb identity or episode information. No title guessing was attempted.')
        plugin.setResolvedUrl(handle, False, gui.ListItem())
        return
    if not providers:
        dialog.ok('Stremio', 'Connect your Stremio account and import addons first.')
        plugin.setResolvedUrl(handle, False, gui.ListItem())
        return
    streams, skipped, failed = collector(providers, kind, identity)
    if not streams:
        dialog.ok('Stremio', 'No supported direct HTTP streams. {} unsupported; {} addons failed. '
                  'Torrents, DRM and custom proxy headers are not supported yet.'.format(skipped, failed))
        plugin.setResolvedUrl(handle, False, gui.ListItem())
        return
    # Provider labels often contain multiple lines; Kodi's simple select rows do not.
    selected = dialog.select('Stremio sources', [' '.join(entry['label'].split()) for entry in streams])
    if selected < 0 or selected >= len(streams):
        plugin.setResolvedUrl(handle, False, gui.ListItem())
        return
    item = gui.ListItem(path=streams[selected]['url'])
    if prepare:
        try:
            prepare(kind, identity, streams[selected], item)
        except Exception:
            dialog.notification('Stremio subtitles', 'Subtitles unavailable; video will still start.')
    plugin.setResolvedUrl(handle, True, item)
