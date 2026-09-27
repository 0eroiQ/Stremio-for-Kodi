"""System-runtime adapter to the checksum-pinned, unmodified SlyGuy Trailers component."""
from urllib.parse import urlencode
import json
from trailers import video_identity


def youtube_route(link):
    """Preserve the exact selected clip; never substitute a different trailer."""
    return 'plugin://slyguy.trailers/play/?' + urlencode({'video_id': video_identity(link)})


def play(link):
    import xbmc
    import xbmcaddon
    # Do not silently install another player or revert to the old resolver.
    xbmcaddon.Addon('slyguy.trailers')
    if not xbmc.getCondVisibility('System.AddonIsEnabled(slyguy.trailers)'):
        raise RuntimeError('SlyGuy Trailers is not enabled')
    # Leave the info modal before Kodi waits for the resolver. Otherwise Kodi
    # 21 macOS can hold its GUI lock while SlyGuy queries getCondVisibility.
    xbmc.executebuiltin('Dialog.Close(12003,true)', True)
    result = json.loads(xbmc.executeJSONRPC(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'Player.Open',
        'params': {'item': {'file': youtube_route(link)}}})))
    if 'error' in result:
        raise RuntimeError('Kodi rejected trailer playback')
