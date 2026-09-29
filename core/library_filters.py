"""Library filters and remote-friendly selection controls."""
from lib.ui_dialogs import dialog as themed_dialog
import json
import sys
import time
from urllib.parse import urlencode

SORTS = [('recent', 'Recently added'), ('az', 'Title A–Z'), ('za', 'Title Z–A')]


def select_rows(rows, kind='all', sort='recent', genre=''):
    rows = [r for r in rows if (kind == 'all' or r.get('type') == kind)
            and (not genre or genre in (r.get('genres') or []))]
    if sort in ('az', 'za'):
        return sorted(rows, key=lambda r: (r.get('name') or '').casefold(), reverse=sort == 'za')
    return sorted(rows, key=lambda r: str(r.get('_ctime') or ''), reverse=True)


def main():
    import xbmcgui
    home = xbmcgui.Window(10000)
    action = sys.argv[1] if len(sys.argv) > 1 else 'open'
    kind = home.getProperty('LibraryKind') or 'all'
    sort = home.getProperty('LibrarySort') or 'recent'
    genre = home.getProperty('LibraryGenre')
    if action == 'default':
        kind, sort, genre = 'all', 'recent', ''
    if action == 'kind':
        index = themed_dialog().select('My Library — type', ['All', 'Movies', 'Series'])
        if index < 0:
            return
        kind = ['all', 'movie', 'series'][index]
    elif action == 'sort':
        index = themed_dialog().select('My Library — sort', [v for k, v in SORTS])
        if index < 0:
            return
        sort = SORTS[index][0]
    elif action == 'genre':
        values = [''] + json.loads(home.getProperty('LibraryGenres') or '[]')
        index = themed_dialog().select('My Library — genre', ['All genres'] + values[1:])
        if index < 0:
            return
        genre = values[index]
    home.setProperty('LibraryKind', kind)
    home.setProperty('LibrarySort', sort)
    home.setProperty('LibraryGenre', genre)
    home.setProperty('LibraryKindLabel', {'all': 'All', 'movie': 'Movies', 'series': 'Series'}[kind])
    home.setProperty('LibrarySortLabel', dict(SORTS)[sort])
    home.setProperty('LibraryGenreLabel', genre or 'All genres')
    home.setProperty('StremioLibraryURL', 'plugin://script.stremioelec/?' + urlencode({
        'action': 'library', 'hub': '1', 'kind': kind, 'sort': sort, 'genre': genre,
        'refresh': '1' if action in ('open', 'default') else '0', 'revision': str(time.time_ns())}))


if __name__ == '__main__':
    main()
