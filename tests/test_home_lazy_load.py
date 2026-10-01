import unittest
from pathlib import Path
from lib.home_catalogs import load_more
class HomeLazyLoadTests(unittest.TestCase):
 def test_uses_skip_and_caps_page(self):
  seen=[]
  def url(manifest,res,kind,identity,extras=None):seen.append(extras);return 'x'
  def fetch(_):return {'metas':[{'id':str(i)} for i in range(30)]}
  spec={'url':'https://x/manifest.json','kind':'movie','catalog_id':'top'}
  rows,advanced=load_more(spec,fetch,url,16)
  self.assertEqual(seen,[{'skip':'16'}]);self.assertEqual(len(rows),16);self.assertEqual(advanced,16)

class HomeLazyRuntimeSpecTests(unittest.TestCase):
 def test_refresh_keeps_catalog_spec_for_runtime_pagination(self):
  source=Path(__file__).resolve().parents[1].joinpath('lib/backend.py').read_text()
  self.assertIn('save_snapshot(STORE.directory, catalog_rows)',source)
  self.assertNotIn('catalog_rows = save_snapshot(STORE.directory, catalog_rows)',source)

class HomePaginationCursorTests(unittest.TestCase):
 def test_runtime_uses_provider_cursor_not_unique_row_count(self):
  source=Path(__file__).resolve().parents[1].joinpath('lib/nimbus.py').read_text()
  self.assertIn('skip=self.home_row_cursor.get(cid,len(rows))',source)
  self.assertIn('self.home_row_cursor[cid]=skip+advanced',source)
  self.assertIn('if advanced<16:self.home_row_exhausted.add(cid)',source)
  self.assertNotIn('if not fresh:self.home_row_exhausted.add(cid)',source)
 def test_home_repopulate_resets_pagination_state(self):
  source=Path(__file__).resolve().parents[1].joinpath('lib/nimbus.py').read_text()
  self.assertIn('self.home_row_exhausted.clear()',source)
  self.assertIn('self.home_row_cursor.clear()',source)
