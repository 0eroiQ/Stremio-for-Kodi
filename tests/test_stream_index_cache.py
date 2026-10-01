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

class ContinuePrefetchIdentityTests(unittest.TestCase):
 def test_prefetch_uses_episode_identity_for_series(self):
  from lib import continue_index
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   library=[{'_id':'ttshow','type':'series','removed':False,'_mtime':'x','state':{'video_id':'ttshow:2:4','timeOffset':120000,'duration':3000000,'lastWatched':'x'}},{'_id':'ttmovie','type':'movie','removed':False,'_mtime':'y','state':{'timeOffset':120000,'duration':6000000,'lastWatched':'y'}}]
   continue_index.seed(root,library);rows=continue_index.prefetch_rows(root,10);pairs={(x[0],x[1]) for x in rows}
   self.assertIn(('series','ttshow:2:4'),pairs);self.assertIn(('movie','ttmovie'),pairs)
