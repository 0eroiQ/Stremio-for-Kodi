import tempfile,unittest
from pathlib import Path
from lib.stream_index import get,put
class StreamIndexTests(unittest.TestCase):
 def test_persists_last_known_good(self):
  with tempfile.TemporaryDirectory() as d:
   result=([{'url':'https://x/video','label':'A','provider':'P','detail':'1080p','filename':'x.mkv'}],1,0)
   self.assertTrue(put(Path(d),'movie','tt1',result));cached=get(Path(d),'movie','tt1');self.assertEqual(cached[0][0]['url'],'https://x/video');self.assertEqual(cached[1:3],(1,0))
 def test_empty_refresh_does_not_replace_good(self):
  with tempfile.TemporaryDirectory() as d:
   put(Path(d),'movie','tt1',([{'url':'https://x'}],0,0));self.assertFalse(put(Path(d),'movie','tt1',([],0,1)));self.assertEqual(get(Path(d),'movie','tt1')[0][0]['url'],'https://x')
