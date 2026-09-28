"""Embedded Nimbus selector shared by account browsing filters."""
import xbmcgui


from lib.theme import window as themed_window


class Selector(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.left = kwargs.pop('left', 50)
        self.top = kwargs.pop('top', 600)
        self.heading = kwargs.pop('heading')
        self.options = kwargs.pop('options')
        self.result = -1
        super().__init__(*args, **kwargs)

    def onInit(self):
        self.setProperty('heading', self.heading)
        for cid, x, y in ((601,0,600),(602,20,613),(600,10,675)):
            self.getControl(cid).setPosition(self.left+x, y + self.top - 600)
        self.getControl(601).setHeight(1045 - self.top)
        self.getControl(600).setHeight(950 - self.top)
        listing = self.getControl(600)
        listing.reset()
        listing.addItems([xbmcgui.ListItem(str(value)) for value in self.options])
        self.setFocusId(600)

    def onAction(self, action):
        if action.getId() in (10, 92, 216, 247):
            self.close()

    def onClick(self, control):
        if control == 600:
            self.result = self.getControl(600).getSelectedPosition()
            self.close()


class Dialog:
    def __init__(self, path, left=50, top=600):
        self.top = top
        self.path = path
        self.left = left

    def select(self, heading, options):
        if not options:
            return -1
        window = themed_window(Selector, 'script-stremio-select.xml', self.path, 'Main', '1080i',
                          heading=heading, options=options, left=self.left, top=self.top)
        window.doModal()
        result = window.result
        del window
        return result
