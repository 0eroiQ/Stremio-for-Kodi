"""Expand the bundled row template to the account's catalog count."""
import copy
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def build_layout(source, profile, count, appearance=None):
    tree = ET.parse(Path(source)/'resources/skins/Main/1080i/script-stremio-nimbus.xml')
    group = tree.find('.//control[@id="2000"]')
    template = copy.deepcopy(group.find('control'))
    for child in list(group.findall('control')):
        group.remove(child)
    count = max(2, count)
    for index in range(count):
        cid = 400 + index
        row = copy.deepcopy(template)
        for node in row.iter():
            def replace(text):
                if not text:
                    return text
                text = text.replace('400665', str(cid)+'665').replace('row400', 'row'+str(cid)).replace('has400', 'has'+str(cid))
                return re.sub(r'\b400\b', str(cid), text)
            node.text = replace(node.text)
            for key, value in list(node.attrib.items()):
                node.set(key, replace(value))
        listing = row.find("control[@type='fixedlist']")
        listing.find('onup').text = str(cid-1) if index else '9000'
        listing.find('ondown').text = str(cid+1) if index+1 < count else str(cid)
        heading = row.find("control[@type='group']")
        heading.find('top').text = '-10'
        group.append(row)
    menu = tree.find('.//control[@id="9000"]')
    menu.find('onright').text = 'SetFocus($INFO[Window.Property(first_row)])'
    controls = tree.getroot().find('controls')
    for index in range(3):
        button = ET.SubElement(controls, 'control', type='button', id=str(9200+index))
        tags = {'left':str(50+index*290), 'top':'535', 'width':'275', 'height':'60',
                'font':'font23', 'textcolor':'FFE5E5E7', 'focusedcolor':'FF15161D',
                'label':'$INFO[Window.Property(filter_label_%d)]' % index, 'align':'left', 'textoffsetx':'20',
                'visible':'[String.IsEqual(Window.Property(page),Discover) | String.IsEqual(Window.Property(page),Library)]',
                'onleft':str(9199+index) if index else '9000', 'onright':str(9200+min(index+1,2)),
                'onup':'9000', 'ondown':'SetFocus($INFO[Window.Property(first_row)])',
                'texturefocus':'special://home/addons/script.stremioelec/resources/skins/Main/media/controls/local-pill-h60-v1.png',
                'texturenofocus':'special://home/addons/script.stremioelec/resources/skins/Main/media/controls/local-pill-h60-v1.png'}
        for key,value in tags.items():
            node=ET.SubElement(button,key);node.text=value
            if key in ('texturefocus','texturenofocus'):
                node.set('border','30,0,30,0');node.set('colordiffuse','FFF0F0F2' if key=='texturefocus' else 'FF30313B')
        button.append(copy.deepcopy(group.find('animation')))
        ET.SubElement(button, 'animation', effect='slide', start='0,0', end='0,60', time='0',
                      condition='String.IsEqual(Window.Property(page),Discover)', reversible='true').text = 'Conditional'
        arrow = ET.SubElement(controls, 'control', type='image')
        for key,value in {'left':str(290+index*290),'top':'560','width':'16','height':'14',
                          'texture':'special://home/addons/script.stremioelec/resources/skins/Main/media/overlays/arrowdown.png',
                          'visible':tags['visible']}.items(): ET.SubElement(arrow,key).text=value
        arrow.append(copy.deepcopy(group.find('animation')))
        ET.SubElement(arrow, 'animation', effect='slide', start='0,0', end='0,60', time='0',
                      condition='String.IsEqual(Window.Property(page),Discover)', reversible='true').text = 'Conditional'
    group.find('top').text = '690'
    ET.SubElement(group, 'animation', effect='slide', start='0,0', end='0,-24', time='0',
                  condition='!String.IsEmpty(Window.Property(next_row))',
                  reversible='true').text = 'Conditional'
    preview = tree.find('.//control[@id="2001"]')
    preview.find('label').text = '$INFO[Window.Property(next_row)]'
    preview.find('visible').text = '!String.IsEmpty(Window.Property(next_row)) + !Control.HasFocus(9000)'
    from lib.addons_layout import build
    build(tree)
    # Apply animation preferences after the addon page has been added.
    from lib.appearance import apply
    apply(tree, appearance or {})
    from lib.theme import apply as apply_theme
    apply_theme(tree, (appearance or {}).get('theme', 0), (appearance or {}).get('color'))
    # Unique filename ensures the active global skin cannot substitute its own XML.
    path = Path(profile)/'home-layout'
    output = path/'resources/skins/Main/1080i'
    output.mkdir(parents=True, exist_ok=True)
    tree.write(output/'stremio-account-home.xml', encoding='utf-8', xml_declaration=True)
    return 'stremio-account-home.xml', str(path), count
