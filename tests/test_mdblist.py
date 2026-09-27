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
    def test_multiple_selected_ratings(self):
        from lib.mdblist import selected_text
        settings={'rating_imdb':'true','rating_tmdb':'true','rating_trakt':'false'}
        data={'ratings':[{'source':'imdb','value':8},{'source':'tmdb','value':80},{'source':'trakt','value':90}]}
        self.assertEqual(selected_text(data,lambda key: settings.get(key,'')), 'IMDb 8  ·  TMDb 80')
        self.assertEqual(selected_text(data,lambda key:'false'),'')
