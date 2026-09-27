"""Info-dialog library status and user-triggered write, exact IMDb IDs only."""
import re
import sys
from pathlib import Path
import xbmc
import xbmcaddon
from addon_state import get_addon
import xbmcgui
import xbmcvfs
from account import Store, pull_library
from library_actions import member, change

home = xbmcgui.Window(10000)
store = Store(Path(xbmcvfs.translatePath(get_addon().getAddonInfo('profile'))))


def current():
    kind = xbmc.getInfoLabel('ListItem.DBTYPE') or xbmc.getInfoLabel('ListItem.Property(DBTYPE)')
    kind = {'tvshow': 'series', 'movie': 'movie'}.get(kind)
    identity = xbmc.getInfoLabel('ListItem.UniqueID(imdb)') or xbmc.getInfoLabel('ListItem.IMDBNumber')
    return identity, kind


def main():
    identity, kind = current()
    key = str(kind) + ':' + identity
    if not kind or not re.fullmatch(r'tt\d+', identity):
        home.clearProperty('StremioLibraryReady')
        home.setProperty('StremioLibraryLabel', 'Library unavailable')
        return
    name, poster = xbmc.getInfoLabel('ListItem.Title'), xbmc.getInfoLabel('ListItem.Art(poster)')
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    desired = home.getProperty('StremioLibraryAdd') == 'true'
    if action == 'toggle' and (home.getProperty('StremioLibraryKey') != key or home.getProperty('StremioLibraryReady') != 'true'):
        return
    home.clearProperty('StremioLibraryReady')
    home.setProperty('StremioLibraryLabel', 'Checking Stremio library…')
    state = store.load()
    token = state.get('token')
    if not token:
        home.setProperty('StremioLibraryLabel', 'Connect to Stremio')
        return
    try:
        entries = change(token, identity, kind, name, poster, desired) if action == 'toggle' else pull_library(token)
        latest = store.load()
        if latest.get('token') != token:
            return
        latest['library'] = entries
        store.save(latest)
        if current() != (identity, kind):
            return
        present = member(entries, identity, kind)
        home.setProperty('StremioLibraryKey', key)
        home.setProperty('StremioLibraryAdd', 'false' if present else 'true')
        home.setProperty('StremioLibraryLabel', 'Remove from library' if present else 'Add to library')
        home.setProperty('StremioLibraryReady', 'true')
        if action == 'toggle':
            xbmcgui.Dialog().notification('Stremio library', 'Added to library' if desired else 'Removed from library')
    except Exception:
        home.setProperty('StremioLibraryLabel', 'Library unavailable')
        if action == 'toggle':
            xbmcgui.Dialog().ok('Stremio library', 'The change could not be confirmed. Reopen this info screen to check your account before retrying.')


if __name__ == '__main__':
    main()
