"""Free BYOK AI subtitle translation tests; no real Gemini requests."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))


def load_module():
    spec = importlib.util.spec_from_file_location("ai_subtitles", CORE / "ai_subtitles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, payload):
        self.body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body.read(size)


class Opener:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.payloads:
            raise AssertionError("unexpected Gemini request")
        return Response(self.payloads.pop(0))


def gemini_payload(rows):
    return {
        "candidates": [{
            "content": {"parts": [{"text": json.dumps(rows, ensure_ascii=False)}]}
        }]
    }


SRT = """1
00:00:01,000 --> 00:00:03,000
Hello.

2
00:00:04,000 --> 00:00:06,000
Good night.
"""
class AISubtitleTests(unittest.TestCase):
    def test_target_defaults_to_bosnian(self):
        module = load_module()
        self.assertEqual(module.target_code("0"), "bs")
        self.assertEqual(module.target_code("Bosnian"), "bs")
        self.assertEqual(module.target_code("hr"), "hr")

    def test_whole_track_translation_preserves_timestamps_and_uses_header_key(self):
        module = load_module()
        opener = Opener([gemini_payload([
            {"id": "1", "text": "Zdravo."},
            {"id": "2", "text": "Laku noć."},
        ])])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "movie.srt"
            source.write_text(SRT, encoding="utf-8")
            result = Path(module.translate_subtitle_file(
                source, Path(directory) / "cache", "test-user-key", "bs",
                source_language="eng", opener=opener
            ))
            translated = result.read_text(encoding="utf-8")

        self.assertIn("00:00:01,000 --> 00:00:03,000", translated)
        self.assertIn("00:00:04,000 --> 00:00:06,000", translated)
        self.assertIn("Zdravo.", translated)
        self.assertIn("Laku noć.", translated)
        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], "test-user-key")
        self.assertNotIn("test-user-key", request.full_url)
        self.assertNotIn("test-user-key", request.data.decode("utf-8"))
    def test_cached_translation_avoids_second_ai_request(self):
        module = load_module()
        opener = Opener([gemini_payload([
            {"id": "1", "text": "Zdravo."},
            {"id": "2", "text": "Laku noć."},
        ])])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "movie.srt"
            cache = Path(directory) / "cache"
            source.write_text(SRT, encoding="utf-8")
            first = module.translate_subtitle_file(
                source, cache, "test-user-key", "bs", "eng", opener
            )
            second = module.translate_subtitle_file(
                source, cache, "test-user-key", "bs", "eng", opener
            )
        self.assertEqual(first, second)
        self.assertEqual(len(opener.requests), 1)

    def test_incomplete_ai_output_is_rejected(self):
        module = load_module()
        opener = Opener([gemini_payload([
            {"id": "1", "text": "Zdravo."},
        ])])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "movie.srt"
            source.write_text(SRT, encoding="utf-8")
            with self.assertRaises(module.AITranslationError):
                module.translate_subtitle_file(
                    source, Path(directory) / "cache", "test-user-key", "bs",
                    source_language="eng", opener=opener
                )

    def test_source_already_target_skips_ai(self):
        module = load_module()
        opener = Opener([])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "movie.srt"
            source.write_text(SRT, encoding="utf-8")
            result = module.translate_subtitle_file(
                source, Path(directory) / "cache", "test-user-key", "bs",
                source_language="bos", opener=opener
            )
        self.assertEqual(result, str(source))
        self.assertEqual(opener.requests, [])
    def test_auto_source_prefers_exact_target_then_clean_english(self):
        module = load_module()
        tracks = [
            {"lang": "rus", "label": "Forced", "forced": True, "impaired": False, "default": False},
            {"lang": "eng", "label": "SDH", "forced": False, "impaired": True, "default": False},
            {"lang": "eng", "label": "Full", "forced": False, "impaired": False, "default": False},
        ]
        best = sorted(tracks, key=lambda item: module._embedded_rank(item, "hr"))[0]
        self.assertEqual(best["label"], "Full")
        tracks.append({"lang": "hrv", "label": "Full", "forced": False, "impaired": False, "default": False})
        best = sorted(tracks, key=lambda item: module._embedded_rank(item, "hr"))[0]
        self.assertEqual(best["lang"], "hrv")

    def test_settings_expose_free_byok_and_truthful_premium_placeholder(self):
        settings = (ROOT / "resources" / "settings.xml").read_text(encoding="utf-8")
        root = ET.fromstring(settings)
        self.assertIn('id="ai_subtitles_gemini_api_key"', settings)
        self.assertIn("My Gemini API key - Free", settings)
        self.assertIn("Auto - Video first, then Stremio addons", settings)
        self.assertIn("Vortexo Premium - In construction", settings)
        self.assertIn("$4.99 USD/month", settings)
        self.assertNotIn('label="Get Premium"', settings)
        self.assertIsNotNone(root)

    def test_download_path_is_ai_translation_hook(self):
        source = (CORE / "subtitles.py").read_text(encoding="utf-8")
        self.assertIn("from ai_subtitles import maybe_translate", source)
        self.assertIn("return maybe_translate(target, Path(directory).parent, lang)", source)
        self.assertIn("def ai_source_candidates", source)

    def test_libreelec_ffmpeg_tools_path_is_supported(self):
        module = load_module()
        with patch.object(module.shutil, "which", return_value=None), \
                patch.object(module.Path, "is_file", autospec=True) as exists:
            exists.side_effect = lambda path: str(path) == "/storage/.kodi/addons/tools.ffmpeg-tools/bin/ffmpeg"
            self.assertEqual(
                module._binary("ffmpeg"),
                "/storage/.kodi/addons/tools.ffmpeg-tools/bin/ffmpeg",
            )

    def test_service_runs_video_first_then_stremio_fallback_in_background(self):
        source = (ROOT / "service.py").read_text(encoding="utf-8")
        self.assertIn("prepare_embedded_auto", source)
        self.assertIn("ai_source_candidates", source)
        self.assertIn("threading.Thread", source)
        self.assertLess(source.index("prepare_embedded_auto"), source.index("ai_source_candidates("))
        self.assertIn("_remember_ai_error", source)
        self.assertIn("Report last error is available", source)


if __name__ == "__main__":
    unittest.main()
