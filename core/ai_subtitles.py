"""Free BYOK Gemini subtitle translation for Stremio for Kodi.

The viewer's Gemini key stays in Kodi add-on settings and is sent only to
Google's Generative Language API. MKGA account sync is separate from the local BYOK translation path.
"""
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from setup_profile import atomic_write

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODEL_CHAIN = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
)
MAX_FILE_BYTES = 512 * 1024
MAX_CUES = 2400
MAX_CUE_TEXT = 8000
TIMEOUT_SECONDS = 15
MAX_MODEL_ATTEMPTS = 2
MAX_BATCH_CUES = 2400
MAX_BATCH_CHARACTERS = 120000
TRANSLATION_REVISION = "byok-v2"
TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text", "subviewer", "microdvd"}
FFMPEG_TIMEOUT_SECONDS = 15
MAX_MODEL_ATTEMPTS = 2
FFPROBE_TIMEOUT_SECONDS = 25
TARGETS = (
    ("Bosnian", "bs"), ("Croatian", "hr"), ("Serbian", "sr"),
    ("English", "en"), ("German", "de"), ("French", "fr"),
    ("Spanish", "es"), ("Italian", "it"), ("Portuguese", "pt"),
    ("Dutch", "nl"), ("Polish", "pl"), ("Czech", "cs"),
    ("Slovak", "sk"), ("Slovenian", "sl"), ("Macedonian", "mk"),
    ("Albanian", "sq"), ("Turkish", "tr"), ("Greek", "el"),
    ("Romanian", "ro"), ("Hungarian", "hu"), ("Bulgarian", "bg"),
    ("Russian", "ru"), ("Ukrainian", "uk"), ("Arabic", "ar"),
    ("Hebrew", "he"), ("Hindi", "hi"), ("Chinese", "zh"),
    ("Japanese", "ja"), ("Korean", "ko"),
)
TARGET_NAMES = dict(TARGETS)
CODE_NAMES = {code: name for name, code in TARGETS}
_preferred_model = None

ISO3_TO_2 = {
    "bos": "bs", "hrv": "hr", "srp": "sr", "eng": "en", "deu": "de",
    "ger": "de", "fra": "fr", "fre": "fr", "spa": "es", "ita": "it",
    "por": "pt", "nld": "nl", "dut": "nl", "pol": "pl", "ces": "cs",
    "cze": "cs", "slk": "sk", "slo": "sk", "slv": "sl", "mkd": "mk",
    "mac": "mk", "sqi": "sq", "alb": "sq", "tur": "tr", "ell": "el",
    "gre": "el", "ron": "ro", "rum": "ro", "hun": "hu", "bul": "bg",
    "rus": "ru", "ukr": "uk", "ara": "ar", "heb": "he", "hin": "hi",
    "zho": "zh", "chi": "zh", "jpn": "ja", "kor": "ko",
}


class AITranslationError(Exception):
    pass
def target_code(value):
    raw = str(value or "").strip()
    if raw in CODE_NAMES:
        return raw
    if raw in TARGET_NAMES:
        return TARGET_NAMES[raw]
    try:
        index = int(raw or "0")
    except ValueError:
        index = 0
    return TARGETS[index][1] if 0 <= index < len(TARGETS) else "bs"


def _source_code(value):
    raw = str(value or "").strip().lower()
    return ISO3_TO_2.get(raw, raw)


def source_rank(language, label, target_language):
    """Best source: target as-is, then clean English, then any clean full track."""
    code = _source_code(language)
    text = str(label or "").lower()
    exact = 0 if code == target_language else 1
    english = 0 if code == "en" else 1
    forced = 1 if "forced" in text else 0
    impaired = 1 if any(word in text for word in ("sdh", "hearing", "impaired", "cc")) else 0
    full = 0 if "full" in text else 1
    return exact, forced, impaired, english, full


def rank_external_entries(entries, target_language):
    return sorted(entries, key=lambda item: source_rank(
        item.get("lang"), item.get("label"), target_language
    ))


def _binary(name):
    found = shutil.which(name)
    if found:
        return found
    roots = (
        "/storage/.kodi/addons/tools.ffmpeg-tools/bin",
        "/storage/.kodi/addons/virtual.multimedia-tools/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
    )
    for root in roots:
        candidate = Path(root) / name
        if candidate.is_file():
            return str(candidate)
    return None


def _parse_timed_text(content):
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = re.split(r"\n{2,}", normalized)
    cues = []
    for block_index, block in enumerate(blocks):
        lines = block.split("\n")
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None or timing_index + 1 >= len(lines):
            continue
        text = "\n".join(lines[timing_index + 1:]).strip()
        if not text:
            continue
        if len(text) > MAX_CUE_TEXT:
            raise AITranslationError("Subtitle cue is too large.")
        cues.append({
            "id": str(len(cues) + 1), "block": block_index,
            "timing": timing_index, "text": text,
        })
    if not cues or len(cues) > MAX_CUES:
        raise AITranslationError("Unsupported subtitle cue count.")
    return blocks, cues


def embedded_tracks(stream_url):
    probe = _binary("ffprobe")
    if not probe:
        return []
    command = [
        probe, "-v", "error", "-select_streams", "s",
        "-show_entries",
        "stream=index,codec_name:stream_tags=language,title:"
        "stream_disposition=default,forced,hearing_impaired",
        "-of", "json", stream_url,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS, check=False
        )
        payload = json.loads(result.stdout or "{}") if result.returncode == 0 else {}
    except Exception:
        return []
    tracks = []
    for item in payload.get("streams", []):
        if not isinstance(item, dict) or item.get("codec_name") not in TEXT_SUBTITLE_CODECS:
            continue
        tags = item.get("tags") if isinstance(item.get("tags"), dict) else {}
        disposition = item.get("disposition") if isinstance(item.get("disposition"), dict) else {}
        tracks.append({
            "index": item.get("index"),
            "codec": item.get("codec_name"),
            "lang": str(tags.get("language") or "und").lower(),
            "label": str(tags.get("title") or ""),
            "forced": bool(disposition.get("forced")),
            "impaired": bool(disposition.get("hearing_impaired")),
            "default": bool(disposition.get("default")),
        })
    return tracks


def _embedded_rank(track, target_language):
    label = track.get("label", "")
    base = source_rank(track.get("lang"), label, target_language)
    return (
        base[0],
        1 if track.get("forced") else base[1],
        1 if track.get("impaired") else base[2],
        base[3], base[4],
        0 if track.get("default") else 1,
    )


def extract_best_embedded(stream_url, cache_directory, target_language):
    ffmpeg = _binary("ffmpeg")
    if not ffmpeg:
        raise AITranslationError(
            "Embedded subtitle extraction is unavailable. "
            "LibreELEC users can install the official FFmpeg Tools addon."
        )
    tracks = embedded_tracks(stream_url)
    if not tracks:
        raise AITranslationError("No text subtitle track is embedded in this video.")
    track = sorted(tracks, key=lambda item: _embedded_rank(item, target_language))[0]
    stream_index = track.get("index")
    if not isinstance(stream_index, int):
        raise AITranslationError("Invalid embedded subtitle track.")
    digest = hashlib.sha256(stream_url.encode("utf-8")).hexdigest()
    language = _source_code(track.get("lang")) or "und"
    destination = Path(cache_directory) / (
        digest + ".embedded-" + str(stream_index) + "." + language + ".srt"
    )
    if destination.exists() and destination.stat().st_size:
        return str(destination), language, track
    # Map by the absolute ffprobe stream index. Kodi 22 ships newer FFmpeg
    # builds where subtitle codec handling changed; keep extraction text-only
    # and explicitly disable unrelated streams for predictable Windows output.
    command = [
        ffmpeg, "-nostdin", "-v", "error", "-i", stream_url,
        "-map", "0:" + str(stream_index), "-vn", "-an", "-dn",
        "-c:s", "srt", "-f", "srt", "pipe:1",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS, check=False
        )
    except Exception as error:
        raise AITranslationError("Could not extract embedded subtitles.") from error
    if result.returncode != 0 or not result.stdout or len(result.stdout) > MAX_FILE_BYTES:
        # Some containers expose a text subtitle to ffprobe but FFmpeg cannot
        # transcode that particular stream. Try other ranked text tracks before
        # failing the whole AUTO translation.
        for alternate in sorted(tracks, key=lambda item: _embedded_rank(item, target_language))[1:]:
            alternate_index = alternate.get("index")
            if not isinstance(alternate_index, int):
                continue
            alternate_cmd = [ffmpeg, "-nostdin", "-v", "error", "-i", stream_url,
                "-map", "0:" + str(alternate_index), "-vn", "-an", "-dn",
                "-c:s", "srt", "-f", "srt", "pipe:1"]
            try:
                alternate_result = subprocess.run(alternate_cmd, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS, check=False)
            except Exception:
                continue
            if alternate_result.returncode == 0 and alternate_result.stdout and len(alternate_result.stdout) <= MAX_FILE_BYTES:
                track, stream_index, result = alternate, alternate_index, alternate_result
                language = _source_code(track.get("lang")) or "und"
                destination = Path(cache_directory) / (digest + ".embedded-" + str(stream_index) + "." + language + ".srt")
                break
        else:
            raise AITranslationError("Could not extract embedded text subtitles from this video.")
    atomic_write(destination, result.stdout)
    return str(destination), language, track


def _prompt(cues, target_language, source_language=None):
    target_name = CODE_NAMES.get(target_language, target_language)
    source = _source_code(source_language) or "auto"
    compact = [{"id": cue["id"], "text": cue["text"]} for cue in cues]
    return (
        "Translate every subtitle cue to " + target_name + ".\n"
        "Return valid JSON only: an array of objects with exactly id and text.\n"
        "Keep the exact same cue count, order and id values.\n"
        "Translate dialogue only. Preserve names, punctuation, speaker labels, "
        "simple subtitle markup and line breaks. Do not add notes or explanations.\n"
        "Source language: " + source + ".\n\nInput:\n" +
        json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    )


def _gemini_text(payload):
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        raise AITranslationError("Gemini returned no translation.") from None
    text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise AITranslationError("Gemini returned no translation.")
    return text


def _decode_translations(text, cues):
    cleaned = text.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*" + re.escape(fence) + r"$", "", cleaned)
    try:
        rows = json.loads(cleaned)
    except (TypeError, ValueError):
        raise AITranslationError("Gemini returned invalid translation data.") from None
    if isinstance(rows, dict):
        rows = rows.get("cues") or rows.get("translations")
    if not isinstance(rows, list) or len(rows) != len(cues):
        raise AITranslationError("Gemini returned an incomplete translation.")
    expected = [cue["id"] for cue in cues]
    result = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or str(row.get("id")) != expected[index]:
            raise AITranslationError("Gemini changed subtitle cue identities.")
        translated = row.get("text")
        if not isinstance(translated, str) or not translated.strip() or len(translated) > MAX_CUE_TEXT * 2:
            raise AITranslationError("Gemini returned an invalid subtitle cue.")
        result[expected[index]] = translated.strip()
    return result


def _ordered_models():
    if _preferred_model in MODEL_CHAIN:
        return (_preferred_model,) + tuple(
            model for model in MODEL_CHAIN if model != _preferred_model
        )
    return MODEL_CHAIN


def _request_translation(cues, api_key, target_language, source_language=None, opener=None):
    global _preferred_model
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": _prompt(
            cues, target_language, source_language
        )}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 65536,
            "responseMimeType": "application/json",
        },
    }, ensure_ascii=False).encode("utf-8")
    client = opener or build_opener()
    last_error = None
    for model in _ordered_models()[:MAX_MODEL_ATTEMPTS]:
        request = Request(
            BASE_URL + "/" + model + ":generateContent",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-goog-api-key": api_key,
                "User-Agent": "Stremio-for-Kodi/1",
            },
            method="POST",
        )
        try:
            with client.open(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_FILE_BYTES * 4 + 1)
            if len(raw) > MAX_FILE_BYTES * 4:
                raise AITranslationError("Gemini response was too large.")
            payload = json.loads(raw.decode("utf-8"))
            translated = _decode_translations(_gemini_text(payload), cues)
            _preferred_model = model
            return translated
        except HTTPError as error:
            last_error = error
            if _preferred_model == model:
                _preferred_model = None
            if error.code in (404, 408, 429, 500, 502, 503, 504):
                continue
            break
        except (AITranslationError, ValueError) as error:
            last_error = error
            if _preferred_model == model:
                _preferred_model = None
            # A malformed/partial model response may be model-specific. Try the
            # next compatible Gemini model instead of failing AUTO translation.
            continue
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if _preferred_model == model:
                _preferred_model = None
            continue
        except Exception as error:
            last_error = error
            if _preferred_model == model:
                _preferred_model = None
            continue
    raise AITranslationError("AI subtitle translation is temporarily unavailable.") from last_error


def _translation_batches(cues):
    """Noiro parity: pack a normal movie/episode into one Gemini request."""
    batches = []
    current = []
    characters = 0
    for cue in cues:
        size = len(str(cue.get("text") or ""))
        if current and (
            len(current) >= MAX_BATCH_CUES
            or characters + size > MAX_BATCH_CHARACTERS
        ):
            batches.append(current)
            current = []
            characters = 0
        current.append(cue)
        characters += size
    if current:
        batches.append(current)
    return batches


def _rebuild(blocks, cues, translations):
    replacements = {cue["block"]: (cue, translations[cue["id"]]) for cue in cues}
    output = []
    for block_index, block in enumerate(blocks):
        if block_index not in replacements:
            output.append(block)
            continue
        cue, translated = replacements[block_index]
        lines = block.split("\n")
        output.append("\n".join(lines[:cue["timing"] + 1] + translated.splitlines()))
    return "\n\n".join(output).rstrip() + "\n"
def _progress(callback, percent, message):
    if callback is None:
        return
    try:
        callback(max(0, min(100, int(percent))), str(message or ""))
    except Exception:
        pass


def _cloud_translation(cues, source_data, target_language, source_language=None):
    try:
        from lib.signin import account_store
        from lib.vortexo_premium import translate_subtitle_cloud
        source_hash = hashlib.sha256(source_data).hexdigest()
        result = translate_subtitle_cloud(
            account_store(), source_hash,
            [{"id": cue["id"], "text": cue["text"]} for cue in cues],
            target_language, source_language
        )
        return result.get("translations") or {}
    except Exception:
        return {}


def translate_subtitle_file(path, cache_directory, api_key, target_language,
                            source_language=None, opener=None, progress_callback=None):
    source = Path(path)
    if source.suffix.lower() not in (".srt", ".vtt"):
        raise AITranslationError("AI translation currently supports SRT and WebVTT.")
    data = source.read_bytes()
    if not data or len(data) > MAX_FILE_BYTES:
        raise AITranslationError("Subtitle file is too large for AI translation.")
    target_language = target_code(target_language)
    if _source_code(source_language) == target_language:
        return str(source)

    digest = hashlib.sha256(
        data + ("|" + target_language + "|" + TRANSLATION_REVISION).encode("utf-8")
    ).hexdigest()
    destination = Path(cache_directory) / (
        digest + "." + target_language + source.suffix.lower()
    )
    if destination.exists() and destination.stat().st_size:
        _progress(progress_callback, 100, "Cached translation ready")
        return str(destination)

    content = data.decode("utf-8-sig", errors="replace")
    blocks, cues = _parse_timed_text(content)
    translations = _cloud_translation(cues, data, target_language, source_language)
    if len(translations) == len(cues):
        _progress(progress_callback, 100, "MKGA Cloud translation ready")
        atomic_write(destination, _rebuild(blocks, cues, translations).encode("utf-8"))
        return str(destination)
    if not str(api_key or "").strip():
        raise AITranslationError("MKGA Cloud translation was unavailable and no BYOK Gemini key is configured.")
    translations = {}
    batches = _translation_batches(cues)
    target_name = CODE_NAMES.get(target_language, target_language)
    _progress(progress_callback, 0, "Starting " + target_name + " translation")
    for index, batch in enumerate(batches):
        _progress(
            progress_callback,
            int(index * 100 / len(batches)),
            "Translating to {} · request {}/{}".format(
                target_name, index + 1, len(batches)
            ),
        )
        result = _request_translation(
            batch, api_key.strip(), target_language, source_language, opener=opener
        )
        translations.update(result)
        _progress(
            progress_callback,
            int((index + 1) * 100 / len(batches)),
            "Translating to {} · {}%".format(
                target_name, int((index + 1) * 100 / len(batches))
            ),
        )
    if len(translations) != len(cues):
        raise AITranslationError("Gemini returned an incomplete subtitle translation.")
    atomic_write(destination, _rebuild(blocks, cues, translations).encode("utf-8"))
    return str(destination)


def _apply_remote_style(settings):
    if not settings.get("remote"):
        return
    try:
        import xbmc
        size_map = {"small": 32, "medium": 40, "large": 48, "extra-large": 56}
        color_map = {"white": "FFFFFFFF", "yellow": "FFFFFF00", "orange": "FFFFA500", "cyan": "FF00FFFF", "green": "FF00FF00"}
        align_map = {"bottom": 0, "middle": 1, "top": 2}
        for key, value in (("subtitles.fontsize", size_map.get(settings.get("subtitle_size"), 40)), ("subtitles.colorpick", color_map.get(settings.get("subtitle_color"), "FFFFFFFF")), ("subtitles.align", align_map.get(settings.get("subtitle_position"), 0))):
            payload = json.dumps({"jsonrpc":"2.0","id":1,"method":"Settings.SetSettingValue","params":{"setting":key,"value":value}})
            xbmc.executeJSONRPC(payload)
    except Exception:
        pass

def cloud_ai_available():
    try:
        from lib.signin import account_store
        from lib.vortexo_premium import cached_state, refresh_quiet
        store = account_store()
        state = cached_state(store)
        if not state or int(time.time()) - int(state.get("checked_at") or 0) > 300:
            state = refresh_quiet(store)
        return bool(state and state.get("entitlements", {}).get("ai_translation"))
    except Exception:
        return False


def local_settings():
    from addon_state import get_addon
    addon = get_addon()
    settings = {
        "enabled": addon.getSetting("ai_subtitles_enabled").strip().lower() == "true",
        "provider": addon.getSetting("ai_subtitles_provider").strip() or "0",
        "source": addon.getSetting("ai_subtitles_source").strip() or "0",
        "api_key": addon.getSetting("ai_subtitles_gemini_api_key").strip(),
        "target": target_code(addon.getSetting("ai_subtitles_target")),
        "remote": False,
        "preferred_languages": [],
        "auto_translate": True,
        "generate_from_audio": False,
        "finish_full_title": False,
        "community_cache": False,
        "auto_timing": False,
        "source_priority": ["mkga_cache", "embedded", "stremio", "translate", "audio"],
        "subtitle_size": "medium", "subtitle_position": "bottom", "subtitle_color": "white",
    }
    try:
        use_remote = addon.getSetting("subtitle_settings_source").strip() in ("", "0")
        if not use_remote:
            return settings
        from lib.signin import account_store
        from lib.vortexo_premium import hub_state
        hub = hub_state(account_store())
        remote = hub.get("settings") if isinstance(hub, dict) and hub.get("linked") else None
        if isinstance(remote, dict):
            languages = [str(x).strip().lower() for x in remote.get("preferredLanguages", [])
                         if isinstance(x, str) and str(x).strip()]
            settings.update({
                # MKGA.TV is authoritative when Remote settings are selected.
                # Do not require the legacy local master switch as a second hidden gate.
                "enabled": bool(remote.get("smartSubtitles")),
                "target": target_code(languages[0]) if languages else settings["target"],
                "remote": True,
                "preferred_languages": languages,
                "auto_translate": bool(remote.get("autoTranslate")),
                "generate_from_audio": bool(remote.get("generateFromAudio")),
                "finish_full_title": bool(remote.get("finishFullTitle")),
                "community_cache": bool(remote.get("communityCache")),
                "auto_timing": bool(remote.get("autoTiming")),
                "source_priority": list(remote.get("sourcePriority") or settings["source_priority"]),
                "subtitle_size": str(remote.get("subtitleSize") or "medium"),
                "subtitle_position": str(remote.get("subtitlePosition") or "bottom"),
                "subtitle_color": str(remote.get("subtitleColor") or "white"),
            })
    except Exception:
        pass
    _apply_remote_style(settings)
    return settings


def prepare_embedded_auto(stream_url, profile, progress_callback=None):
    """Video-first AUTO source. Returns translated/exact-target subtitle + metadata."""
    settings = local_settings()
    if (not settings["enabled"] or not settings.get("auto_translate", True)
            or settings["provider"] != "0" or (not settings["api_key"] and not cloud_ai_available())):
        return None
    cache = Path(profile) / "ai-subtitles"
    _progress(progress_callback, 5, "Checking subtitles embedded in the video")
    source_path, source_language, track = extract_best_embedded(
        stream_url, cache / "embedded", settings["target"]
    )
    source_name = CODE_NAMES.get(source_language, source_language or "Auto")
    _progress(progress_callback, 15, source_name + " subtitle ready · preserving original sync")
    if source_language == settings["target"]:
        final_path = source_path
    else:
        def translation_progress(percent, message):
            _progress(progress_callback, 20 + int(percent * 0.75), message)
        final_path = translate_subtitle_file(
            source_path, cache, settings["api_key"], settings["target"], source_language,
            progress_callback=translation_progress
        )
    return {
        "path": final_path,
        "source_language": source_language,
        "target_language": settings["target"],
        "source": "video",
        "track": track,
    }


def translate_external_auto(path, profile, source_language=None, progress_callback=None):
    settings = local_settings()
    if (not settings["enabled"] or not settings.get("auto_translate", True)
            or settings["provider"] != "0" or (not settings["api_key"] and not cloud_ai_available())):
        return str(path)
    return translate_subtitle_file(
        path, Path(profile) / "ai-subtitles", settings["api_key"],
        settings["target"], source_language, progress_callback=progress_callback
    )


def maybe_translate(path, profile, source_language=None, progress_callback=None):
    try:
        settings = local_settings()
        if not settings["enabled"] or not settings.get("auto_translate", True):
            return str(path)
        if settings["provider"] != "0":
            return str(path)  # MKGA hosted generation is wired separately.
        if not settings["api_key"]:
            return str(path)
        return translate_subtitle_file(
            path, Path(profile) / "ai-subtitles", settings["api_key"],
            settings["target"], source_language, progress_callback=progress_callback
        )
    except Exception:
        # Translation is optional. Original subtitles must always keep playback usable.
        return str(path)
