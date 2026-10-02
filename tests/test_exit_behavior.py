from pathlib import Path
import unittest
class ExitBehaviorTests(unittest.TestCase):
 def test_main_back_returns_non_home_pages_home_before_exit(self):
  source=Path(__file__).resolve().parents[1].joinpath('lib/nimbus.py').read_text()
  start=source.index('        if aid in BACK:')
  block=source[start:source.index("        if aid in (1, 2, 3, 4, 7, 11, 100, 101):",start)]
  self.assertIn("self.getProperty('page') != 'Home'",block)
  self.assertIn('self.load_home()',block)
  self.assertIn('sidebar.selectItem(home_index())',block)
  self.assertIn("'Exit Stremio for Kodi'",block)
  self.assertLess(block.index("self.getProperty('page') != 'Home'"),block.index("'Exit Stremio for Kodi'"))
