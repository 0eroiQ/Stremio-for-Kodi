"""Shared palettes for addon-owned windows; never modifies the Kodi skin."""
from pathlib import Path
import xml.etree.ElementTree as ET

NAMES = ('Purple', 'Black', 'Blue', 'Green', 'Gold')
# background, sidebar, surface, button, selected card, focus, accent
PALETTES = (
 ('FF100E1C','FF14111E','FF242333','FF302B41','FF42365C','FFC4ACFF','FFB5A4E8'),
 ('FF080808','FF101010','FF202020','FF303030','FF464646','FFE5E5E5','FFCCCCCC'),
 ('FF0B1421','FF101C2C','FF1C2C41','FF263C56','FF31577A','FFA4D8FF','FF85C7F2'),
 ('FF0B1814','FF10241C','FF1C352A','FF294839','FF35644C','FFA7EAC2','FF83CEA1'),
 ('FF19140B','FF241D10','FF352B1C','FF493B27','FF665233','FFF4D59B','FFDDB875'),
)
KEYS = ('background','sidebar','surface','button','selected','focus','accent')


def index(addon):
    try:
        value = int(addon.getSetting('ui_theme') or 0)
        return value if 0 <= value < len(PALETTES) else 0
    except (TypeError, ValueError):
        return 0


def apply(tree, selected=0, poster_color=None):
    palette = dict(zip(KEYS, PALETTES[selected if 0 <= selected < len(PALETTES) else 0]))
    roles = {
        'background': ('0F1017','0B0B12','171322','090711','050505'),
        'sidebar': ('121212',),
        'surface': ('242333','242530','20222F','252333','17151F','191526','2A2736'),
        'button': ('302B41','30313B','353238','403650'),
        'selected': ('42365C','7355DE'),
        'focus': ('C4ACFF','F0F0F2','4564FF'),
        'accent': ('B5A4E8','9B7CFF','9B7BFF'),
    }
    mapping = {color:palette[role][2:] for role,colors in roles.items() for color in colors}
    color_tags = {'textcolor','focusedcolor','disabledcolor','selectedcolor','shadowcolor'}
    for element in tree.iter():
        if element.tag in color_tags:
            old = element.text or ''
            if len(old)==8 and old[2:] in mapping:
                element.text=old[:2]+mapping[old[2:]]
        for key in ('colordiffuse','start','end'):
            value=element.get(key,'')
            if len(value)==8 and value[2:] in mapping:
                element.set(key,value[:2]+mapping[value[2:]])
        if element.tag in ('texture','bordertexture') and any(part in (element.text or '') for part in ('poster-glow','poster-border')):
            element.set('colordiffuse',poster_color or palette['focus'])
        if element.tag=='texturefocus':
            element.set('colordiffuse',palette['focus'])
    # Sidebar focus marker and labels use the same accent as the rest of the app.
    menu=tree.find('.//control[@id="9000"]/focusedlayout')
    if menu is not None:
        for color in menu.iter('textcolor'):
            if color.text=='FFE5E5E5':color.text=palette['focus']
        for texture in menu.iter('texture'):
            texture.set('colordiffuse',palette['focus'])


def window(cls, filename, source, *args, **kwargs):
    """Compile a themed copy in the addon profile before WindowXML allocates it."""
    import xbmcvfs
    from addon_state import get_addon
    addon=get_addon()
    selected=index(addon)
    original=Path(source)/'resources/skins/Main/1080i'/filename
    if not original.exists():
        original=Path(addon.getAddonInfo('path'))/'resources/skins/Main/1080i'/filename
    tree=ET.parse(original)
    from lib.appearance import options
    apply(tree,selected,options(addon)['color'])
    base=Path(xbmcvfs.translatePath(addon.getAddonInfo('profile')))/'theme-layout'/str(selected)
    dest=base/'resources/skins/Main/1080i'
    dest.mkdir(parents=True,exist_ok=True)
    name='themed-'+filename
    tree.write(dest/name,encoding='utf-8',xml_declaration=True)
    return cls(name,str(base),*args,**kwargs)
