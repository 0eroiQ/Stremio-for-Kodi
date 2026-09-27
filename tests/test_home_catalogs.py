import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'lib'/(name+'.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
catalogs = load('home_catalogs')
layout = load('home_layout')

class HomeTests(unittest.TestCase):
    def test_account_order_and_required_filters(self):
        addons = [{'transportUrl': 'https://example.org/manifest.json', 'manifest': {'catalogs': [
            {'id':'z', 'name':'First', 'type':'movie'},
            {'id':'search', 'type':'movie', 'extra':[{'name':'search','isRequired':True}]},
            {'id':'a', 'name':'Second', 'type':'series'},
            {'id':'legacy', 'type':'movie', 'extraRequired':['genre']}]}}]
        specs = catalogs.descriptors(addons)
        self.assertEqual([s['catalog_id'] for s in specs], ['z','a'])
        rows = catalogs.load_rows(addons, lambda url: {'metas':[{'id':url,'name':'Title'}]},
                                 lambda url, resource, kind, cid: cid)
        self.assertEqual([r['label'] for r in rows], ['First','Second'])
        self.assertEqual(rows[1]['items'][0]['type'], 'series')

    def test_provider_failure_is_isolated(self):
        addons=[{'transportUrl':'test','manifest':{'catalogs':[{'id':x,'type':'movie'} for x in ['bad','good']]}}]
        def fetch(url):
            if url=='bad':raise ValueError('unavailable')
            return {'metas':[{'id':'title'}]}
        rows=catalogs.load_rows(addons,fetch,lambda u,r,k,i:i)
        self.assertTrue(rows[0]['failed']);self.assertEqual(rows[1]['items'][0]['id'],'title')

    def test_many_rows_have_unique_controls_and_consistent_geometry(self):
        with tempfile.TemporaryDirectory() as d:
            name,path,count=layout.build_layout(ROOT,d,60)
            tree=ET.parse(Path(path)/'resources/skins/Main/1080i'/name)
            group=tree.find('.//control[@id="2000"]')
            self.assertEqual(len(group.findall('control')),60)
            ids=[n.get('id') for n in tree.iter('control') if n.get('id')]
            self.assertEqual(len(ids),len(set(ids)))
            for index,row in enumerate(group.findall('control')):
                control=row.find("control[@type='fixedlist']")
                self.assertEqual(control.get('id'),str(400+index))
                self.assertEqual(control.findtext('top'),'22')
                self.assertEqual(row.findtext('height'),'440')
