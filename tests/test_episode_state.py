import base64
import unittest
import zlib
from lib.episode_state import watched_ids


class EpisodeStateTests(unittest.TestCase):
    def setUp(self):
        self.videos = [dict(id=f'series:1:{i}', season=1, episode=i) for i in range(1, 5)]

    def saved(self, anchor='series:1:3', length=3, bits=5):
        packed = base64.b64encode(zlib.compress(bytes([bits]))).decode()
        return {'state': {'watched': f'{anchor}:{length}:{packed}'}}

    def test_nonconsecutive_history_does_not_mark_skipped_episode(self):
        self.assertEqual(watched_ids(self.videos, self.saved()), {'series:1:1', 'series:1:3'})

    def test_inserted_specials_preserve_episode_identity(self):
        videos = [dict(id='special', season=0, episode=1)] + self.videos
        self.assertEqual(watched_ids(videos, self.saved()), {'series:1:1', 'series:1:3'})

    def test_missing_anchor_and_invalid_history_are_not_guessed(self):
        for saved in (self.saved('removed'), {'state': {'watched': 'broken'}}, {}, self.saved(length=-1)):
            self.assertEqual(watched_ids(self.videos, saved), set())

    def test_order_is_independent_of_provider_response_order(self):
        self.assertEqual(watched_ids(list(reversed(self.videos)), self.saved()), {'series:1:1', 'series:1:3'})
