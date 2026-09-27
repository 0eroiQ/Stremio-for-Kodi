"""Expand the bundled row template to the account's catalog count."""
import copy
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def build_layout(source, profile, count):
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
    preview = tree.find('.//control[@id="2001"]')
    preview.find('label').text = '$INFO[Window.Property(next_row)]'
    preview.find('visible').text = '!String.IsEmpty(Window.Property(next_row)) + !Control.HasFocus(9000)'
    # Unique filename ensures the active global skin cannot substitute its own XML.
    path = Path(profile)/'home-layout'
    output = path/'resources/skins/Main/1080i'
    output.mkdir(parents=True, exist_ok=True)
    tree.write(output/'stremio-account-home.xml', encoding='utf-8', xml_declaration=True)
    return 'stremio-account-home.xml', str(path), count
