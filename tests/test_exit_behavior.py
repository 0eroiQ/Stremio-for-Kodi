from pathlib import Path
import unittest
class ExitBehaviorTests(unittest.TestCase):
 def test_first_back_only_arms_exit_and_second_back_can_confirm(self):
  source=Path(__file__).resolve().parents[1].joinpath('lib/nimbus.py').read_text()
  start=source.index('        if aid in BACK:',source.index('class HomeWindow'))
  block=source[start:source.index("        if aid in (1, 2, 3, 4, 7, 11, 100, 101):",start)]
  self.assertIn("if not getattr(self, 'exit_armed', False):",block)
  self.assertIn('self.cancel_trailer()',block)
  self.assertIn('self.setFocusId(9000)',block)
  self.assertIn('self.exit_armed = True',block)
  self.assertIn("'Exit Stremio for Kodi'",block)
  self.assertLess(block.index('self.exit_armed = True'),block.index("'Exit Stremio for Kodi'"))
