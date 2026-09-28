"""Addon-owned appearance preferences; never changes the active Kodi skin."""
import xml.etree.ElementTree as ET

COLORS = ['FFFFFFFF', 'FF9B7BFF', 'FF55BBFF', 'FF55DD99', 'FFFFBB55']


def options(addon):
    from lib.theme import index, PALETTES
    selected = index(addon)
    try:
        value = addon.getSetting('ui_focus_color')
        poster = int(value) if value else 5
        color = COLORS[poster] if 0 <= poster < len(COLORS) else PALETTES[selected][5]
    except (TypeError, ValueError):
        color = PALETTES[selected][5]
    return {'theme': selected, 'color': color, 'animations': addon.getSetting('ui_animations') != 'false',
            'dim': addon.getSetting('ui_dim_rows') == 'true'}


def apply(tree, options):
    color = options.get('color', COLORS[0])
    for node in tree.iter():
        if color != COLORS[0] and node.tag in ('texture', 'bordertexture') and any(
                part in (node.text or '') for part in ('poster-glow', 'poster-border')):
            node.set('colordiffuse', color)
        if not options.get('animations', True) and node.tag in ('animation', 'effect'):
            node.set('time', '0')
            if 'delay' in node.attrib:
                node.set('delay', '0')
    button = tree.find('.//control[@id="9200"]/texturefocus')
    if button is not None and color != COLORS[0]:
        button.set('colordiffuse', color)
    group = tree.find('.//control[@id="2000"]')
    if group is not None and options.get('dim'):
        ET.SubElement(group, 'animation', effect='fade', start='100', end='45',
                      time='180' if options.get('animations', True) else '0',
                      condition='Control.HasFocus(9000)', reversible='true').text = 'Conditional'
