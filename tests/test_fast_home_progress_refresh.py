import tempfile
import time
import unittest
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'core'))

from lib import home_snapshot
from continue_playback import resume_seconds, next_series_episode


class FastHomeTests(unittest.TestCase):
    def test_snapshot_roundtrip_is_display_only_and_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            rows=[{'label':'Popular','provider':'secret-provider-id','kind':'movie',
                   'catalog_id':'top','url':'https://example.test/manifest.json',
                   'items':[{'id':'tt1','type':'movie','name':'One'}]}]
            home_snapshot.save(directory,rows)
            started=time.perf_counter()
            loaded=home_snapshot.load(directory)
            elapsed=time.perf_counter()-started
            self.assertLess(elapsed,0.25)
            self.assertEqual(loaded[0]['items'][0]['id'],'tt1')
            raw=(directory/'home-snapshot'/'account.json').read_text()
            self.assertNotIn('example.test',raw)
            self.assertNotIn('manifest.json',raw)

    def test_failed_refresh_keeps_previous_catalog_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            first=[{'label':'Popular','provider':'p','kind':'movie','catalog_id':'top',
                    'items':[{'id':'tt1','type':'movie','name':'One'}]}]
            home_snapshot.save(directory,first)
            failed=[{'label':'Popular','provider':'p','kind':'movie','catalog_id':'top',
                     'items':[],'failed':True}]
            rows=home_snapshot.save(directory,failed)
            self.assertEqual(rows[0]['items'][0]['id'],'tt1')
            self.assertTrue(rows[0]['failed'])

    def test_continue_rows_are_built_from_local_progress_without_network(self):
        library=[{'_id':'tt1','type':'movie','name':'One','temp':True,'removed':True,
                  'state':{'timeOffset':123000,'lastWatched':'2026-09-29T10:00:00Z'}}]
        rows=home_snapshot.update_continue_rows(
            [{'label':'Popular','items':[{'id':'tt1','type':'movie','name':'One','poster':'p'}]}],
            library)
        self.assertEqual(rows[0]['label'],'Continue Watching')
        self.assertEqual(rows[0]['items'][0]['state']['timeOffset'],123000)
        self.assertEqual(rows[0]['items'][0]['poster'],'p')


class StartupWiringTests(unittest.TestCase):
    def test_app_opens_cached_home_without_waiting_for_catalog_network(self):
        text=(ROOT/'lib/app.py').read_text()
        self.assertIn('backend.account_home(False)',text)
        self.assertNotIn("Loading your account catalogs",text)

    def test_home_revalidates_after_window_is_visible(self):
        text=(ROOT/'lib/nimbus.py').read_text()
        self.assertIn('self.load_home()',text)
        self.assertIn('self.setFocusId(9000)\n        self.refresh_home_async()',text)
        self.assertIn('fresh = api.account_home(True)',text)


class PosterProgressTests(unittest.TestCase):
    def test_home_skin_has_plex_style_progress_in_both_layouts(self):
        import xml.etree.ElementTree as ET
        tree=ET.parse(ROOT/'resources/skins/Main/1080i/script-stremio-nimbus.xml')
        fixed=tree.find('.//control[@type="fixedlist"][@id="400"]')
        for name in ('itemlayout','focusedlayout'):
            bars=[c for c in fixed.find(name).iter('control')
                  if c.get('type')=='progress' and c.findtext('description')=='Stremio watch progress']
            self.assertEqual(len(bars),1)
            self.assertEqual(bars[0].findtext('info'),'ListItem.PercentPlayed')
            self.assertIn('WatchedProgress',bars[0].findtext('visible'))

    def test_nimbus_sets_native_resume_point_for_poster_progress(self):
        text=(ROOT/'lib/nimbus.py').read_text()
        self.assertIn("li.setProperty('WatchedProgress', str(progress))",text)
        self.assertIn('li.getVideoInfoTag().setResumePoint(offset, duration)',text)


    def test_progress_fill_follows_every_theme_accent(self):
        import copy
        import xml.etree.ElementTree as ET
        from lib.theme import apply, PALETTES
        for filename in ('script-stremio-nimbus.xml','script-stremio-info.xml'):
            source=ET.parse(ROOT/'resources/skins/Main/1080i'/filename)
            for index,palette in enumerate(PALETTES):
                tree=copy.deepcopy(source)
                apply(tree,index)
                fills=[node.get('colordiffuse') for node in tree.iter('midtexture')
                       if 'progress-local/capsule.png' in (node.text or '')]
                self.assertTrue(fills)
                self.assertTrue(all(value == palette[6] for value in fills))


class ResumeSentinelTests(unittest.TestCase):
    def test_one_millisecond_next_episode_sentinel_is_play_not_resume(self):
        self.assertEqual(resume_seconds(1),0)
        videos=[{'id':'tt1:1:1','season':1,'episode':1},
                {'id':'tt1:1:2','season':1,'episode':2}]
        video,offset=next_series_episode(
            videos,'tt1',{'_id':'tt1','type':'series',
                           'state':{'video_id':'tt1:1:2','timeOffset':1}})
        self.assertEqual(video['id'],'tt1:1:2')
        self.assertEqual(offset,0)


class HomePerformanceBudgetTests(unittest.TestCase):
    def test_home_snapshot_caps_each_row_for_low_power_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            items=[{'id':'tt{}'.format(i),'type':'movie','name':str(i)} for i in range(100)]
            rows=home_snapshot.save(directory,[{'label':'Big','items':items,'failed':False}])
            self.assertEqual(len(rows[0]['items']),16)

    def test_catalog_loader_uses_bounded_defaults(self):
        from lib import home_catalogs
        self.assertEqual(home_catalogs.HOME_ITEM_LIMIT,16)
        self.assertEqual(home_catalogs.MAX_WORKERS,2)

    def test_home_refresh_bounds_completed_series_metadata_verification(self):
        text=(ROOT/'lib/backend.py').read_text()
        self.assertIn('_continue_rows(state, catalog_rows, True)', text)
        self.assertIn('continue_index.unresolved_series(STORE.directory, 8)', text)
        self.assertIn('continue_index.rows(STORE.directory, 100)', text)


class PerformanceTraceWiringTests(unittest.TestCase):
    def test_home_records_safe_stage_timings(self):
        backend=(ROOT/'lib/backend.py').read_text()
        nimbus=(ROOT/'lib/nimbus.py').read_text()
        self.assertIn("perf_log('home.cached'",backend)
        self.assertIn("perf_log('home.refresh.account'",backend)
        self.assertIn("perf_log('home.refresh.catalogs'",backend)
        self.assertIn("perf_log('home.refresh.library'",backend)
        self.assertIn("perf_log('home.refresh.total'",backend)
        self.assertIn("perf_log('ui.home.initial'",nimbus)
        self.assertIn("perf_log('ui.home.repopulate'",nimbus)

    def test_perf_trace_never_accepts_freeform_values(self):
        text=(ROOT/'lib/perf_trace.py').read_text()
        self.assertNotIn('**fields',text)
        self.assertIn('value = int(counts[key])',text)


class PerformanceReportTests(unittest.TestCase):
    def test_performance_payload_contains_only_allowlisted_timings(self):
        from lib.perf_report import record, build_payload
        with tempfile.TemporaryDirectory() as tmp:
            profile=Path(tmp)
            record(profile,'home.refresh.catalogs',1234,rows=7,items=88,secret='nope')
            payload=build_payload(profile,{'addonVersion':'1.0.50','kodiVersion':'21','platform':'Linux','pythonVersion':'3.11'})
            self.assertEqual(payload['errorType'],'PerformanceReport')
            self.assertEqual(payload['performance']['home.refresh.catalogs'],{'ms':1234,'rows':7,'items':88})
            raw=str(payload).lower()
            for forbidden in ('token','url','title','api_key','device'):
                self.assertNotIn(forbidden,raw)

    def test_support_exposes_explicit_performance_report(self):
        settings=(ROOT/'resources/settings.xml').read_text()
        page=(ROOT/'lib/settings_page.py').read_text()
        self.assertIn('send_performance_report',settings)
        self.assertIn('Send performance report',page)


if __name__=='__main__':
    unittest.main()
