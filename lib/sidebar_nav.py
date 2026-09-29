"""Single source of truth for sidebar order, icons and existing actions."""
MEDIA = 'special://home/addons/script.stremioelec/resources/skins/Main/media/navigation-local/'
ENTRIES = (
    ('Search', 201, 'search'),
    ('Home', 202, 'home'),
    ('Discover', 203, 'discover'),
    ('Library', 204, 'library'),
    ('Addons', 205, 'addons'),
    ('Settings', 206, 'settings'),
)


def menu_items(gui):
    rows = []
    for label, action, icon in ENTRIES:
        item = gui.ListItem(label)
        item.setArt({'icon': MEDIA + icon + '.png'})
        item.setProperty('sidebar_action', str(action))
        rows.append(item)
    return rows


def menu_action(index):
    return ENTRIES[index][1] if type(index) is int and 0 <= index < len(ENTRIES) else 202


def home_index():
    return next(i for i, entry in enumerate(ENTRIES) if entry[1] == 202)
