from lib.ui_dialogs import dialog as themed_dialog
import xbmc
import xbmcgui
from lib.cinemeta import catalog
from lib.settings import apply_kodi_locale, load_setup, save_setup

LANGUAGES = (
    ('English (US)', 'resource.language.en_us', 'eng'),
    ('English (UK)', 'resource.language.en_gb', 'eng'),
    ('Bosanski', 'resource.language.bs_ba', 'bos'),
    ('Hrvatski', 'resource.language.hr_hr', 'hrv'),
    ('Deutsch', 'resource.language.de_de', 'ger'),
)

REGIONS = (
    ('Australia', 'Australia'),
    ('United States', 'USA'),
    ('United Kingdom', 'UK'),
    ('Bosnia and Herzegovina', 'Bosnia and Herzegovina'),
    ('Croatia', 'Croatia'),
    ('Germany', 'Germany'),
)

# Welcome controls
BTN_LANGUAGE = 101
BTN_LOCATION = 102
BTN_CONTINUE = 103

# Home side rail
BTN_SEARCH = 201
BTN_HOME = 202
BTN_DISCOVER = 203
BTN_LIBRARY = 204
BTN_ADDONS = 205
BTN_SETTINGS = 206
LIST_MOVIES = 400
LIST_SERIES = 401
HERO = 310
HERO_TITLE = 311
HERO_PLOT = 312



def _listitem(row):
    item = xbmcgui.ListItem(row['name'])
    art = row.get('poster') or ''
    item.setArt({'thumb': art, 'poster': art, 'icon': art, 'fanart': row.get('background') or art})
    item.setProperty('stremio.id', row['id'])
    item.setProperty('stremio.type', row['type'])
    item.setInfo('video', {'title': row['name'], 'plot': row.get('description', '')})
    return item


class HomeWindow(xbmcgui.WindowXML):
    def onInit(self):
        setup = load_setup()
        region = setup.get('region') or REGIONS[0]
        self.getControl(300).setLabel('Popular Movies')
        self.getControl(301).setLabel('Popular Series')
        self.getControl(302).setLabel(region[0])
        self.movies = []
        self.series = []
        try:
            self.movies = catalog('movie', 'top')
            self.series = catalog('series', 'top')
        except Exception as error:
            xbmc.log('Stremio for Kodi Cinemeta: {}'.format(error), xbmc.LOGERROR)
            themed_dialog().notification('Stremio for Kodi', 'Cinemeta catalog unavailable')
        self._fill(LIST_MOVIES, self.movies)
        self._fill(LIST_SERIES, self.series)
        if self.movies:
            self._hero(self.movies[0])

    def _fill(self, control_id, rows):
        listing = self.getControl(control_id)
        listing.reset()
        for row in rows:
            listing.addItem(_listitem(row))

    def _hero(self, row):
        fanart = row.get('background') or row.get('poster') or ''
        if fanart:
            self.getControl(HERO).setImage(fanart)
        self.getControl(HERO_TITLE).setLabel(row.get('name') or '')
        plot = row.get('description') or ''
        self.getControl(HERO_PLOT).setLabel(plot[:220])

    def onClick(self, control_id):
        labels = {
            BTN_SEARCH: 'Search',
            BTN_HOME: 'Home',
            BTN_DISCOVER: 'Discover',
            BTN_LIBRARY: 'Library',
            BTN_ADDONS: 'Addons',
            BTN_SETTINGS: 'Settings',
        }
        if control_id in labels:
            themed_dialog().ok('Stremio for Kodi', '{} — sljedeći korak.'.format(labels[control_id]))
            return
        if control_id == LIST_MOVIES:
            self._open(self.movies, LIST_MOVIES)
        elif control_id == LIST_SERIES:
            self._open(self.series, LIST_SERIES)

    def _open(self, rows, control_id):
        listing = self.getControl(control_id)
        pos = listing.getSelectedPosition()
        if pos < 0 or pos >= len(rows):
            return
        row = rows[pos]
        self._hero(row)
        themed_dialog().ok(row['name'], row.get('description') or row['id'])

    def onAction(self, action):
        if action.getId() in (10, 92):
            self.close()
