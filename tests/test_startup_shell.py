"""Startup-shell and top-level exit behavior regressions."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def function_from_file(path, name, class_name=None):
    tree = ast.parse(path.read_text())
    body = tree.body
    if class_name:
        cls = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name)
        body = cls.body
    return next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == name)


class StartupShellTests(unittest.TestCase):
    def test_service_launches_once_when_enabled(self):
        configured_delay = function_from_file(ROOT / "service.py", "configured_delay")
        maybe_autostart = function_from_file(ROOT / "service.py", "maybe_autostart")
        addon = Mock()
        addon.getSetting.side_effect = lambda key: {
            "startup_autostart": "true", "startup_delay": "0"}.get(key, "")
        session = Mock(); session.getProperty.return_value = ""
        monitor = Mock(); monitor.abortRequested.return_value = False
        xbmc = Mock(); xbmcgui = Mock(); xbmcgui.Window.return_value = session
        scope = {"ADDON":addon,"SESSION_WINDOW_ID":10000,
                 "STARTUP_LAUNCHED":"stremioforkodi.startup.launched",
                 "APP_RUNNING":"stremioforkodi.running","DELAYS":(0,1,2,3,5),
                 "xbmc":xbmc,"xbmcgui":xbmcgui}
        exec(compile(ast.Module(body=[configured_delay, maybe_autostart],type_ignores=[]),
                     "<service>","exec"),scope)
        scope["maybe_autostart"](monitor)
        session.setProperty.assert_called_once_with("stremioforkodi.startup.launched","true")
        xbmc.executebuiltin.assert_called_once_with("RunScript(script.stremioelec,startup)")

    def test_service_does_not_autostart_when_disabled(self):
        maybe_autostart = function_from_file(ROOT / "service.py", "maybe_autostart")
        addon=Mock(); addon.getSetting.return_value="false"
        xbmc=Mock(); xbmcgui=Mock(); monitor=Mock()
        scope={"ADDON":addon,"SESSION_WINDOW_ID":10000,
               "STARTUP_LAUNCHED":"stremioforkodi.startup.launched",
               "APP_RUNNING":"stremioforkodi.running","configured_delay":lambda:0,
               "xbmc":xbmc,"xbmcgui":xbmcgui}
        exec(compile(ast.Module(body=[maybe_autostart],type_ignores=[]),"<service>","exec"),scope)
        scope["maybe_autostart"](monitor)
        xbmcgui.Window.assert_not_called()
        xbmc.executebuiltin.assert_not_called()

    def home_action(self, accepted=False):
        on_action = function_from_file(ROOT / "lib/nimbus.py", "onAction", "HomeWindow")
        exit_guard = Mock()
        self.exit_guard = exit_guard
        override = patch("lib.launch_guard.defer_relaunch", exit_guard)
        override.start(); self.addCleanup(override.stop)
        dialog = Mock()
        dialog.yesno.return_value = accepted
        gui = Mock()
        gui.Dialog.return_value = dialog
        gui.getCurrentWindowId.return_value = 13002
        window = Mock()
        window.exit_armed = False
        window.exit_requested = False
        window.rows = {}
        window.getProperty.return_value = "Home"
        window.getFocusId.return_value = 9000
        action = Mock()
        action.getId.return_value = 92
        scope = {"BACK": (10, 92, 216, 247), "xbmcgui": gui,
                 "home_index": lambda: 1}
        exec(compile(ast.Module(body=[on_action], type_ignores=[]), "<home>", "exec"), scope)
        return window, dialog, action, scope["onAction"]

    def test_first_back_returns_to_sidebar_before_confirmation(self):
        window, dialog, action, on_action = self.home_action()
        on_action(window, action)
        self.assertIs(window.exit_armed, True)
        window.cancel_trailer.assert_called_once_with()
        window.setFocusId.assert_called_once_with(9000)
        window.getControl.return_value.selectItem.assert_called_once_with(1)
        dialog.yesno.assert_not_called()
        window.close.assert_not_called()

    def test_back_cancel_keeps_home_open_and_allows_later_exit(self):
        window, dialog, action, on_action = self.home_action()
        on_action(window, action)
        on_action(window, action)
        self.assertIs(window.exit_armed, False)
        self.assertIs(window.exit_requested, False)
        self.exit_guard.assert_not_called()
        dialog.yesno.assert_called_once_with(
            "Exit Stremio for Kodi", "Do you want to exit Stremio for Kodi?",
            nolabel="Cancel", yeslabel="Exit")
        window.close.assert_not_called()
        dialog.yesno.return_value = True
        on_action(window, action)
        window.close.assert_not_called()
        on_action(window, action)
        window.close.assert_called_once_with()
        self.exit_guard.assert_called_once_with()

    def test_second_back_exit_closes_home(self):
        window, dialog, action, on_action = self.home_action(accepted=True)
        on_action(window, action)
        window.close.assert_not_called()
        on_action(window, action)
        window.close.assert_called_once_with()
        self.assertIs(window.exit_armed, False)
        self.assertIs(window.exit_requested, True)

    def test_navigation_disarms_back_confirmation(self):
        window, dialog, action, on_action = self.home_action(accepted=True)
        on_action(window, action)
        action.getId.return_value = 1
        on_action(window, action)
        self.assertIs(window.exit_armed, False)
        action.getId.return_value = 92
        on_action(window, action)
        dialog.yesno.assert_not_called()
        window.close.assert_not_called()

    def test_confirmed_exit_ends_modal_loop_instead_of_reopening_home(self):
        import sys
        from types import ModuleType
        from unittest.mock import patch
        run = function_from_file(ROOT / "lib/app.py", "run")
        launch = ModuleType("lib.launch_guard")
        guard = Mock()
        guard.acquire.return_value = True
        launch.defer_relaunch = self.exit_guard if hasattr(self, "exit_guard") else Mock()
        launch.LaunchGuard = Mock(return_value=guard)
        launch.mark_window = Mock()
        launch.unmark_window = Mock()
        signin = ModuleType("lib.signin")
        signin.signed_in = Mock(return_value=True)
        signin.show_signin = Mock()
        vfs = ModuleType("xbmcvfs")
        vfs.translatePath = lambda value: value
        backend = ModuleType("lib.backend")
        backend.account_home = Mock(return_value=[])
        backend.account_home_capacity = Mock(return_value=8)
        layout = ModuleType("lib.home_layout")
        layout.build_layout = Mock(return_value=("home.xml", "/tmp", 8))
        appearance = ModuleType("lib.appearance")
        appearance.options = Mock(return_value={})
        window, dialog, action, on_action = self.home_action(accepted=True)
        window.reload_appearance = False
        window.close.side_effect = lambda: launch.defer_relaunch.assert_called_once_with()
        window.doModal.side_effect = lambda: (on_action(window, action), on_action(window, action))
        factory = Mock(return_value=window)
        gui = Mock(); gui.getCurrentWindowId.return_value = 10025
        scope = {"xbmcgui": gui, "HomeWindow": factory, "ADDON": Mock(),
                 "ADDON_PATH": "/addon", "SKIN": "Main", "RES": "1080i"}
        exec(compile(ast.Module(body=[run], type_ignores=[]), "<app>", "exec"), scope)
        kodi = Mock()
        kodi.getCondVisibility.return_value = False
        kodi.executebuiltin.side_effect = lambda *args: guard.release.assert_not_called()
        modules = {"xbmc": kodi, "lib.launch_guard": launch, "lib.signin": signin,
                   "xbmcvfs": vfs, "lib.backend": backend,
                   "lib.home_layout": layout, "lib.appearance": appearance}
        with patch.dict(sys.modules, modules), patch("lib.backend", backend, create=True):
            scope["run"]()
        factory.assert_called_once()
        window.close.assert_called_once_with()
        launch.unmark_window.assert_called_once_with(window)
        kodi.executebuiltin.assert_called_once_with("ActivateWindow(Home)", True)
        guard.release.assert_called_once_with()

    def app_context(self, windows):
        import sys
        from types import ModuleType
        from unittest.mock import patch
        run = function_from_file(ROOT / "lib/app.py", "run")
        launch = ModuleType("lib.launch_guard")
        guard = Mock(); guard.acquire.return_value = True
        launch.defer_relaunch = self.exit_guard if hasattr(self, "exit_guard") else Mock()
        launch.LaunchGuard = Mock(return_value=guard)
        launch.mark_window = Mock(); launch.unmark_window = Mock()
        signin = ModuleType("lib.signin")
        signin.signed_in = Mock(return_value=True); signin.show_signin = Mock()
        vfs = ModuleType("xbmcvfs"); vfs.translatePath = lambda value: value
        backend = ModuleType("lib.backend")
        backend.account_home = Mock(return_value=[])
        backend.account_home_capacity = Mock(return_value=8)
        layout = ModuleType("lib.home_layout")
        layout.build_layout = Mock(return_value=("home.xml", "/tmp", 8))
        appearance = ModuleType("lib.appearance"); appearance.options = Mock(return_value={})
        kodi = Mock()
        kodi.getCondVisibility.return_value = False
        factory = Mock(side_effect=windows)
        gui = Mock(); gui.getCurrentWindowId.return_value = 10025
        scope = {"xbmcgui": gui, "HomeWindow": factory, "ADDON": Mock(),
                 "ADDON_PATH": "/addon", "SKIN": "Main", "RES": "1080i"}
        exec(compile(ast.Module(body=[run], type_ignores=[]), "<app>", "exec"), scope)
        modules = {"xbmc": kodi, "lib.launch_guard": launch, "lib.signin": signin,
                   "xbmcvfs": vfs, "lib.backend": backend,
                   "lib.home_layout": layout, "lib.appearance": appearance}
        def execute():
            with patch.dict(sys.modules, modules), patch("lib.backend", backend, create=True):
                scope["run"]()
        return execute, guard, kodi, factory, layout, gui

    def test_cancelled_modal_return_does_not_navigate_away(self):
        window = Mock(); window.reload_appearance = False; window.exit_requested = False
        execute, guard, kodi, factory, layout, gui = self.app_context([window])
        execute()
        kodi.executebuiltin.assert_not_called()
        guard.defer_relaunch.assert_not_called()
        guard.release.assert_called_once_with()

    def test_appearance_reload_recreates_home_without_exit_navigation(self):
        first = Mock(); first.reload_appearance = True; first.exit_requested = False
        second = Mock(); second.reload_appearance = False; second.exit_requested = False
        execute, guard, kodi, factory, layout, gui = self.app_context([first, second])
        execute()
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(layout.build_layout.call_count, 2)
        kodi.executebuiltin.assert_not_called()
        guard.defer_relaunch.assert_not_called()
        guard.release.assert_called_once_with()

    def test_exit_waits_for_native_previous_window_before_returning_home(self):
        window = Mock(); window.reload_appearance = False
        window.exit_requested = True; window.exit_window_id = 13002
        execute, guard, kodi, factory, layout, gui = self.app_context([window])
        gui.getCurrentWindowId.side_effect = [13002, 13002, 10025]
        def navigate(*args):
            self.assertEqual(kodi.sleep.call_count, 2)
            guard.release.assert_not_called()
        kodi.executebuiltin.side_effect = navigate
        execute()
        kodi.executebuiltin.assert_called_once_with("ActivateWindow(Home)", True)
        guard.release.assert_called_once_with()

    def test_exit_waits_for_closing_modal_before_home_navigation(self):
        window = Mock(); window.reload_appearance = False
        window.exit_requested = True; window.exit_window_id = 13002
        execute, guard, kodi, factory, layout, gui = self.app_context([window])
        kodi.getCondVisibility.side_effect = [True, True, False]
        execute()
        self.assertEqual(kodi.sleep.call_count, 2)
        kodi.executebuiltin.assert_called_once_with("ActivateWindow(Home)", True)

    def test_navigation_failure_still_releases_launch_lease(self):
        window = Mock(); window.reload_appearance = False; window.exit_requested = True
        execute, guard, kodi, factory, layout, gui = self.app_context([window])
        def unavailable(*args):
            guard.release.assert_not_called()
            raise RuntimeError("Kodi navigation unavailable")
        kodi.executebuiltin.side_effect = unavailable
        with self.assertRaisesRegex(RuntimeError, "navigation unavailable"):
            execute()
        guard.release.assert_called_once_with()

    def test_service_does_not_relaunch_after_user_exit_in_same_session(self):
        configured_delay = function_from_file(ROOT / "service.py", "configured_delay")
        maybe_autostart = function_from_file(ROOT / "service.py", "maybe_autostart")
        properties = {}
        session = Mock()
        session.getProperty.side_effect = lambda key: properties.get(key, "")
        session.setProperty.side_effect = lambda key, value: properties.update({key: value})
        addon = Mock()
        addon.getSetting.side_effect = lambda key: {
            "startup_autostart": "true", "startup_delay": "0"}.get(key, "")
        gui = Mock()
        gui.Window.return_value = session
        kodi = Mock()
        kodi.getCondVisibility.return_value = False
        monitor = Mock()
        monitor.abortRequested.return_value = False
        scope = {"ADDON": addon, "SESSION_WINDOW_ID": 10000,
                 "STARTUP_LAUNCHED": "stremioforkodi.startup.launched",
                 "APP_RUNNING": "stremioforkodi.running", "DELAYS": (0, 1, 2, 3, 5),
                 "xbmc": kodi, "xbmcgui": gui}
        exec(compile(ast.Module(body=[configured_delay, maybe_autostart], type_ignores=[]),
                     "<service>", "exec"), scope)
        scope["maybe_autostart"](monitor)
        # Closing the UI clears APP_RUNNING, but must retain STARTUP_LAUNCHED.
        properties.pop("stremioforkodi.running", None)
        scope["maybe_autostart"](monitor)
        kodi.executebuiltin.assert_called_once_with("RunScript(script.stremioelec,startup)")


if __name__ == "__main__":
    unittest.main()
