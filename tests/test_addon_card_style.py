"""Addon rows reuse stream surfaces without changing layout or navigation."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from lib.addons_layout import build
from lib.theme import apply, PALETTES

ROOT = Path(__file__).resolve().parents[1]


def layout_tree():
    tree = ET.ElementTree(ET.fromstring('<window><controls /></window>'))
    build(tree)
    return tree


class AddonCardStyleTests(unittest.TestCase):
    def test_surfaces_match_stream_rows(self):
        tree = layout_tree()
        streams = ET.parse(ROOT / 'resources/skins/Main/1080i/script-stremio-info.xml')
        for name in ('itemlayout', 'focusedlayout'):
            card = tree.find('.//control[@id="9300"]/' + name)
            reference = streams.find('.//control[@id="7100"]/' + name)
            for actual, expected in zip(list(card)[:2], list(reference)[:2]):
                texture, source = actual.find('texture'), expected.find('texture')
                self.assertEqual(texture.text, source.text)
                self.assertEqual(texture.attrib, source.attrib)
                asset = ROOT / texture.text.split('script.stremioelec/', 1)[1]
                self.assertEqual(asset.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_dimensions_content_and_navigation_preserved(self):
        tree = layout_tree()
        self.assertEqual(tree.find('.//control[@id="9400"]').findtext('left'), '320')
        listing = tree.find('.//control[@id="9300"]')
        self.assertEqual([listing.findtext(k) for k in ('left', 'top', 'width', 'height')],
                         ['0', '215', '1300', '660'])
        self.assertEqual([listing.findtext(k) for k in ('onleft', 'onright', 'onup', 'ondown')],
                         ['9000', '9301', '9304', '9304'])
        for name in ('itemlayout', 'focusedlayout'):
            card = listing.find(name)
            self.assertEqual(card.attrib, {'width': '1300', 'height': '220'})
            for surface in list(card)[:2]:
                self.assertEqual([surface.findtext(k) for k in ('left', 'top', 'width', 'height')],
                                 ['0', '0', '1280', '202'])
            labels = [n.findtext('label') for n in card.findall('control') if n.find('label') is not None]
            self.assertEqual(labels, ['$INFO[ListItem.Label]', '$INFO[ListItem.Property(version)]',
                '$INFO[ListItem.Property(types)]', '$INFO[ListItem.Property(status)]',
                '$INFO[ListItem.Property(description)]'])
            icon = list(card)[2]
            self.assertEqual(icon.findtext('texture'), '$INFO[ListItem.Art(thumb)]')
            self.assertEqual(icon.find('texture').get('fallback'), 'DefaultAddon.png')
        for cid in ('9301', '9302', '9303', '9304'):
            button = tree.find('.//control[@id="' + cid + '"]')
            self.assertEqual(button.findtext('top'), '910')
            self.assertEqual(button.findtext('height'), '65')
            self.assertEqual(button.findtext('width'), '300')

    def test_all_themes_keep_stream_opacity_and_focus_colours(self):
        for index, palette in enumerate(PALETTES):
            tree = layout_tree()
            apply(tree, index)
            normal = tree.find('.//control[@id="9300"]/itemlayout')
            focused = tree.find('.//control[@id="9300"]/focusedlayout')
            self.assertEqual(normal[0].find('texture').get('colordiffuse'), 'B8' + palette[2][2:])
            self.assertEqual(normal[1].find('texture').get('colordiffuse'), '60' + palette[4][2:])
            self.assertEqual(focused[0].find('texture').get('colordiffuse'), 'DC' + palette[4][2:])
            self.assertEqual(focused[1].find('texture').get('colordiffuse'), 'C0' + palette[5][2:])
            self.assertEqual(focused[2].find('texture').attrib, {'fallback': 'DefaultAddon.png'})


if __name__ == '__main__':
    unittest.main()
