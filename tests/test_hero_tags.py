import unittest
from lib.hero_tags import tags
class HeroTagTests(unittest.TestCase):
    def test_provider_fields_and_runtime(self):
        result=tags({'released':'2024-05-15T00:00:00Z','runtime':'91 min','genres':['Horror','Thriller'],'certification':'R'})
        self.assertEqual(result,{'premiered':'15/05/2024','runtime_tag':'1 HR 31 MINS','genre_tag':'Horror Thriller','certificate':'R'})
    def test_missing_data_not_invented(self):
        self.assertEqual(tags({}),dict.fromkeys(['premiered','certificate','genre_tag','runtime_tag'],''))

    def test_invalid_and_year_only_dates(self):
        for value in ('2024-02-30', '2024', '2020–2024'):
            self.assertEqual(tags({'releaseInfo':value})['premiered'], value)
