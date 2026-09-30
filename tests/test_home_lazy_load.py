import unittest
from pathlib import Path
from lib.home_catalogs import load_more
class HomeLazyLoadTests(unittest.TestCase):
 def test_uses_skip_and_caps_page(self):
  seen=[]
  def url(manifest,res,kind,identity,extras=None):seen.append(extras);return 'x'
  def fetch(_):return {'metas':[{'id':str(i)} for i in range(30)]}
  spec={'url':'https://x/manifest.json','kind':'movie','catalog_id':'top'}
  rows=load_more(spec,fetch,url,16)
  self.assertEqual(seen,[{'skip':'16'}]);self.assertEqual(len(rows),16)

class HomeLazyRuntimeSpecTests(unittest.TestCase):
 def test_refresh_keeps_catalog_spec_for_runtime_pagination(self):
  source=Path(__file__).resolve().parents[1].joinpath('lib/backend.py').read_text()
  self.assertIn('save_snapshot(STORE.directory, catalog_rows)',source)
  self.assertNotIn('catalog_rows = save_snapshot(STORE.directory, catalog_rows)',source)
