"""Startup-shell and top-level exit behavior regressions."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock

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

    def test_back_cancel_does_not_change_or_close_home(self):
        on_action = function_from_file(ROOT / "lib/nimbus.py", "onAction", "HomeWindow")
        dialog = Mock()
        dialog.yesno.return_value = False
        xbmcgui = Mock()
        xbmcgui.Dialog.return_value = dialog
        window = Mock()
        window.getProperty.return_value = 'Home'
        action = Mock()
        action.getId.return_value = 92
        scope = {"BACK": (10, 92, 216, 247), "xbmcgui": xbmcgui, "home_index": lambda: 1}
        exec(compile(ast.Module(body=[on_action], type_ignores=[]), "<home>", "exec"), scope)
        scope["onAction"](window, action)
        dialog.yesno.assert_called_once()
        window.close.assert_not_called()
        window.cancel_trailer.assert_not_called()
        window.setFocusId.assert_not_called()

    def test_back_exit_closes_home(self):
        on_action = function_from_file(ROOT / "lib/nimbus.py", "onAction", "HomeWindow")
        dialog = Mock()
        dialog.yesno.return_value = True
        xbmcgui = Mock()
        xbmcgui.Dialog.return_value = dialog
        window = Mock()
        window.getProperty.return_value = 'Home'
        action = Mock()
        action.getId.return_value = 92
        scope = {"BACK": (10, 92, 216, 247), "xbmcgui": xbmcgui, "home_index": lambda: 1}
        exec(compile(ast.Module(body=[on_action], type_ignores=[]), "<home>", "exec"), scope)
        scope["onAction"](window, action)
        window.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
