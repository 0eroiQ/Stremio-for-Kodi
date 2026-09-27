"""Skin RunScript entry: existing TMDb clips played by SlyGuy Trailers."""
import sys
import time
import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcgui
from trailers import discover, video_identity
from slyguy_trailers import play
from account import Store
from addons_core import active_addons
from metadata_bridge import details as metadata_details, trailer_rows as metadata_trailers


def main():
    window = xbmcgui.Window(10000)
    try:
        busy_since = float(window.getProperty('StremioTrailerBusy') or 0)
    except ValueError:
        busy_since = 0
    if 0 <= time.time() - busy_since < 60:
        return
    window.setProperty('StremioTrailerBusy', str(time.time()))
    progress = None
    try:
        label = xbmc.getInfoLabel
        selected_clip = 'selected' in sys.argv[1:]
        if selected_clip:
            link = ''
            for candidate in (
                    label('Container(354).ListItem.Property(StremioTrailerURL)'),
                    label('Container(354).ListItem.FolderPath'),
                    label('Container(354).ListItem.FileNameAndPath')):
                try:
                    video_identity(candidate)
                    link = candidate
                    break
                except (TypeError, ValueError):
                    continue
        else:
            link = label('ListItem.Trailer')
        if link:
            title = label('Container(354).ListItem.Label') if selected_clip else label('ListItem.Title')
            if xbmc.Monitor().abortRequested():
                return
            play(link)
            return
        if selected_clip:
            raise ValueError('Missing selected trailer')
        import xbmcvfs
        addon = get_addon()
        label = xbmc.getInfoLabel
        raw_kind = label('ListItem.Property(StremioType)') or label('ListItem.DBType') or label('ListItem.Property(DBTYPE)')
        kind = 'series' if raw_kind in ('tv', 'tvshow', 'season', 'episode', 'series') else 'movie'
        identity = (label('ListItem.Property(StremioID)') or
                    label('ListItem.IMDBNumber') or label('ListItem.Property(imdb_id)'))
        title = label('ListItem.Title')
        store = Store(xbmcvfs.translatePath(addon.getAddonInfo('profile')))
        meta = metadata_details(kind, identity, title, active_addons(store.load()))
        stremio_rows = metadata_trailers(meta)
        if stremio_rows:
            selected = xbmcgui.Dialog().select(
                'Stremio trailers', [r.get('name', 'Trailer') for r in stremio_rows])
            if selected < 0 or xbmc.Monitor().abortRequested():
                return
            play('https://www.youtube.com/watch?v=' + stremio_rows[selected]['id'])
            return

        key = addon.getSetting('tmdb_api_key').strip()
        if not key:
            xbmcgui.Dialog().ok('Stremio for Kodi trailers', 'No trailer was provided by the installed Stremio metadata addons.')
            return
        tmdb = label('ListItem.Property(tmdb_id)') or label('ListItem.UniqueID(tmdb)')
        imdb = label('ListItem.IMDBNumber') or label('ListItem.Property(imdb_id)')
        tmdb_kind = 'tv' if kind == 'series' else 'movie'
        progress = xbmcgui.DialogProgress()
        progress.create('Stremio for Kodi trailers', 'Finding official trailers on TMDb…')
        rows = discover(key, tmdb_kind, tmdb, imdb, 'en-US')
        if progress.iscanceled() or xbmc.Monitor().abortRequested():
            return
        progress.close()
        progress = None
        if not rows:
            xbmcgui.Dialog().ok('Stremio for Kodi trailers', 'No trailer found for this title.')
            return
        selected = xbmcgui.Dialog().select('TMDb trailers', [r.get('name', 'Trailer') for r in rows])
        if selected < 0:
            return
        if xbmc.Monitor().abortRequested():
            return
        play('https://www.youtube.com/watch?v=' + rows[selected]['key'])
    except Exception as error:
        xbmc.log('Stremio for Kodi trailer failed: ' + type(error).__name__, xbmc.LOGWARNING)
        if progress is not None:
            progress.close()
            progress = None
        xbmcgui.Dialog().ok('Stremio for Kodi trailers', 'Unable to open trailer. The built-in trailer playback component is unavailable; install a verified Stremio for Kodi system update.')
    finally:
        window.clearProperty('StremioTrailerBusy')
        if progress is not None:
            progress.close()


if __name__ == '__main__':
    main()
