from pathlib import Path
import unittest
class ExitBehaviorTests(unittest.TestCase):
 def test_main_back_opens_exit_confirmation_without_hidden_arm_state(self):
  source=Path(__file__).resolve().parents[1].joinpath('lib/nimbus.py').read_text()
  block=source[source.index('        if aid in BACK:'):source.index("        if aid in (1, 2, 3, 4, 7, 11, 100, 101):")]
  self.assertIn("'Exit Stremio for Kodi'",block);self.assertNotIn("if not getattr(self, 'exit_armed'",block)
