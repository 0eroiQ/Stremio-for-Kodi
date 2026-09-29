"""Authentication gating and link lifecycle, without using a real account."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import types
import threading

ROOT = Path(__file__).resolve().parents[1]


class SigninTests(unittest.TestCase):
    def test_setup_completion_is_not_login(self):
        tree = ast.parse((ROOT/'lib/signin.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'signed_in')
        store = Mock()
        scope = {'account_store': lambda: store}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<signin>', 'exec'), scope)
        for state in ({}, {'welcome_done': True}, {'token': ''}, {'token': ' '}, {'token': False}):
            store.load.return_value = state
            self.assertFalse(scope['signed_in']())
        store.load.return_value = {'token': 'test-only'}
        self.assertTrue(scope['signed_in']())

    def test_cancelled_login_does_not_open_home(self):
        tree = ast.parse((ROOT/'lib/app.py').read_text())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        module = types.ModuleType('lib.signin')
        module.signed_in = Mock(return_value=False)
        module.show_signin = Mock(return_value=False)
        home = Mock()
        session = Mock()
        session.getProperty.return_value = ''
        kodi_gui = Mock()
        kodi_gui.Window.return_value = session
        scope = {
            'HomeWindow': home, 'ADDON_PATH': '/test', 'SKIN': 'Main', 'RES': '1080i',
            'xbmcgui': kodi_gui, 'SESSION_WINDOW_ID': 10000,
            'APP_RUNNING': 'stremioforkodi.running'
        }
        exec(compile(ast.Module(body=[run], type_ignores=[]), '<app>', 'exec'), scope)
        guard = Mock()
        guard.acquire.return_value = True
        with patch.dict('sys.modules', {'lib.signin': module}), patch('lib.launch_guard.LaunchGuard', return_value=guard):
            scope['run']()
            home.assert_not_called()
            guard.acquire.assert_called_once_with()
            guard.release.assert_called_once_with()


    def test_confirmed_link_saves_token_and_opens_home(self):
        tree = ast.parse((ROOT/'lib/signin.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'link_account')
        store = Mock()
        store.load.return_value = {}
        window = Mock()
        window.cancel = threading.Event()
        window.refresh = threading.Event()
        window.authenticated = False
        scope = {'create_link_details': lambda: ('test', 'https://link.stremio.com/test', ''),
                 'read_link': lambda code: 'test-only-token', 'account_store': lambda: store,
                 'pull_addons': lambda token: ([], 0), 'merge_account': lambda state, addons: addons,
                 'pull_library': lambda token: [], 'time': __import__('time'),
                 'xbmc': Mock(), 'threading': threading}
        scope['xbmc'].Monitor.return_value.abortRequested.return_value = False
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<link>', 'exec'), scope)
        scope['link_account'](window)
        self.assertTrue(window.authenticated)
        self.assertEqual(store.save.call_args.args[0]['token'], 'test-only-token')
        window.close.assert_called_once()

    def test_transient_link_poll_failure_retries_instead_of_aborting_signin(self):
        tree = ast.parse((ROOT/'lib/signin.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'link_account')
        class AccountError(Exception):
            pass
        calls = {'count': 0}
        def flaky(code):
            calls['count'] += 1
            if calls['count'] == 1:
                raise AccountError('temporary')
            return 'test-only-token'
        class FastTime:
            value = 0
            @classmethod
            def monotonic(cls):
                cls.value += 20
                return cls.value
        store = Mock()
        store.load.return_value = {}
        window = Mock()
        window.cancel = threading.Event()
        window.refresh = threading.Event()
        window.authenticated = False
        scope = {
            'create_link_details': lambda: ('test', 'https://link.stremio.com/test', ''),
            'read_link': flaky, 'AccountError': AccountError,
            'account_store': lambda: store, 'pull_addons': lambda token: ([], 0),
            'merge_account': lambda state, addons: addons, 'pull_library': lambda token: [],
            'time': FastTime, 'xbmc': Mock(), 'threading': threading,
            'AccountStorageError': type('AccountStorageError', (Exception,), {}),
        }
        scope['xbmc'].Monitor.return_value.abortRequested.return_value = False
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<link>', 'exec'), scope)
        scope['link_account'](window)
        self.assertEqual(calls['count'], 2)
        self.assertTrue(window.authenticated)
        self.assertEqual(store.save.call_args.args[0]['token'], 'test-only-token')
        window.close.assert_called_once()

    def test_pending_link_does_not_save_login(self):
        tree = ast.parse((ROOT/'lib/signin.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'link_account')
        store = Mock()
        window = Mock()
        window.cancel = threading.Event()
        window.refresh = threading.Event()
        def pending(code):
            window.cancel.set()
            return None
        scope = {'create_link_details': lambda: ('test', 'https://link.stremio.com/test', ''),
                 'read_link': pending, 'account_store': lambda: store, 'time': __import__('time'),
                 'xbmc': Mock(), 'threading': threading}
        scope['xbmc'].Monitor.return_value.abortRequested.return_value = False
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<link>', 'exec'), scope)
        scope['link_account'](window)
        store.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
