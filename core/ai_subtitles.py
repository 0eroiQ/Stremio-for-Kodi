"""Free BYOK Gemini subtitle translation for Stremio for Kodi.

The viewer's Gemini key stays in Kodi add-on settings and is sent only to
Google's Generative Language API. Vortexo Premium hosted translation is a
separate future path and is never silently substituted here.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError
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
MAX_CUES = 2000
MAX_CUE_TEXT = 8000
TIMEOUT_SECONDS = 45
TRANSLATION_REVISION = "byok-v1"
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


def _request_translation(cues, api_key, target_language, source_language=None, opener=None):
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
    for model in MODEL_CHAIN:
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
            return _decode_translations(_gemini_text(payload), cues)
        except HTTPError as error:
            last_error = error
            if error.code in (404, 408, 429, 500, 502, 503, 504):
                continue
            break
        except (AITranslationError, ValueError) as error:
            last_error = error
            break
        except Exception as error:
            last_error = error
            continue
    raise AITranslationError("AI subtitle translation is temporarily unavailable.") from last_error


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
def translate_subtitle_file(path, cache_directory, api_key, target_language,
                            source_language=None, opener=None):
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
        return str(destination)

    content = data.decode("utf-8-sig", errors="replace")
    blocks, cues = _parse_timed_text(content)
    translations = _request_translation(
        cues, api_key.strip(), target_language, source_language, opener=opener
    )
    atomic_write(destination, _rebuild(blocks, cues, translations).encode("utf-8"))
    return str(destination)


def maybe_translate(path, profile, source_language=None):
    try:
        from addon_state import get_addon
        addon = get_addon()
        if addon.getSetting("ai_subtitles_enabled").strip().lower() != "true":
            return str(path)
        provider = addon.getSetting("ai_subtitles_provider").strip() or "0"
        if provider != "0":
            return str(path)  # Vortexo Premium hosted AI is still in construction.
        api_key = addon.getSetting("ai_subtitles_gemini_api_key").strip()
        if not api_key:
            return str(path)
        target = target_code(addon.getSetting("ai_subtitles_target"))
        return translate_subtitle_file(
            path, Path(profile) / "ai-subtitles", api_key, target, source_language
        )
    except Exception:
        # Translation is optional. Original subtitles must always keep playback usable.
        return str(path)
