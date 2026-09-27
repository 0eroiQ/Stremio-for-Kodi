import tempfile
import unittest
from pathlib import Path
from lib.playback_settings import write_keymap

class PlaybackSettingsTests(unittest.TestCase):
    def test_toggle_preserves_other_keymaps(self):
        with tempfile.TemporaryDirectory() as d:
            other = Path(d)/'keyboard.xml'
            other.write_text('<keymap/>')
            self.assertTrue(write_keymap(d, True))
            self.assertFalse(write_keymap(d, True))
            self.assertTrue(write_keymap(d, False))
            self.assertEqual(other.read_text(), '<keymap/>')
            self.assertEqual(list(Path(d).iterdir()), [other])
