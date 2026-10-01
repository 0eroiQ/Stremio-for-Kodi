import tempfile,time,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lib import stream_index

class StreamIndexCacheTests(unittest.TestCase):
 def test_fresh_stale_signature_and_expiry(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);result=([{'url':'https://example.test/video','label':'A','provider':'P'}],0,0)
   self.assertTrue(stream_index.put(root,'series','ttx:1:1',result,'sig-a'))
   row=stream_index.get(root,'series','ttx:1:1','sig-a');self.assertTrue(row);self.assertFalse(row[4])
   self.assertIsNone(stream_index.get(root,'series','ttx:1:1','sig-b'))
   db=stream_index._connect(root);db.execute('UPDATE streams SET updated=?',(time.time()-stream_index.TTL-1,));db.commit();db.close()
   self.assertTrue(stream_index.get(root,'series','ttx:1:1','sig-a')[4])
   db=stream_index._connect(root);db.execute('UPDATE streams SET updated=?',(time.time()-stream_index.MAX_AGE-1,));db.commit();db.close()
   self.assertIsNone(stream_index.get(root,'series','ttx:1:1','sig-a'))

 def test_provider_signature_is_stable_and_sensitive(self):
  a=[{'transportUrl':'https://a.test/manifest.json','manifest':{'id':'a','version':'1'}}]
  b=[{'transportUrl':'https://a.test/manifest.json','manifest':{'id':'a','version':'2'}}]
  self.assertEqual(stream_index.provider_signature(a),stream_index.provider_signature(list(a)))
  self.assertNotEqual(stream_index.provider_signature(a),stream_index.provider_signature(b))
