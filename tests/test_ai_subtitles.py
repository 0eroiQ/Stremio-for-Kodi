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


    def test_local_master_switch_can_disable_mkga_smart_subtitles(self):
        module = load_module()
        class Addon:
            def getSetting(self, key):
                values = {
                    "ai_subtitles_enabled": "false",
                    "ai_subtitles_provider": "0",
                    "ai_subtitles_source": "0",
                    "ai_subtitles_gemini_api_key": "local-key",
                    "ai_subtitles_target": "3",
                }
                return values.get(key, "")
        addon_state = types.ModuleType("addon_state")
        addon_state.get_addon = lambda: Addon()
        signin = types.ModuleType("lib.signin")
        signin.account_store = lambda: object()
        premium = types.ModuleType("lib.vortexo_premium")
        premium.hub_state = lambda store: {
            "linked": True,
            "plan": "supporter",
            "settings": {
                "preferredLanguages": ["bs", "de"],
                "smartSubtitles": True,
                "autoTranslate": True,
                "generateFromAudio": True,
                "finishFullTitle": True,
                "communityCache": True,
                "autoTiming": True,
            },
        }
        with patch.dict(sys.modules, {
            "addon_state": addon_state,
            "lib.signin": signin,
            "lib.vortexo_premium": premium,
        }):
            settings = module.local_settings()
        self.assertTrue(settings["remote"])
        self.assertFalse(settings["enabled"])
        self.assertEqual(settings["target"], "bs")
        self.assertEqual(settings["preferred_languages"], ["bs", "de"])
        self.assertTrue(settings["generate_from_audio"])
        self.assertTrue(settings["finish_full_title"])

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

    def test_settings_expose_free_byok_without_premium_ui(self):
        settings = (ROOT / "resources" / "settings.xml").read_text(encoding="utf-8")
        root = ET.fromstring(settings)
        self.assertIn('id="ai_subtitles_gemini_api_key"', settings)
        self.assertIn("My Gemini API key - Free", settings)
        self.assertIn("Auto - Video first, then Stremio addons", settings)
        self.assertNotIn("MKGA Premium", settings)
        self.assertNotIn("$4.99", settings)
        self.assertNotIn('label="Get Premium"', settings)
        self.assertIsNotNone(root)

    def test_download_path_is_ai_translation_hook(self):
        source = (CORE / "subtitles.py").read_text(encoding="utf-8")
        self.assertIn("from ai_subtitles import maybe_translate", source)
        self.assertIn("return maybe_translate(", source)
        self.assertIn("progress_callback=progress_callback", source)
        self.assertIn("def ai_source_candidates", source)

    def test_translation_uses_larger_batches_and_reports_progress(self):
        module = load_module()
        cues = []
        for index in range(321):
            cues.append(
                "{}\n00:{:02d}:{:02d},000 --> 00:{:02d}:{:02d},500\nLine {}".format(
                    index + 1,
                    (index // 60) % 60, index % 60,
                    (index // 60) % 60, index % 60,
                    index + 1,
                )
            )
        source_text = "\n\n".join(cues) + "\n"
        progress = []

        def fake_request(batch, api_key, target_language, source_language=None, opener=None):
            return {cue["id"]: "HR " + cue["text"] for cue in batch}

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(module, "_request_translation", side_effect=fake_request) as request:
            source = Path(directory) / "long.srt"
            source.write_text(source_text, encoding="utf-8")
            result = Path(module.translate_subtitle_file(
                source, Path(directory) / "cache", "test-user-key", "hr", "en",
                progress_callback=lambda percent, message: progress.append((percent, message))
            ))
            translated = result.read_text(encoding="utf-8")

        self.assertEqual(module.MAX_BATCH_CUES, 2400)
        self.assertEqual(module.MAX_BATCH_CHARACTERS, 120000)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(progress[0][0], 0)
        self.assertEqual(progress[-1][0], 100)
        self.assertIn("Translating to Croatian", progress[-1][1])
        self.assertEqual(translated.count("-->"), 321)


    def test_noiro_batch_packer_splits_only_oversized_tracks(self):
        module = load_module()
        normal = [{"id": str(i), "text": "Line " + str(i)} for i in range(700)]
        self.assertEqual(len(module._translation_batches(normal)), 1)
        huge = [{"id": str(i), "text": "x" * 1000} for i in range(250)]
        batches = module._translation_batches(huge)
        self.assertGreater(len(batches), 1)
        self.assertEqual(sum(len(batch) for batch in batches), len(huge))

    def test_successful_gemini_model_is_preferred_next_time(self):
        module = load_module()
        module._preferred_model = None
        cues = [{"id": "1", "text": "Hello"}]
        good = module.MODEL_CHAIN[1]
        calls = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit):
                import json
                inner = json.dumps([{"id": "1", "text": "Bok"}])
                return json.dumps({
                    "candidates": [{"content": {"parts": [{"text": inner}]}}]
                }).encode("utf-8")

        class Opener:
            def open(self, request, timeout=None):
                model = request.full_url.split('/models/', 1)[1].split(':', 1)[0]
                calls.append(model)
                if model != good:
                    from urllib.error import HTTPError
                    raise HTTPError(request.full_url, 404, "Not Found", {}, None)
                return Response()

        result = module._request_translation(cues, "test-key", "hr", "en", opener=Opener())
        self.assertEqual(result["1"], "Bok")
        self.assertEqual(module._preferred_model, good)
        calls.clear()
        module._request_translation(cues, "test-key", "hr", "en", opener=Opener())
        self.assertEqual(calls[0], good)

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
        self.assertIn("progress_bg", source)
        self.assertIn("progress_callback=update", source)
        self.assertIn("Report last error is available", source)
        self.assertIn("download_original", source)
        self.assertIn("Never leave playback subtitle-less while AI is working", source)


if __name__ == "__main__":
    unittest.main()

class EmbeddedKodi22Tests(unittest.TestCase):
    def test_kodi22_extraction_falls_back_to_second_text_track(self):
        module=load_module()
        tracks=[{'index':2,'codec':'ass','lang':'eng','label':'Full','forced':False,'impaired':False,'default':True},{'index':3,'codec':'subrip','lang':'eng','label':'Backup','forced':False,'impaired':False,'default':False}]
        class R:
            def __init__(self,code,data):self.returncode=code;self.stdout=data
        with tempfile.TemporaryDirectory() as d, patch.object(module,'_binary',return_value='ffmpeg'), patch.object(module,'embedded_tracks',return_value=tracks), patch.object(module.subprocess,'run',side_effect=[R(1,b''),R(0,b'1\\n00:00:01,000 --> 00:00:02,000\\nHello\\n')]) as run:
            path,lang,track=module.extract_best_embedded('https://example/video.mkv',Path(d),'bs')
            self.assertEqual(track['index'],3);self.assertEqual(lang,'en');self.assertTrue(Path(path).exists());self.assertIn('-nostdin',run.call_args_list[0].args[0])

class GeminiFallbackTests(unittest.TestCase):
    def test_invalid_first_model_response_falls_back(self):
        module=load_module(); module._preferred_model=None
        cues=[{'id':'1','text':'Hello'}]; calls=[]
        class Response:
            def __init__(self,payload):self.payload=payload
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):return json.dumps(self.payload).encode()
        class Opener:
            def open(self,request,timeout=None):
                calls.append((request.full_url,timeout))
                if len(calls)==1:return Response({'candidates':[{'content':{'parts':[{'text':'not-json'}]}}]})
                inner=json.dumps([{'id':'1','text':'Zdravo'}])
                return Response({'candidates':[{'content':{'parts':[{'text':inner}]}}]})
        self.assertEqual(module._request_translation(cues,'key','bs','en',Opener())['1'],'Zdravo')
        self.assertEqual(len(calls),2);self.assertEqual(calls[0][1],15)
