"""Playback service must respect the remote Auto translate preference."""
import ast
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]

class PlaybackSubtitlePreferencesTests(unittest.TestCase):
    def prepare(self, enabled, cloud_result=None, entries=None, source="0"):
        tree = ast.parse((ROOT / "service.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PlaybackWatcher")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_prepare")
        progress, errors, notice = Mock(), Mock(), Mock()
        cloud, translate, download, embedded = Mock(return_value=cloud_result), Mock(return_value="/tmp/translated.srt"), Mock(return_value="/tmp/original.srt"), Mock(return_value=None)
        premium, signin, ai, setup = (ModuleType(name) for name in ("lib.vortexo_premium", "lib.signin", "ai_subtitles", "setup_profile"))
        premium.resolve_subtitle_cloud = cloud
        signin.account_store = lambda: object()
        ai.translate_external_auto = translate
        ai.AITranslationError = RuntimeError
        setup.atomic_write = Mock()
        player = SimpleNamespace(_context=Mock(return_value={"kind":"movie","id":"tt1"}), _matches=Mock(return_value=True), _apply=Mock(return_value=True))
        with tempfile.TemporaryDirectory() as directory:
            scope = {"local_settings":lambda:{"enabled":True,"auto_translate":enabled,"target":"bs","source":source}, "CODE_NAMES":{"bs":"Bosnian","en":"English"}, "PROFILE":Path(directory), "progress_bg":lambda:progress, "Store":lambda path:SimpleNamespace(load=lambda:{}), "active_addons":lambda account:[], "ai_source_candidates":Mock(return_value=entries if entries is not None else [{"lang":"en"}]), "download_original":download, "prepare_embedded_auto":embedded, "_remember_ai_error":errors, "_notify":notice}
            exec(compile(ast.Module(body=[method], type_ignores=[]), "<service-playback>", "exec"), scope)
            with patch.dict(sys.modules, {"lib.vortexo_premium":premium, "lib.signin":signin, "ai_subtitles":ai, "setup_profile":setup}):
                scope["_prepare"](player, "https://video.test/file.mkv", "digest")
        return SimpleNamespace(cloud=cloud, translate=translate, download=download, embedded=embedded, errors=errors, notice=notice, player=player, progress=progress, write=setup.atomic_write)

    def test_translation_off_keeps_original_without_cloud_or_byok_requests(self):
        result = self.prepare(False)
        result.cloud.assert_not_called()
        result.translate.assert_not_called()
        result.download.assert_called_once()
        result.player._apply.assert_called_once_with("/tmp/original.srt", "digest", "Stremio addon", "en", "en")
        result.progress.close.assert_called_once()
        result.errors.assert_not_called()

    def test_translation_on_uses_cloud_and_applies_the_ready_subtitle(self):
        result = self.prepare(True, {"subtitle":"1\n00:00:01,000 --> 00:00:02,000\nZdravo.\n", "source_language":"en", "target_language":"bs"})
        result.cloud.assert_called_once()
        result.write.assert_called_once()
        result.download.assert_not_called()
        result.translate.assert_not_called()
        self.assertEqual(result.player._apply.call_args.args[2:], ("MKGA Cloud", "en", "bs"))
        result.progress.close.assert_called_once()

    def test_translation_on_falls_back_to_local_provider_when_cloud_has_no_result(self):
        result = self.prepare(True)
        result.cloud.assert_called_once()
        result.download.assert_called_once()
        result.translate.assert_called_once()
        self.assertEqual(result.player._apply.call_count, 2)

    def test_translation_off_with_no_addon_result_keeps_existing_embedded_tracks(self):
        result = self.prepare(False, entries=[])
        result.cloud.assert_not_called()
        result.translate.assert_not_called()
        result.embedded.assert_not_called()
        result.errors.assert_not_called()
        result.notice.assert_not_called()
        result.progress.close.assert_called_once()

    def test_embedded_only_no_result_reports_diagnostic_without_unbound_entries(self):
        result = self.prepare(True, entries=[], source="1")
        result.embedded.assert_called_once()
        result.errors.assert_called_once()
        result.progress.close.assert_called_once()

if __name__ == "__main__":
    unittest.main()
