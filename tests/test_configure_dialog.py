"""Dialog buttons, cancellation, temporary QR cleanup and failure recovery."""
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from test_addon_config import entry
ROOT=Path(__file__).resolve().parents[1]


class FakeWindow:
    def __init__(self,*args,**kwargs):
        self.props={}; self.controls={}; self.focus=None; self.closed=False
    def setProperty(self,key,value): self.props[key]=value
    def clearProperty(self,key): self.props.pop(key,None)
    def getProperty(self,key): return self.props.get(key,'')
    def getControl(self,key): return self.controls.setdefault(key,Mock())
    def setFocusId(self,key): self.focus=key
    def close(self): self.closed=True


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.api=Mock(); self.api.CORE.getAddonInfo.return_value=self.temp.name
        self.modules=patch.dict('sys.modules',{'xbmcgui':types.SimpleNamespace(WindowXMLDialog=FakeWindow),
            'xbmcvfs':types.SimpleNamespace(translatePath=lambda p:p),
            'addons_ui':types.SimpleNamespace(plain=lambda v,n:str(v)[:n]),'lib.backend':self.api})
        self.modules.start();self.addCleanup(self.modules.stop)
        import lib
        self.attr=patch.object(lib,'backend',self.api,create=True)
        self.attr.start();self.addCleanup(self.attr.stop)
        spec=importlib.util.spec_from_file_location('cfg_dialog_test',ROOT/'lib/addon_config_dialog.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.window=self.module.ConfigureWindow(entry=entry())
        self.addCleanup(self.window.dispose)

    def test_open_generates_private_qr_without_sync_and_back_removes_it(self):
        w=self.window
        with patch.object(self.module,'sync_addons') as sync:
            w.onInit(); self.assertEqual(w.getProperty('config_has_qr'),'true')
            paths=list(w._qr_paths);self.assertTrue(all(p.exists() for p in paths))
            w.getControl(101).setImage.assert_called_with(str(paths[-1]),False)
            self.assertNotIn('/old/',w.getProperty('config_site'))
            w.onClick(1); sync.assert_not_called()
            self.assertTrue(w.closed);self.assertTrue(all(not p.exists() for p in paths))

    def test_refresh_changes_qr_path_and_retains_at_most_two_files(self):
        w=self.window;w.onInit();first=w._qr_paths[-1]
        for i in range(4):w.onClick(2)
        self.assertEqual(len(w._qr_paths),2);self.assertFalse(first.exists())
        self.assertEqual(w.getProperty('config_has_qr'),'true')

    def test_sync_keeps_dialog_open_and_done_syncs_then_closes(self):
        w=self.window;w.onInit()
        result={'changed':True,'entry':entry(),'count':1,'account_count':1}
        with patch.object(self.module,'sync_addons',return_value=result) as sync:
            w.onClick(3);w._worker.join(3)
            self.assertFalse(w.closed);self.assertTrue(w.changed)
            self.assertFalse(w.getProperty('config_busy'))
            w.onClick(4);w._worker.join(3)
            self.assertTrue(w.closed);self.assertEqual(sync.call_count,2)
            self.assertFalse(w._qr_paths)

    def test_sync_failure_is_safe_and_does_not_close(self):
        w=self.window;w.onInit()
        with patch.object(self.module,'sync_addons',side_effect=OSError('private-token')):
            w.onClick(4);w._worker.join(3)
        self.assertFalse(w.closed);self.assertFalse(w.getProperty('config_busy'))
        self.assertNotIn('private-token',w.getProperty('config_status'))
        self.assertEqual(w.focus,3)

    def test_late_sync_reply_cannot_reopen_or_change_closed_dialog(self):
        import threading
        started,release=threading.Event(),threading.Event()
        def blocked(*args,**kwargs):
            started.set();release.wait(2)
            return {'changed':True,'entry':entry(),'account_count':1}
        w=self.window;w.onInit()
        with patch.object(self.module,'sync_addons',side_effect=blocked) as sync:
            w.onClick(3);self.assertTrue(started.wait(1));w.onClick(4)
            w.onClick(1);release.set();w._worker.join(3)
            self.assertTrue(w.closed);self.assertFalse(w.changed)
            self.assertEqual(sync.call_count,1);self.assertFalse(w._qr_paths)

if __name__=='__main__':unittest.main()
