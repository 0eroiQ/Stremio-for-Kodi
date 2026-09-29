"""Regression tests for hidden UI, stale launch flags and cold boot imports."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock
from lib.launch_guard import LaunchGuard, mark_window, OWNER, ROLE, RUNNING, TOKEN

class Window:
    def __init__(self):
        self.props = {}
        self.controls = {}
    def getProperty(self, key): return self.props.get(key, '')
    def setProperty(self, key, value): self.props[key] = value
    def clearProperty(self, key): self.props.pop(key, None)
    def getControl(self, key):
        if key not in self.controls: raise RuntimeError('Missing control')
        return self.controls[key]

class GUI:
    def __init__(self):
        self.windows = {10000: Window()}
        self.dialog = Mock()
    def Window(self, wid=None):
        if wid is None:
            wid = next(v for v in range(13000, 13200) if v not in self.windows)
            self.windows[wid] = Window()
        if wid not in self.windows: raise ValueError('Missing window')
        return self.windows[wid]
    def Dialog(self): return self.dialog

class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.gui = GUI()
        self.kodi = Mock()
        self.kodi.getCondVisibility.return_value = False
        self.session = self.gui.Window(10000)
    def guard(self): return LaunchGuard(self.gui, self.kodi)
    def view(self, wid, role):
        win = self.gui.windows[wid] = Window()
        mark_window(win, role)
        return win
    def test_fresh_session_does_not_probe_python_window_range(self):
        calls = []
        original = self.gui.Window
        def tracked(wid=None):
            calls.append(wid)
            return original(wid)
        self.gui.Window = tracked
        guard = self.guard()
        guard.injected_gui = False
        self.assertTrue(guard.acquire())
        self.assertFalse(any(isinstance(wid, int) and 13000 <= wid < 13200 for wid in calls))
        guard.release()

    def test_stale_flag_does_not_block_start(self):
        self.session.setProperty(RUNNING, 'true')
        guard = self.guard()
        self.assertTrue(guard.acquire())
        self.assertEqual(guard.lease.getProperty(ROLE), 'lease')
        guard.release()
        self.assertEqual(self.session.getProperty(RUNNING), '')
    def test_hidden_legacy_home_resumes_instead_of_duplicate(self):
        self.session.setProperty(RUNNING, 'true')
        win = self.gui.windows[13000] = Window()
        win.props.update(page='Home', first_row='400')
        win.controls[9000] = object()
        self.assertFalse(self.guard().acquire())
        self.kodi.executebuiltin.assert_called_once_with('ActivateWindow(13000)')
        self.assertEqual(len(self.gui.windows), 2)
    def test_hidden_details_take_precedence_over_home(self):
        self.view(13000, 'home')
        self.view(13002, 'info')
        self.assertFalse(self.guard().acquire())
        self.kodi.executebuiltin.assert_called_once_with('ActivateWindow(13002)')
    def test_visible_window_is_not_navigated_away(self):
        self.view(13000, 'home')
        self.kodi.getCondVisibility.return_value = True
        self.assertFalse(self.guard().acquire())
        self.kodi.executebuiltin.assert_not_called()
    def test_loading_lease_blocks_duplicate_and_can_be_released(self):
        first = self.guard()
        self.assertTrue(first.acquire())
        self.assertFalse(self.guard().acquire())
        self.gui.dialog.notification.assert_called_once()
        first.release()
        next_guard = self.guard()
        self.assertTrue(next_guard.acquire())
        next_guard.release()
    def test_foreign_window_is_not_reopened(self):
        self.gui.windows[13000] = Window()
        self.gui.windows[13000].props['page'] = 'Home'
        guard = self.guard()
        self.assertTrue(guard.acquire())
        self.kodi.executebuiltin.assert_not_called()
        guard.release()
    def test_old_owner_cannot_clear_new_owners_guard(self):
        guard = self.guard()
        self.assertTrue(guard.acquire())
        self.session.setProperty(TOKEN, 'new-owner')
        guard.release()
        self.assertEqual(self.session.getProperty(TOKEN), 'new-owner')
        self.assertEqual(self.session.getProperty(RUNNING), 'true')
    def test_missing_legacy_controls_do_not_crash_launch(self):
        self.session.setProperty(RUNNING, 'true')
        win = self.gui.windows[13000] = Window()
        win.props.update(page='Home', first_row='400')
        guard = self.guard()
        self.assertTrue(guard.acquire())
        guard.release()
    def test_cold_entrypoint_adds_core_import_path(self):
        root = Path(__file__).resolve().parents[1]
        code = ('import runpy,sys,importlib.util; '
                'runpy.run_path(sys.argv[1],run_name="bootstrap-test"); '
                's=importlib.util.find_spec("addon_state"); '
                'assert s and s.origin.endswith("/core/addon_state.py"), s')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(root/'default.py')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == '__main__':
    unittest.main()
