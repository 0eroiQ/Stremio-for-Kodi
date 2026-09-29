import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'core'))

from media_actions import apply_movie_watched, apply_remove_continue


class MediaContextActionsTests(unittest.TestCase):
    def movie(self):
        return {'_id':'ttm','id':'ttm','type':'movie','name':'Movie',
                'removed':False,'temp':False,
                'state':{'timeOffset':420000,'timeWatched':420000,
                         'duration':600000,'flaggedWatched':0,'timesWatched':0}}

    def test_mark_movie_watched_removes_resume_and_sets_flag(self):
        item=apply_movie_watched([self.movie()],self.movie(),True)
        self.assertEqual(item['state']['timeOffset'],0)
        self.assertEqual(item['state']['flaggedWatched'],1)
        self.assertGreaterEqual(item['state']['timesWatched'],1)

    def test_mark_movie_unwatched_clears_flag(self):
        row=self.movie(); row['state']['flaggedWatched']=1; row['state']['timesWatched']=1
        item=apply_movie_watched([row],row,False)
        self.assertEqual(item['state']['flaggedWatched'],0)
        self.assertEqual(item['state']['timesWatched'],0)

    def test_remove_continue_preserves_watched_state_but_clears_progress(self):
        row=self.movie(); row['state']['flaggedWatched']=1
        item=apply_remove_continue([row],row)
        self.assertEqual(item['state']['timeOffset'],0)
        self.assertEqual(item['state']['timeWatched'],0)
        self.assertEqual(item['state']['flaggedWatched'],1)

    def test_action_menu_icons_exist(self):
        names=('play','restart','watched','unwatched','through-watch',
               'through-unwatch','info','episode','series','remove')
        base=ROOT/'resources/skins/Main/media/action-menu'
        for name in names:
            self.assertTrue((base/(name+'.png')).is_file(),name)


if __name__=='__main__':
    unittest.main()
