"""Installed Stremio addons inside the embedded Nimbus shell."""
import xml.etree.ElementTree as ET

MEDIA = 'special://home/addons/script.stremioelec/resources/skins/Main/media/'
PAGE = 'String.IsEqual(Window.Property(page),Addons)'




def node(parent, kind, cid=None, **tags):
    control = ET.SubElement(parent, 'control', type=kind)
    if cid is not None:
        control.set('id', str(cid))
    for key, value in tags.items():
        ET.SubElement(control, key).text = str(value)
    return control


def label(parent, text, x, y, width, height=40, font='font27', color='FFE5E5E7', kind='label'):
    return node(parent, kind, left=x, top=y, width=width, height=height,
                font=font, textcolor=color, label=text)


def build(tree):
    controls = tree.find('controls')
    for control in list(controls)[1:]:
        if control.find('.//control[@id="9000"]') is not None:
            for animation in control.findall('animation'):
                condition = animation.get('condition')
                if condition:
                    animation.set('condition', '[' + condition + '] | ' + PAGE)
            continue
        visible = control.find('visible')
        if visible is None:
            visible = ET.SubElement(control, 'visible')
            visible.text = '!' + PAGE
        else:
            visible.text = '[' + (visible.text or 'true') + '] + !' + PAGE
    group = node(controls, 'group', visible=PAGE)
    label(group, 'Addons', 540, 65, 1100, 70, 'font52_title')
    label(group, '$INFO[Window.Property(addons_summary)]', 540, 145, 1280, 45, 'font23', 'FFADACB5')
    add = node(group, 'button', 9304, left=1515, top=910, width=300, height=65,
               font='font27', label='+ Add addon', textcolor='FFE5E5E7', focusedcolor='FF15121E',
               onleft=9303, onright=9304, onup='SetFocus($INFO[Window.Property(addons_list_focus)])', ondown='SetFocus($INFO[Window.Property(addons_list_focus)])')
    ET.SubElement(add,'texturefocus',border='14',colordiffuse='FFC4ACFF').text=MEDIA+'masks/flixicon-filled.png'
    ET.SubElement(add,'texturenofocus',border='14',colordiffuse='FF302B41').text=MEDIA+'masks/flixicon-filled.png'
    listing = node(group, 'list', 9300, left=540, top=215, width=1300, height=660,
                   onleft=9000, onright=9301, onup=9304, ondown=9304,
                   scrolltime=180, orientation='vertical')
    for layout, color in [('itemlayout', 'FF242333'), ('focusedlayout', 'FF42365C')]:
        box = ET.SubElement(listing, layout, width='1300', height='220')
        bg = node(box, 'image', left=0, top=0, width=1280, height=202)
        ET.SubElement(bg, 'texture', border='16', colordiffuse=color).text = MEDIA+'masks/flixicon-filled.png'
        icon = node(box, 'image', left=24, top=42, width=112, height=112, aspectratio='keep')
        ET.SubElement(icon, 'texture', fallback='DefaultAddon.png').text = '$INFO[ListItem.Art(thumb)]'
        label(box, '$INFO[ListItem.Label]', 164, 18, 835, 48, 'font37')
        label(box, '$INFO[ListItem.Property(version)]', 1020, 23, 235, 40, 'font23', 'FFADACB5')
        label(box, '$INFO[ListItem.Property(types)]', 164, 72, 780, 35, 'font23', 'FFB5A4E8')
        label(box, '$INFO[ListItem.Property(status)]', 965, 72, 290, 35, 'font23', 'FF78DEAC')
        label(box, '$INFO[ListItem.Property(description)]', 164, 110, 1080, 87, 'font23', 'FFCCCCD4', 'textbox')
    label(group, '$INFO[Window.Property(addons_empty)]', 540, 260, 1260, 160, kind='textbox')
    for cid, x, text, left, right in [(9301,540,'$INFO[Window.Property(addon_toggle)]',9300,9302),
                                     (9302,865,'Configure',9301,9303),
                                     (9303,1190,'Remove',9302,9304)]:
        button = node(group,'button',cid,left=x,top=910,width=300,height=65,font='font27',
                      label=text,textcolor='FFE5E5E7',focusedcolor='FF15121E',disabledcolor='FF65616F',
                      onleft=left,onright=right,onup=9300,ondown=9300,
                      enable='!String.IsEmpty(Window.Property(addon_selected))' if cid !=9302 else 'String.IsEqual(Window.Property(addon_configurable),true)')
        ET.SubElement(button,'texturefocus',border='14',colordiffuse='FFC4ACFF').text=MEDIA+'masks/flixicon-filled.png'
        ET.SubElement(button,'texturenofocus',border='14',colordiffuse='FF302B41').text=MEDIA+'masks/flixicon-filled.png'
    label(group,'$INFO[Window.Property(addon_selected)]  •  Right: actions  /  Left: sidebar',540,995,1300,40,'font23','FFADACB5')
