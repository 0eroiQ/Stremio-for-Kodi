import unittest
from lib.mdblist import rating_text

class RatingTests(unittest.TestCase):
    def test_selected_source_and_zero(self):
        data={'ratings':[{'source':'imdb','value':7.2},{'source':'tomatoes','value':0}]}
        self.assertEqual(rating_text(data,0),'IMDb 7.2')
        self.assertEqual(rating_text(data,3),'Rotten Tomatoes 0')
        self.assertEqual(rating_text(data,4),'')
    def test_missing_rating_keeps_fallback(self):
        self.assertEqual(rating_text({'ratings':[{'source':'imdb','value':None}]},0),'')
