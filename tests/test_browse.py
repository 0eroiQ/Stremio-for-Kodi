import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('browse',Path(__file__).resolve().parents[1]/'lib/browse.py')
browse=importlib.util.module_from_spec(spec);spec.loader.exec_module(browse)

class BrowseTests(unittest.TestCase):
    def test_discover_uses_account_catalogs_and_manifest_filters(self):
        catalog=[{'id':'popular','type':'movie','extra':[{'name':'genre','options':['Drama','Comedy']}]},
                 {'id':'filtered','type':'series','extra':[{'name':'genre','isRequired':True,'options':['Action']}]},
                 {'id':'search','type':'movie','extra':[{'name':'search','isRequired':True}]}]
        addons=[{'account':True,'transportUrl':'test','manifest':{'catalogs':catalog}},
                {'account':False,'transportUrl':'local','manifest':{'catalogs':catalog}}]
        rows=browse.discover_catalogs(addons)
        self.assertEqual([r['id'] for r in rows],['popular','filtered'])
        self.assertEqual(rows[0]['extras'][0]['options'],['Drama','Comedy'])
        self.assertEqual(rows[1]['defaults'],{'genre':'Action'})

    def test_library_excludes_removed_and_temporary_entries(self):
        entries=[{'_id':str(i),'name':name,'type':kind,'_ctime':date,**flags} for i,name,kind,date,flags in [
            (1,'Zulu','movie','2026-01-01',{}),(2,'Alpha','movie','2026-02-01',{}),
            (3,'Series','series','2026-03-01',{}),(4,'Removed','movie','2026-04-01',{'removed':True}),
            (5,'Temp','series','2026-05-01',{'temp':True})]]
        rows=browse.library_sections(entries)
        self.assertEqual([r['label'] for r in rows],['Movies','Series'])
        self.assertEqual([e['id'] for e in rows[0]['items']],['2','1'])
        self.assertEqual(len(browse.library_sections(entries,'series')[0]['items']),1)
        self.assertEqual(browse.library_sections(entries,'movie','name')[0]['items'][0]['name'],'Alpha')

    def test_empty_library_is_not_populated_with_home_catalogs(self):
        self.assertEqual(browse.library_sections([]),[])
