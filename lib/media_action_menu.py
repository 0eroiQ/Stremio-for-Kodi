"""Addon-owned vertical long-press action menu for media cards."""
import xbmcgui

BACK = (10, 92, 216, 247)
LIST = 600


class MediaActionMenu(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.options = list(kwargs.pop('options'))
        self.result = None
        super().__init__(*args, **kwargs)

    def onInit(self):
        from addon_state import get_addon
        path = get_addon().getAddonInfo('path')
        listing = self.getControl(LIST)
        listing.reset()
        items = []
        for option in self.options:
            li = xbmcgui.ListItem(label=str(option.get('label') or ''))
            icon = str(option.get('icon') or 'info')
            li.setProperty('icon', path + '/resources/skins/Main/media/action-menu/' + icon + '.png')
            items.append(li)
        listing.addItems(items)
        height = max(1, len(items)) * 70
        panel_height = height + 28
        top = max(190, 540 - panel_height // 2)
        self.getControl(100).setPosition(690, top)
        self.getControl(100).setHeight(panel_height)
        listing.setPosition(704, top + 14)
        listing.setHeight(height)
        self.setFocusId(LIST)

    def onClick(self, cid):
        if cid != LIST:
            return
        pos = self.getControl(LIST).getSelectedPosition()
        if 0 <= pos < len(self.options):
            self.result = self.options[pos].get('action')
        self.close()

    def onAction(self, action):
        if action.getId() in BACK:
            self.close()


def choose(path, options):
    from lib.theme import window as themed_window
    window = themed_window(MediaActionMenu, 'script-stremio-media-actions.xml',
                           path, 'Main', '1080i', options=options)
    window.doModal()
    result = window.result
    del window
    return result
