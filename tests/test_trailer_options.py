import unittest
from lib.trailer_options import imdb_id, playback_url, choose_trailer, choose_stream, resolve

class TrailerOptionsTests(unittest.TestCase):
    def test_route_is_internal_and_validates_identity(self):
        self.assertEqual(imdb_id({'id':'tt1234:2:1'}),'tt1234')
        self.assertTrue(playback_url('tt1234',2).startswith('plugin://script.stremioelec/'))
        self.assertEqual(playback_url('https://example.com'),'')

    def test_selected_season_wins_over_newer_season(self):
        nodes=[{'id':'vi1','name':{'value':'Official Season 3 Trailer'}},
               {'id':'vi2','name':{'value':'Season 1 Trailer'}}]
        self.assertEqual(choose_trailer(nodes,1)['id'],'vi2')

    def test_quality_and_native_hls_fallback(self):
        streams=[{'url':'https://example.com/'+q,'videoMimeType':'MP4','videoDefinition':q}
                 for q in ('DEF_1080p','DEF_720p','DEF_SD')]
        self.assertEqual(choose_stream(streams,'1')['videoDefinition'],'DEF_720p')
        self.assertEqual(choose_stream([{'url':'http://example.com','videoMimeType':'MP4'}]),None)
        hls={'url':'https://example.com/a.m3u8','videoMimeType':'M3U8'}
        self.assertEqual(choose_stream([hls]),hls)

    def test_discovery_resolves_video_without_external_provider(self):
        calls=[]
        def request(query, variables):
            calls.append(variables)
            if 'title(' in query:
                return {'title':{'latestTrailer':{'id':'vi2','name':{'value':'Trailer'}}}}
            return {'video':{'playbackURLs':[{'url':'https://example.com/a.mp4','videoMimeType':'MP4','videoDefinition':'DEF_720p'}]}}
        self.assertEqual(resolve('tt1',request=request)['mime'],'video/mp4')
        self.assertEqual(calls,[{'id':'tt1'},{'id':'vi2'}])
        self.assertIsNone(resolve('tt1',request=lambda q,v:{}))
