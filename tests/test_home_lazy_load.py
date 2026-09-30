import unittest
from lib.home_catalogs import load_more
class HomeLazyLoadTests(unittest.TestCase):
 def test_uses_skip_and_caps_page(self):
  seen=[]
  def url(manifest,res,kind,identity,extras=None):seen.append(extras);return 'x'
  def fetch(_):return {'metas':[{'id':str(i)} for i in range(30)]}
  spec={'url':'https://x/manifest.json','kind':'movie','catalog_id':'top'}
  rows=load_more(spec,fetch,url,16)
  self.assertEqual(seen,[{'skip':'16'}]);self.assertEqual(len(rows),16)
