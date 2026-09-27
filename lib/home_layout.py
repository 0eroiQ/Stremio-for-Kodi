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
        group.append(row)
    menu = tree.find('.//control[@id="9000"]')
    menu.find('onright').text = 'SetFocus($INFO[Window.Property(first_row)])'
    controls = tree.getroot().find('controls')
    button = ET.SubElement(controls, 'control', type='button', id='9200')
    tags = {'left':'50', 'top':'535', 'width':'160', 'height':'65',
            'font':'font25', 'textcolor':'FFFFFFFF', 'focusedcolor':'FFFFFFFF',
            'label':'Filters', 'align':'center',
            'visible':'[String.IsEqual(Window.Property(page),Discover) | String.IsEqual(Window.Property(page),Library)]',
            'onleft':'9000', 'onup':'9000', 'ondown':'SetFocus($INFO[Window.Property(first_row)])',
            'texturefocus':'special://home/addons/script.stremioelec/resources/skins/Main/media/solid.png',
            'texturenofocus':'special://home/addons/script.stremioelec/resources/skins/Main/media/solid.png'}
    for key,value in tags.items():
        node=ET.SubElement(button,key);node.text=value
        if key in ('texturefocus','texturenofocus'):
            node.set('colordiffuse', 'FF7355DE' if key=='texturefocus' else 'DD252333')
    button.append(copy.deepcopy(group.find('animation')))
    summary = ET.SubElement(controls, 'control', type='label')
    for key, value in {'left':'230', 'top':'535', 'width':'1000', 'height':'65',
                       'font':'font25', 'textcolor':'FFBBBBBB',
                       'label':'$INFO[Window.Property(filters)]',
                       'visible':tags['visible']}.items():
        ET.SubElement(summary, key).text = value
    summary.append(copy.deepcopy(group.find('animation')))
    preview = tree.find('.//control[@id="2001"]')
    preview.find('label').text = '$INFO[Window.Property(next_row)]'
    preview.find('visible').text = '!String.IsEmpty(Window.Property(next_row)) + !Control.HasFocus(9000)'
    from lib.appearance import apply
    apply(tree, appearance or {})
    # Unique filename ensures the active global skin cannot substitute its own XML.
    path = Path(profile)/'home-layout'
    output = path/'resources/skins/Main/1080i'
    output.mkdir(parents=True, exist_ok=True)
    tree.write(output/'stremio-account-home.xml', encoding='utf-8', xml_declaration=True)
    return 'stremio-account-home.xml', str(path), count
