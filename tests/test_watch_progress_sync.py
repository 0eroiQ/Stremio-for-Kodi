import copy
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'core'))

from core.playback_progress import apply_progress, playback_context, sync_progress


VIDEOS = [
    {'id':'tt100:1:1','season':1,'episode':1,'released':'2026-01-01T00:00:00Z'},
    {'id':'tt100:1:2','season':1,'episode':2,'released':'2026-01-08T00:00:00Z'},
    {'id':'tt100:1:3','season':1,'episode':3,'released':'2026-01-15T00:00:00Z'},
]


def context(video='tt100:1:1'):
    return {'meta_id':'tt100','video_id':video,'kind':'series','name':'Show',
            'poster':None,'posterShape':'poster','behaviorHints':{},'videos':copy.deepcopy(VIDEOS)}


class Store:
    def __init__(self, state): self.state=copy.deepcopy(state); self.saved=[]
    def load(self): return copy.deepcopy(self.state)
    def save(self, value): self.state=copy.deepcopy(value); self.saved.append(copy.deepcopy(value))
class ProgressStateTests(unittest.TestCase):
    NOW=datetime(2026,9,29,10,0,0,tzinfo=timezone.utc)

    def test_partial_episode_creates_native_resume_item(self):
        item=apply_progress([],context(),20*60*1000,45*60*1000,20*60*1000,now=self.NOW)
        self.assertEqual(item['_id'],'tt100')
        self.assertTrue(item['removed']); self.assertTrue(item['temp'])
        self.assertEqual(item['state']['video_id'],'tt100:1:1')
        self.assertEqual(item['state']['timeOffset'],20*60*1000)
        self.assertEqual(item['state']['duration'],45*60*1000)

    def test_existing_library_membership_is_preserved(self):
        existing=apply_progress([],context(),5_000,100_000,5_000,now=self.NOW)
        existing.update(removed=False,temp=False)
        item=apply_progress([existing],context(),20_000,100_000,15_000,now=self.NOW)
        self.assertFalse(item['removed']); self.assertFalse(item['temp'])
        self.assertEqual(item['state']['timeOffset'],20_000)

    def test_credits_threshold_advances_series_to_next_episode(self):
        item=apply_progress([],context(),91_000,100_000,75_000,now=self.NOW)
        state=item['state']
        self.assertEqual(state['video_id'],'tt100:1:2')
        self.assertEqual(state['timeOffset'],1)
        self.assertEqual(state['timeWatched'],0)
        self.assertEqual(state['flaggedWatched'],0)
        self.assertEqual(state['timesWatched'],1)
        self.assertTrue(state['watched'])
    def test_last_episode_completion_clears_resume(self):
        item=apply_progress([],context('tt100:1:3'),99_000,100_000,80_000,ended=True,now=self.NOW)
        self.assertEqual(item['state']['video_id'],'tt100:1:3')
        self.assertEqual(item['state']['timeOffset'],0)

    def test_seeked_position_does_not_need_to_equal_watched_time(self):
        item=apply_progress([],context(),80_000,200_000,10_000,now=self.NOW)
        self.assertEqual(item['state']['timeOffset'],80_000)
        self.assertEqual(item['state']['timeWatched'],10_000)
        self.assertEqual(item['state']['flaggedWatched'],0)

    def test_continue_watching_accepts_partial_and_next_episode_pointer(self):
        from account import library_rows
        partial=apply_progress([],context(),20_000,100_000,20_000,now=self.NOW)
        self.assertEqual(library_rows([partial],continuing=True),[partial])
        completed=apply_progress([],context(),95_000,100_000,80_000,now=self.NOW)
        self.assertEqual(completed['state']['timeOffset'],1)
        self.assertEqual(completed['state']['video_id'],'tt100:1:2')
        self.assertEqual(library_rows([completed],continuing=True),[completed])
        last=apply_progress([],context('tt100:1:3'),95_000,100_000,80_000,now=self.NOW)
        self.assertEqual(library_rows([last],continuing=True),[])

    def test_playback_meta_retains_series_parent_identity(self):
        from lib.stream_presenter import playback_meta
        meta={'id':'tt100','type':'series','name':'Show','videos':VIDEOS}
        result=playback_meta(meta,'tt100:1:2')
        self.assertEqual(result['_stremio_meta_id'],'tt100')
        self.assertEqual(result['id'],'tt100:1:2')
        self.assertEqual(playback_context(result,'series','tt100:1:2')['meta_id'],'tt100')

    def test_sync_pulls_latest_before_put_and_refreshes_local_state(self):
        initial={'token':'auth','library':[]}; store=Store(initial); calls=[]
        latest=[]
        verified=[apply_progress([],context(),30_000,100_000,30_000,now=self.NOW)]
        pulls=[latest,verified]
        def pull(token): calls.append(('pull',token)); return copy.deepcopy(pulls.pop(0))
        def request(url,payload): calls.append(('put',payload)); return {'result':{'success':True}}
        remote=sync_progress(store,context(),30_000,100_000,30_000,
                             request_func=request,pull_func=pull)
        self.assertEqual([c[0] for c in calls],['pull','put','pull'])
        self.assertEqual(remote['_id'],'tt100')
        self.assertEqual(store.state['library'][0]['state']['timeOffset'],30_000)
class WiringTests(unittest.TestCase):
    def test_observer_forces_saved_resume_when_kodi_starts_at_zero(self):
        xbmc=types.ModuleType('xbmc')
        class Base:
            def __init__(self): pass
        xbmc.Player=Base
        with patch.dict(sys.modules,{'xbmc':xbmc}):
            spec=importlib.util.spec_from_file_location('observer_resume_test',ROOT/'lib/playback_observer.py')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        player=module.ProgressPlayer()
        player._context=context(); player._position_ms=1000; player._duration_ms=1000000
        player._resume_target_ms=337690; player._resume_attempts=0
        calls=[]
        player.seekTime=lambda value: calls.append(value)
        with patch.object(module.time,'monotonic',return_value=123.0):
            player._apply_resume()
        self.assertEqual(calls,[337.69])
        self.assertEqual(player._position_ms,337690)
        self.assertEqual(player._resume_target_ms,0)

    def test_resolver_sets_native_resume_point_and_start_offset(self):
        text=(ROOT/'plugin.py').read_text()
        self.assertIn("entry.setProperty('StartOffset', str(resume_at))",text)
        self.assertIn('entry.getVideoInfoTag().setResumePoint(float(resume_at))',text)

    def test_plugin_marks_resolved_item_with_private_playback_key(self):
        text=(ROOT/'plugin.py').read_text()
        self.assertIn("entry.setProperty('StremioPlaybackKey', playback_key)",text)
        self.assertIn("Store(STORE.directory / 'playback-context').save",text)

    def test_service_runs_observer_even_when_autostart_is_disabled(self):
        text=(ROOT/'service.py').read_text()
        self.assertIn('player = ProgressPlayer()',text)
        self.assertIn('while not monitor.waitForAbort(1):',text)
        main=text.split('def main():',1)[1]
        self.assertNotIn('if ADDON.getSetting("startup_autostart") != "true":\n        return',main)

    def test_observer_counts_normal_playback_but_not_seek_jump(self):
        xbmc=types.ModuleType('xbmc')
        class Base:
            def __init__(self): pass
        xbmc.Player=Base
        with patch.dict(sys.modules,{'xbmc':xbmc}):
            spec=importlib.util.spec_from_file_location('observer_test',ROOT/'lib/playback_observer.py')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        player=module.ProgressPlayer()
        player._context=context(); player._last_position_ms=10_000; player._last_clock=100.0
        player._counting=True
        player.isPlayingVideo=lambda: True
        player.getTime=lambda: 11.0
        player.getTotalTime=lambda: 100.0
        with patch.object(module.time,'monotonic',return_value=101.0):
            player._sample()
        self.assertEqual(player._watched_ms,1000)
        player.getTime=lambda: 80.0
        with patch.object(module.time,'monotonic',return_value=102.0):
            player._sample()
        self.assertEqual(player._watched_ms,1000)


    def test_continue_index_keeps_all_series_not_just_recent_four(self):
        import tempfile
        from pathlib import Path
        from lib import continue_index
        library=[]
        for i in range(10):
            library.append({'_id':'tt%03d'%i,'type':'series','removed':False,'temp':False,'_mtime':'2026-10-01T%02d:00:00Z'%i,'state':{'video_id':'tt%03d:1:3'%i,'timeOffset':0,'flaggedWatched':1,'lastWatched':'2026-10-01T%02d:00:00Z'%i}})
        with tempfile.TemporaryDirectory() as tmp:
            continue_index.seed(Path(tmp),library)
            self.assertEqual(len(continue_index.unresolved_series(Path(tmp),32)),10)

    def test_continue_index_excludes_completed_movie_and_hides_completed_series_until_resolved(self):
        import tempfile
        from pathlib import Path
        from lib import continue_index
        library=[
          {'_id':'ttmovie','type':'movie','removed':False,'_mtime':'x','state':{'timeOffset':96000,'duration':100000,'flaggedWatched':1,'lastWatched':'x'}},
          {'_id':'ttshow','type':'series','removed':False,'_mtime':'y','state':{'video_id':'ttshow:1:3','timeOffset':96000,'duration':100000,'flaggedWatched':1,'lastWatched':'y'}}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);continue_index.seed(root,library)
            self.assertEqual(continue_index.rows(root,100),[])
            self.assertEqual([x[0] for x in continue_index.unresolved_series(root,100)],['ttshow'])

    def test_continue_index_treats_one_ms_series_sentinel_as_waiting(self):
        import tempfile
        from pathlib import Path
        from lib import continue_index
        row={'_id':'ttsentinel','type':'series','removed':False,'_mtime':'z','state':{'video_id':'ttsentinel:2:2','timeOffset':1,'duration':3000000,'flaggedWatched':0,'lastWatched':'z'}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);continue_index.seed(root,[row])
            self.assertEqual(continue_index.rows(root,10),[])
            self.assertEqual([x[0] for x in continue_index.unresolved_series(root,10)],['ttsentinel'])

    def test_continue_index_does_not_mark_ambiguous_series_finished(self):
        import tempfile
        from pathlib import Path
        from lib import continue_index
        row={'_id':'ttamb','id':'ttamb','type':'series','removed':False,'_mtime':'z','state':{'video_id':'ttamb:1:3','timeOffset':0,'duration':100000,'flaggedWatched':1,'lastWatched':'z'}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);continue_index.seed(root,[row]);continue_index.resolve_series(root,'ttamb',row,None,0,False)
            self.assertEqual(continue_index.rows(root,10),[])
            self.assertEqual([x[0] for x in continue_index.unresolved_series(root,10)],[])  # daily backoff, not falsely visible/finished

if __name__=='__main__':
    unittest.main()
