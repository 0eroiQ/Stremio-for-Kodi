import sys,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'core'
class PlaybackSettingsImportTests(unittest.TestCase):
 def test_apply_can_resolve_core_addon_state_without_program_entry_bootstrap(self):
  old=list(sys.path);sys.path[:]=[p for p in sys.path if p!=str(CORE)]
  sys.modules['xbmc']=types.SimpleNamespace(executebuiltin=lambda *_:None)
  sys.modules['xbmcvfs']=types.SimpleNamespace(translatePath=lambda p:'/tmp')
  fake=types.ModuleType('core.addon_state');fake.get_addon=lambda:types.SimpleNamespace(getSetting=lambda _:'false');sys.modules['core.addon_state']=fake
  try:
   import lib.playback_settings as mod
   mod.apply()
  finally:
   sys.path[:]=old;sys.modules.pop('core.addon_state',None)
