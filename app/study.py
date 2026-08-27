"""Study aids for one sentence of the Thai/Tagalog text: word-by-word
translation (with Thai romanization) and text-to-speech.

Both are produced on demand — the first time someone asks for that sentence —
and cached: word lists in the day's cached content, audio as MP3 files next to
the SQLite database.

* Words: Thai marks every word boundary with U+200B in the source, so the split
  is exact; Tagalog splits on spaces. Each word is translated on its own (no
  context), in one request per sentence.
* Romanization: pythainlp's rule-based RTGS ("royin") — the official Thai
  system; spelling-based and without tones (Google's toned romanization via
  gtx is blocked from both the home and the Cloudflare IPs).
* Speech: Microsoft Edge's neural voices through ``edge-tts`` (free,
  unofficial, like the Google translate endpoints).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

import edge_tts
from pythainlp.transliterate import romanize

import db
from daily_text import ZWSP, _TH_DASH_REF, _strip_parentheticals
from translate import translate_texts

VOICES = {"th": "th-TH-NiwatNeural", "tl": "fil-PH-AngeloNeural"}   # Joel chose male
TTS_DIR = Path(db.DB_PATH).parent / "tts"

_PUNCT = "‘’“”\"'?!.,:;—–…()[]«»"
_HAS_WORD = re.compile(r"\w", re.UNICODE)
_THAI_CHAR = re.compile(r"[฀-๿]")


def split_words(visible: str, lang: str) -> list[str]:
    """The words of a sentence token's visible text, citations left out."""
    text = _TH_DASH_REF.sub("", visible)     # trailing "—1 Ped. 3:4" (themes, Thai)
    text = _strip_parentheticals(text)
    words: list[str] = []
    for part in re.split(rf"[{ZWSP}\s]+", text):
        w = part.strip(_PUNCT)
        if not w or not _HAS_WORD.search(w):
            continue
        if w == "ๆ" and words:            # repetition mark: "จริง ๆ" is one word
            words[-1] += " ๆ"
            continue
        words.append(w)
    return words


# frequent words royin gets wrong (ก็ has an implicit vowel royin can't infer)
_ROM_OVERRIDES = {"ก็": "ko"}


def _romanize_th(word: str) -> str:
    base = word.replace("ๆ", "").strip()
    rom = _ROM_OVERRIDES.get(base)
    if rom is None:
        # royin doesn't know the short-vowel mark ็: drop it, and never let a
        # Thai character leak into the romanization
        rom = _THAI_CHAR.sub("", romanize(base.replace("็", ""), engine="royin"))
    return f"{rom}-{rom}" if "ๆ" in word else rom


def word_entries(visible: str, lang: str) -> list[dict]:
    """``[{"w", "rom", "es"}, ...]`` for a sentence. Raises TranslationError."""
    words = split_words(visible, lang)
    uniq = list(dict.fromkeys(words))
    es = dict(zip(uniq, translate_texts(uniq, lang)))
    return [
        {"w": w, "rom": _romanize_th(w) if lang == "th" else None, "es": es[w]}
        for w in words
    ]


def sentence_parts(visible: str, words: list[str]) -> list[dict]:
    """The sentence as display pieces, so the client can light up word ``k``:
    ``{"s": text, "k": k}`` for a word, ``{"s": text}`` for what's between
    (spaces, punctuation, citations) and ``{"zw": True}`` for a Thai word
    boundary (U+200B), shown as "·" in "mostrar espacios" mode."""
    parts: list[dict] = []

    def gap(s: str) -> None:
        for n, piece in enumerate(s.split(ZWSP)):
            if n:
                parts.append({"zw": True})
            if piece:
                parts.append({"s": piece})

    pos = 0
    for k, w in enumerate(words):
        # "จริง ๆ" may have a U+200B around the space in the source
        m = re.compile(re.escape(w).replace(r"\ ", rf"[\s{ZWSP}]+")).search(visible, pos)
        if not m:
            continue
        gap(visible[pos:m.start()])
        parts.append({"s": m.group(0).replace(ZWSP, ""), "k": k})
        pos = m.end()
    gap(visible[pos:])
    return parts


_NOT_LETTER = re.compile(rf"[\s{ZWSP}{re.escape(_PUNCT)}]")


def align_marks(words: list[str], boundaries: list[list]) -> list[list[int]]:
    """Map the voice's word timings onto our words: ``[[ms, k_first, k_last]]``.
    Its split can differ from wol.jw.org's (it says รู้จัก as one word where the
    source has รู้ + จัก), so both are matched as one character stream and a
    spoken chunk lights up every word it covers."""
    owner: list[int] = []
    stream = ""
    for k, w in enumerate(words):
        n = _NOT_LETTER.sub("", w)
        stream += n
        owner += [k] * len(n)
    marks, pos = [], 0
    for ms, text in boundaries:
        b = _NOT_LETTER.sub("", text)
        j = stream.find(b, pos) if b else -1
        if j < 0:
            continue
        marks.append([ms, owner[j], owner[j + len(b) - 1]])
        pos = j + len(b)
    return marks


async def speech(text: str, lang: str) -> tuple[Path, list[list]]:
    """(MP3 path, word timings ``[[ms, spoken text], ...]``) for ``text`` in
    ``lang`` — synthesized once and kept; the timings live in a .json beside
    the MP3 (older MP3s without one are synthesized again)."""
    voice = VOICES[lang]
    text = text.replace(ZWSP, "")
    name = hashlib.sha1(f"{voice}\n{text}".encode()).hexdigest()
    path, marks_path = TTS_DIR / f"{name}.mp3", TTS_DIR / f"{name}.json"
    if not (path.exists() and marks_path.exists()):
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{name}.{uuid.uuid4().hex}.tmp")
        boundaries = []
        with open(tmp, "wb") as f:
            async for chunk in edge_tts.Communicate(text, voice, boundary="WordBoundary").stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    boundaries.append([round(chunk["offset"] / 10_000), chunk["text"]])
        tmp.replace(path)
        marks_path.write_text(json.dumps(boundaries, ensure_ascii=False), encoding="utf-8")
    return path, json.loads(marks_path.read_text(encoding="utf-8"))
