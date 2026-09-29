import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'core'))

from continue_playback import continue_series_target
from core.playback_progress import _encode_watched

NOW=datetime(2026,9,29,12,0,0,tzinfo=timezone.utc)


def videos(next_release='2026-09-20T00:00:00Z'):
    return [
        {'id':'ttx:1:1','season':1,'episode':1,'released':'2026-09-01T00:00:00Z'},
        {'id':'ttx:1:2','season':1,'episode':2,'released':next_release},
    ]


def saved(video_id, offset, watched=()):
    rows=videos()
    ids=[row['id'] for row in rows]
    bits=[identity in watched for identity in ids]
    return {'_id':'ttx','type':'series','state':{
        'video_id':video_id,'timeOffset':offset,
        'watched':_encode_watched(bits,ids) if watched else None}}


class ContinueWatchingAirdateTests(unittest.TestCase):
    def test_partial_episode_stays_visible(self):
        row,offset=continue_series_target(videos(),saved('ttx:1:1',120000),NOW)
        self.assertEqual(row['id'],'ttx:1:1')
        self.assertEqual(offset,120000)

    def test_watched_episode_advances_only_to_aired_next(self):
        row,offset=continue_series_target(
            videos(),saved('ttx:1:1',0,{'ttx:1:1'}),NOW)
        self.assertEqual(row['id'],'ttx:1:2')
        self.assertEqual(offset,0)

    def test_flagged_watched_is_authoritative_when_bitmap_lags(self):
        state=saved('ttx:1:1',90000)
        state['state']['flaggedWatched']=1
        row,offset=continue_series_target(videos(),state,NOW)
        self.assertEqual(row['id'],'ttx:1:2')
        self.assertEqual(offset,0)

    def test_watched_episode_hides_when_next_is_future(self):
        rows=videos('2026-10-10T00:00:00Z')
        ids=[r['id'] for r in rows]
        state={'_id':'ttx','type':'series','state':{
            'video_id':'ttx:1:1','timeOffset':0,
            'watched':_encode_watched([True,False],ids)}}
        row,offset=continue_series_target(rows,state,NOW)
        self.assertIsNone(row); self.assertEqual(offset,0)

    def test_final_watched_episode_hides_series(self):
        rows=videos(); ids=[r['id'] for r in rows]
        state={'_id':'ttx','type':'series','state':{
            'video_id':'ttx:1:2','timeOffset':0,
            'watched':_encode_watched([True,True],ids)}}
        row,offset=continue_series_target(rows,state,NOW)
        self.assertIsNone(row); self.assertEqual(offset,0)

    def test_next_episode_sentinel_requires_aired_date(self):
        aired=saved('ttx:1:2',1)
        row,_=continue_series_target(videos(),aired,NOW)
        self.assertEqual(row['id'],'ttx:1:2')
        future_rows=videos('2026-10-10T00:00:00Z')
        row,_=continue_series_target(future_rows,aired,NOW)
        self.assertIsNone(row)

    def test_unknown_next_release_is_not_assumed_aired(self):
        rows=videos(); rows[1].pop('released')
        ids=[r['id'] for r in rows]
        state={'_id':'ttx','type':'series','state':{
            'video_id':'ttx:1:1','timeOffset':0,
            'watched':_encode_watched([True,False],ids)}}
        row,_=continue_series_target(rows,state,NOW)
        self.assertIsNone(row)


class MovieContinueWatchingTests(unittest.TestCase):
    def _movie(self, offset, duration, flagged=0, times=0):
        return {'_id':'ttmovie','type':'movie','removed':False,'temp':False,
                'state':{'timeOffset':offset,'duration':duration,
                         'flaggedWatched':flagged,'timesWatched':times,
                         'lastWatched':'2026-09-29T12:00:00Z'}}

    def test_movie_below_credits_threshold_stays(self):
        from account import library_rows
        movie=self._movie(3000000,6000000)
        self.assertEqual(library_rows([movie],True),[movie])

    def test_movie_at_credits_threshold_is_removed(self):
        from account import library_rows
        movie=self._movie(5400000,6000000)
        self.assertEqual(library_rows([movie],True),[])

    def test_movie_above_credits_threshold_is_removed_even_if_flag_lags(self):
        from account import library_rows
        movie=self._movie(5940000,6000000,flagged=0,times=2)
        self.assertEqual(library_rows([movie],True),[])

    def test_partial_rewatch_survives_old_watched_flag(self):
        from account import library_rows
        movie=self._movie(120000,7500000,flagged=1,times=1)
        self.assertEqual(library_rows([movie],True),[movie])


if __name__=='__main__':
    unittest.main()
