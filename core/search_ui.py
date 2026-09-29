"""Stremio for Kodi search launcher; no autocomplete/helper addon required."""
from lib.ui_dialogs import dialog as themed_dialog
from urllib.parse import urlencode
import xbmc
import xbmcgui


def run():
    query = themed_dialog().input('Search Stremio', type=xbmcgui.INPUT_ALPHANUM).strip()
    if not query:
        return
    path = 'plugin://script.stremioelec/?' + urlencode({
        'action': 'search_results', 'query': query})
    xbmc.executebuiltin('ActivateWindow(Videos,' + path + ',return)')


if __name__ == '__main__':
    run()
