import unittest
import xml.etree.ElementTree as ET
from lib.appearance import apply

class AppearanceTests(unittest.TestCase):
    def test_no_animation_preserves_sidebar_position_rule_and_dims_rows(self):
        tree=ET.ElementTree(ET.fromstring('<window><control id="2000"><animation effect="slide" end="490,0" time="500" condition="Control.HasFocus(9000)">Conditional</animation></control><texture colordiffuse="FFFFFFFF">masks/poster-glow-widget.png</texture></window>'))
        apply(tree, {'color':'FF55BBFF','animations':False,'dim':True})
        self.assertEqual(tree.find('.//animation').get('time'),'0')
        self.assertEqual(tree.find('.//animation').get('end'),'490,0')
        self.assertEqual(tree.find('.//texture').get('colordiffuse'),'FF55BBFF')
        self.assertEqual(tree.findall('.//animation')[1].get('end'),'45')
