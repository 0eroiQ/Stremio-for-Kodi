import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'core'))

from episode_actions import apply_through, range_through, sync_through, through_is_watched
from context_options import episode_options, continue_options
from lib.episode_state import watched_ids

NOW=datetime(2026,9,29,12,0,0,tzinfo=timezone.utc)


def videos():
    rows=[]
    for season,count in ((1,4),(2,6)):
        for episode in range(1,count+1):
            rows.append({'id':'show:{}:{}'.format(season,episode),
                         'season':season,'episode':episode,
                         'released':'2026-01-{:02d}T00:00:00Z'.format(min(28,episode))})
    return rows


def meta():
    return {'id':'show','type':'series','name':'Show','poster':'poster','videos':videos()}


class Store:
    def __init__(self,state): self.state=copy.deepcopy(state)
    def load(self): return copy.deepcopy(self.state)
    def save(self,value): self.state=copy.deepcopy(value)


class MarkWatchedUpToHereTests(unittest.TestCase):
    def test_s2e5_selects_every_regular_episode_from_start_through_target(self):
        selected=range_through(videos(),'show:2:5')
        self.assertEqual(selected,[
            'show:1:1','show:1:2','show:1:3','show:1:4',
            'show:2:1','show:2:2','show:2:3','show:2:4','show:2:5'])

    def test_mark_watched_through_s2e5_sets_all_nine_bits_but_not_s2e6(self):
        item,selected=apply_through([],meta(),'show:2:5',True,NOW)
        marked=watched_ids(videos(),item)
        self.assertEqual(marked,set(selected))
        self.assertNotIn('show:2:6',marked)
        self.assertEqual(item['state']['video_id'],'show:2:6')
        self.assertEqual(item['state']['timeOffset'],1)
        self.assertEqual(item['state']['flaggedWatched'],0)

    def test_mark_unwatched_through_target_clears_earlier_but_preserves_later(self):
        watched_item,_=apply_through([],meta(),'show:2:6',True,NOW)
        item,selected=apply_through([watched_item],meta(),'show:2:5',False,NOW)
        marked=watched_ids(videos(),item)
        self.assertEqual(marked,{'show:2:6'})
        self.assertEqual(len(selected),9)
        self.assertEqual(item['state']['flaggedWatched'],0)

    def test_sync_uses_one_datastore_put_then_verifies(self):
        store=Store({'token':'auth','library':[]})
        calls=[]
        written=[]
        pull_count=[0]
        def request(url,payload):
            calls.append(('put',url))
            written[:] = copy.deepcopy(payload['changes'])
            return {'result':{'success':True}}
        def pull(token):
            calls.append(('pull',token))
            pull_count[0] += 1
            return [] if pull_count[0] == 1 else copy.deepcopy(written)
        remote,selected=sync_through(store,meta(),'show:2:5',True,
                                     request_func=request,pull_func=pull)
        self.assertEqual([kind for kind,_ in calls],['pull','put','pull'])
        self.assertEqual(len(selected),9)
        self.assertEqual(watched_ids(videos(),remote),set(selected))
        self.assertEqual(store.state['library'][0]['_id'],'show')

    def test_episode_menu_is_state_aware_and_never_shows_both_here_actions(self):
        unwatched=episode_options(False,False,False)
        self.assertEqual([x['label'] for x in unwatched],
            ['Play','Play from Beginning','Mark as Watched','Mark Here as Watched','More Info'])
        watched=episode_options(True,True,False)
        self.assertEqual([x['label'] for x in watched],
            ['Play','Play from Beginning','Mark as Unwatched','Mark Here as Unwatched','More Info'])
        partial_prefix=episode_options(True,False,False)
        self.assertIn('Mark Here as Watched',[x['label'] for x in partial_prefix])
        self.assertNotIn('Mark Here as Unwatched',[x['label'] for x in partial_prefix])
        resume=episode_options(False,False,True)
        self.assertEqual(resume[0]['label'],'Resume')

    def test_through_state_requires_every_episode_in_prefix_to_be_watched(self):
        prefix=range_through(videos(),'show:2:5')
        self.assertTrue(through_is_watched(videos(),'show:2:5',prefix))
        missing=set(prefix); missing.remove('show:1:3')
        self.assertFalse(through_is_watched(videos(),'show:2:5',missing))

    def test_info_window_routes_context_action_117_to_vertical_media_menu(self):
        text=(ROOT/'lib/nimbus.py').read_text()
        self.assertIn("if aid == 117 and self.episode_context_menu():",text)
        self.assertIn("from lib.media_action_menu import choose",text)
        self.assertIn("episode_options(watched, prefix_watched, resume)",text)
        self.assertNotIn("EpisodeContextWindow",text)

    def test_vertical_menu_has_rounded_panel_icons_and_theme_focus(self):
        import copy
        import xml.etree.ElementTree as ET
        from lib.theme import apply, PALETTES
        source=ET.parse(ROOT/'resources/skins/Main/1080i/script-stremio-media-actions.xml')
        self.assertIsNotNone(source.find('.//control[@id="600"]'))
        panel=source.find('.//control[@id="100"]/texture')
        self.assertIn('local-card-rounded.png',panel.text)
        for index,palette in enumerate(PALETTES):
            tree=copy.deepcopy(source)
            apply(tree,index)
            focus=tree.find('.//control[@id="600"]/focusedlayout/control[@type="image"]/texture')
            self.assertEqual(focus.get('colordiffuse'),palette[5])

    def test_home_continue_watching_options_match_kind_and_watched_state(self):
        series=[x['label'] for x in continue_options('series',False)]
        self.assertEqual(series,['Watch from Beginning','Go to Episode','Go to Series',
                                 'Mark as Watched','Remove from Continue Watching','More Info'])
        movie=[x['label'] for x in continue_options('movie',True)]
        self.assertEqual(movie,['Watch from Beginning','Mark as Unwatched',
                                'Remove from Continue Watching','More Info'])
        text=(ROOT/'lib/nimbus.py').read_text()
        self.assertIn("if aid == 117 and self.home_media_context_menu():",text)
        self.assertIn("continue_options(row.get('type'), watched)",text)

    def test_single_episode_action_changes_only_selected_episode(self):
        from episode_actions import apply_single
        item,_=apply_through([],meta(),'show:2:6',True,NOW)
        changed,selected=apply_single([item],meta(),'show:2:3',False,NOW)
        marked=watched_ids(videos(),changed)
        self.assertEqual(selected,{'show:2:3'})
        self.assertNotIn('show:2:3',marked)
        self.assertIn('show:2:2',marked)
        self.assertIn('show:2:4',marked)


if __name__=='__main__':
    unittest.main()
