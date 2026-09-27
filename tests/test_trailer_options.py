import unittest
from lib.trailer_options import playback_url

class TrailerOptionsTests(unittest.TestCase):
    def test_auto_fallback_and_explicit_provider(self):
        installed=lambda name:name=='plugin.video.youtube'
        self.assertTrue(playback_url('abc','0',installed).startswith('plugin://plugin.video.youtube/'))
        self.assertEqual(playback_url('abc','1',installed),'')
        self.assertTrue(playback_url('abc','2',installed).endswith('video_id=abc'))
