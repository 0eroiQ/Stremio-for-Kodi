import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'core'
if str(CORE) not in sys.path:sys.path.insert(0,str(CORE))

class DummyPlayer:
    pass
class DummyDialog:
    def __init__(self,*a,**k): pass


def load_module():
    old={k:sys.modules.get(k) for k in ('xbmc','xbmcgui','lib.theme')}
    xbmc=types.ModuleType('xbmc');xbmc.Player=DummyPlayer
    xbmcgui=types.ModuleType('xbmcgui');xbmcgui.WindowXMLDialog=DummyDialog
    theme=types.ModuleType('lib.theme');theme.window=lambda *a,**k:None
    sys.modules['xbmc']=xbmc;sys.modules['xbmcgui']=xbmcgui;sys.modules['lib.theme']=theme
    try:
        spec=importlib.util.spec_from_file_location('skip_segments_test',ROOT/'lib/skip_segments.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    finally:
        for k,v in old.items():
            if v is None:sys.modules.pop(k,None)
            else:sys.modules[k]=v

class Response:
    def __init__(self,payload):self.body=io.BytesIO(json.dumps(payload).encode())
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,n=-1):return self.body.read(n)
class Opener:
    def __init__(self,payload):self.payload=payload;self.requests=[]
    def open(self,request,timeout=None):self.requests.append((request,timeout));return Response(self.payload)

class SkipSegmentTests(unittest.TestCase):
    def test_series_identity(self):
        m=load_module();self.assertEqual(m._identity('series','tt0903747:1:3'),{'imdb_id':'tt0903747','season':1,'episode':3})
    def test_movie_identity(self):
        m=load_module();self.assertEqual(m._identity('movie','tt0371746'),{'imdb_id':'tt0371746','is_movie':'true'})
    def test_fetches_segments_and_uses_cache(self):
        m=load_module();payload={'intro':{'start_sec':2,'end_sec':58,'confidence':1},'recap':None,'outro':{'start_sec':1300,'end_sec':1360,'confidence':.9},'post_credits':None};opener=Opener(payload)
        with tempfile.TemporaryDirectory() as d:
            first=m.fetch_segments(Path(d),'series','tt0903747:1:1',opener=opener,now=1000)
            second=m.fetch_segments(Path(d),'series','tt0903747:1:1',opener=opener,now=1001)
        self.assertEqual([x['type'] for x in first],['intro','outro']);self.assertEqual(second,first);self.assertEqual(len(opener.requests),1);self.assertIn('/segments?',opener.requests[0][0].full_url);self.assertEqual(opener.requests[0][1],m.TIMEOUT_SECONDS)
    def test_invalid_segments_are_dropped(self):
        m=load_module();self.assertIsNone(m._clean_segment('intro',{'start_sec':60,'end_sec':10}))

if __name__=='__main__':unittest.main()
