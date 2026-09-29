"""Installed addons: stream-style cards and a focus-driven, collapsible sidebar."""
import xml.etree.ElementTree as ET

MEDIA = 'special://home/addons/script.stremioelec/resources/skins/Main/media/'
PAGE = 'String.IsEqual(Window.Property(page),Addons)'
PAGE_GROUP = 9400


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


def surface(parent, texture, color):
    control = node(parent, 'image', left=0, top=0, width=1280, height=202)
    ET.SubElement(control, 'texture', border='24', colordiffuse=color).text = (
        MEDIA + 'streams-local/' + texture + '.png')
    return control


def action_button(parent, cid, x, text, left, right, enable='true'):
    target = 'SetFocus($INFO[Window.Property(addons_list_focus)])'
    control = node(parent, 'button', cid, left=x, top=910, width=300, height=65,
                   label=text, font='font23_title', align='center', aligny='center',
                   textcolor='FFE5E5E7', focusedcolor='FF15161D', disabledcolor='FF65616F',
                   onleft=left, onright=right, onup=target, ondown=target, enable=enable)
    for tag, color in (('texturenofocus', 'C0302B41'), ('texturefocus', 'FFC4ACFF')):
        ET.SubElement(control, tag, border='24', colordiffuse=color).text = (
            MEDIA + 'streams-local/row-fill.png')
    return control


def build(tree):
    controls = tree.find('controls')
    sidebar = None
    for control in list(controls)[1:]:
        if control.find('.//control[@id="9000"]') is not None:
            # Leave its focus-only animation intact; Addons must not pin it open.
            sidebar = control
            continue
        visible = control.find('visible')
        if visible is None:
            visible = ET.SubElement(control, 'visible')
            visible.text = '!' + PAGE
        else:
            visible.text = '[' + (visible.text or 'true') + '] + !' + PAGE
    # Keep the same card sizes and three-row list, centred with the drawer shut.
    group = node(controls, 'group', PAGE_GROUP, left=320, top=0, visible=PAGE)
    try:
        drawer_width = abs(int(sidebar.findtext('left', '0'))) if sidebar is not None else 0
    except (TypeError, ValueError):
        drawer_width = 0
    if drawer_width:
        ET.SubElement(group, 'animation', effect='slide', start='0,0',
                      end='{},0'.format(drawer_width // 2), time='500', tween='cubic',
                      easing='inout', condition='Control.HasFocus(9000)',
                      reversible='true').text = 'Conditional'
    label(group, 'Addons', 0, 65, 1100, 70, 'font52_title')
    label(group, '$INFO[Window.Property(addons_summary)]', 0, 145, 1280, 45, 'font23', 'FFADACB5')
    listing = node(group, 'list', 9300, left=0, top=215, width=1300, height=660,
                   onleft=9000, onright=9301, onup=9304, ondown=9304,
                   scrolltime=180, orientation='vertical')
    for layout, fill, edge in (('itemlayout', 'B8242333', '6042365C'),
                               ('focusedlayout', 'DC42365C', 'C0C4ACFF')):
        box = ET.SubElement(listing, layout, width='1300', height='220')
        surface(box, 'row-fill', fill)
        surface(box, 'row-outline', edge)
        icon = node(box, 'image', left=24, top=42, width=112, height=112, aspectratio='keep')
        ET.SubElement(icon, 'texture', fallback='DefaultAddon.png').text = '$INFO[ListItem.Art(thumb)]'
        title = label(box, '$INFO[ListItem.Label]', 164, 18, 835, 48, 'font32_title',
                      'FFFFFFFF' if layout == 'focusedlayout' else 'FFE5E5E7')
        ET.SubElement(title, 'scroll').text = 'true' if layout == 'focusedlayout' else 'false'
        version = label(box, '$INFO[ListItem.Property(version)]', 1020, 23, 235, 40, 'font23', 'FFADACB5')
        ET.SubElement(version, 'align').text = 'right'
        label(box, '$INFO[ListItem.Property(types)]', 164, 72, 780, 35, 'font23', 'FFB5A4E8')
        status = label(box, '$INFO[ListItem.Property(status)]', 965, 72, 290, 35, 'font23', 'FF78DEAC')
        ET.SubElement(status, 'align').text = 'right'
        label(box, '$INFO[ListItem.Property(description)]', 164, 110, 1080, 87,
              'font23', 'FFE5E5E7' if layout == 'focusedlayout' else 'FFADACB5', 'textbox')
    label(group, '$INFO[Window.Property(addons_empty)]', 0, 260, 1260, 160, kind='textbox')
    selected = '!String.IsEmpty(Window.Property(addon_selected))'
    action_button(group, 9301, 0, '$INFO[Window.Property(addon_toggle)]', 9300, 9302, selected)
    action_button(group, 9302, 325, 'Configure', 9301, 9303,
                  'String.IsEqual(Window.Property(addon_configurable),true)')
    action_button(group, 9303, 650, 'Remove', 9302, 9304, selected)
    action_button(group, 9304, 975, '+ Add addon', 9303, 9304)
    label(group, '$INFO[Window.Property(addon_selected)]  •  Right: actions  /  Left: sidebar',
          0, 995, 1280, 40, 'font23', 'FFADACB5')
