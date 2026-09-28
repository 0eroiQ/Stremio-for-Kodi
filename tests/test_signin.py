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
        scope = {'HomeWindow': home, 'ADDON_PATH': '/test', 'SKIN': 'Main', 'RES': '1080i'}
        exec(compile(ast.Module(body=[run], type_ignores=[]), '<app>', 'exec'), scope)
        with patch.dict('sys.modules', {'lib.signin': module}):
            scope['run']()
            home.assert_not_called()

    def test_confirmed_link_saves_token_uid_and_opens_home(self):
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
                 'pull_user_id': lambda token: 'stremio-user-id',
                 'pull_addons': lambda token: ([], 0), 'merge_account': lambda state, addons: addons,
                 'pull_library': lambda token: [], 'time': __import__('time'),
                 'xbmc': Mock(), 'threading': threading}
        scope['xbmc'].Monitor.return_value.abortRequested.return_value = False
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<link>', 'exec'), scope)
        scope['link_account'](window)
        self.assertTrue(window.authenticated)
        saved_states = [call.args[0] for call in store.save.call_args_list]
        self.assertTrue(any(state.get('token') == 'test-only-token' for state in saved_states))
        self.assertTrue(any(state.get('uid') == 'stremio-user-id' for state in saved_states))
        window.close.assert_called_once()

    def test_uid_failure_does_not_cancel_confirmed_login(self):
        tree = ast.parse((ROOT/'lib/signin.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'link_account')
        store = Mock()
        store.load.return_value = {}
        window = Mock()
        window.cancel = threading.Event()
        window.refresh = threading.Event()
        window.authenticated = False
        def uid_failure(token):
            raise RuntimeError('test-only')
        scope = {'create_link_details': lambda: ('test', 'https://link.stremio.com/test', ''),
                 'read_link': lambda code: 'test-only-token', 'account_store': lambda: store,
                 'pull_user_id': uid_failure,
                 'pull_addons': lambda token: ([], 0), 'merge_account': lambda state, addons: addons,
                 'pull_library': lambda token: [], 'time': __import__('time'),
                 'xbmc': Mock(), 'threading': threading}
        scope['xbmc'].Monitor.return_value.abortRequested.return_value = False
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<link>', 'exec'), scope)
        scope['link_account'](window)
        self.assertTrue(window.authenticated)
        self.assertTrue(any(call.args[0].get('token') == 'test-only-token' for call in store.save.call_args_list))
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
