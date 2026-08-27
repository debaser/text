"""Fetch and parse the Tagalog daily text from wol.jw.org.

The old PHP project split the comment on ``.``/``!``/``?`` and then fought the
Bible citations in parentheses with ad-hoc heuristics. Here we keep the source
text intact but treat the parenthetical citations as their own, non-translated
tokens: they still show exactly as in the original, they just don't become
"sentences" with a tooltip (translating "(Jud. 4)" out of context gave noise).
Segmentation then runs on clean prose.

``segment()`` returns an ordered list of tokens:
  * ``{"t": "s", "tl": <visible Tagalog>, "src": <Tagalog minus parens, to translate>}``
  * ``{"t": "ref", "tl": "(Awit 5:4-6)"}``
"""
from __future__ import annotations

import re
from datetime import date as _date

import httpx
from bs4 import BeautifulSoup

URL_BASE = "https://wol.jw.org/tl/wol/h/r27/lp-tg/"
URL_BASE_TH = "https://wol.jw.org/th/wol/h/r113/lp-si/"
URL_BASE_ES = "https://wol.jw.org/es/wol/h/r4/lp-s/"   # official Spanish edition
SOURCE_LANGUAGE = "tl"
TARGET_LANGUAGE = "es"

# Parenthetical "(...)" spans in the comment are Bible citations. They are always
# shown verbatim; this only controls whether they are also translated. Keeping
# them in the translated sentence produced garbage (e.g. "Jud." -> "Jueces"), so
# by default they ride along as separate, untranslated tokens.
TRANSLATE_PARENTHETICALS = False

_UA = "Mozilla/5.0 (compatible; text/2.0; +https://text.joelgoncalves.es)"

# zero-width space / non-joiner / joiner / word-joiner / BOM
_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
_ASCII_WS = re.compile(r"[ \t\r\n\f\v]+")          # collapse, but keep U+00A0
_PARENS = re.compile(r"\s*\([^()]*\)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?…”’)\]])")
_SPACE_AFTER_OPEN = re.compile(r"([“‘(\[¡¿])\s+")

# A sentence boundary: terminal punctuation, then any trailing closing quotes or
# brackets, then whitespace, then something that can start a new sentence
# (an opening quote/bracket, a digit, or an uppercase — incl. accented — letter).
_BOUNDARY = re.compile(
    r'(?<=[.!?…])(?P<tail>[”’"\')\]]*)\s+(?=[«"“‘¡¿(\[]|\d|[A-ZÁÉÍÓÚÜÑ])'
)
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_PAREN_TOKEN = re.compile(r"(\([^()]*\))")
_ENDS_SENTENCE = re.compile(r"""[.!?…]["”’')\]]*\s*$""")


class DailyTextError(RuntimeError):
    """Raised when the page can't be fetched or the expected markup is missing."""


ZWSP = "​"   # Thai marks word boundaries with it — kept for "mostrar espacios"
_ZERO_WIDTH_BUT_ZWSP = re.compile("[‌‍⁠﻿]")


def _clean(text: str, keep_zwsp: bool = False) -> str:
    text = (_ZERO_WIDTH_BUT_ZWSP if keep_zwsp else _ZERO_WIDTH).sub("", text or "")
    text = _ASCII_WS.sub(" ", text)
    return text.strip()


def fetch_html(day: _date, base: str = URL_BASE) -> str:
    url = base + day.strftime("%Y/%m/%d")
    try:
        resp = httpx.get(url, headers={"User-Agent": _UA}, timeout=20.0,
                         follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise DailyTextError(f"No se pudo descargar {url}: {exc}") from exc
    return resp.text


def parse_fields(html: str, segmenter=None, keep_zwsp: bool = False) -> dict:
    """Extract date / theme text / comment sentences from the day's block.

    wol.jw.org renders three ``div.tabContent`` blocks (previous / current /
    next day). We want the second one.
    """
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all("div", class_="tabContent")
    if len(blocks) < 2:
        raise DailyTextError("No se encontraron suficientes bloques tabContent")
    node = blocks[1]

    date_node = node.select_one("header h2") or node.find("h2")
    date_txt = _clean(date_node.get_text(), keep_zwsp) if date_node else ""

    text_node = node.find("p", class_="themeScrp")
    text_txt = _tidy(_clean(text_node.get_text(), keep_zwsp)) if text_node else ""

    comment_node = node.find("div", class_="bodyTxt")
    if comment_node is not None:
        # Remove the trailing study-article reference ("w24.09 27 ¶6-7"):
        # wol.jw.org marks it with a /wol/pc/ ("publication citation") link.
        # Inline scripture links use /wol/bc/ and are left in place.
        for ref in comment_node.select('a[href*="/wol/pc/"]'):
            ref.decompose()
        comment_full = _clean(comment_node.get_text(), keep_zwsp)
    else:
        comment_full = ""

    if not (date_txt and text_txt and comment_full):
        raise DailyTextError("El bloque del día no tiene la estructura esperada")

    return {
        "date": date_txt,
        "text": text_txt,
        "comment_full": comment_full,
        "comment": (segmenter or segment)(comment_full),
    }


def fetch_official_es(day: _date) -> dict:
    """The same day's text from the official Spanish edition — shown as-is
    (plain text, no segmentation/translation) in the Spanish view."""
    f = parse_fields(fetch_html(day, URL_BASE_ES))
    return {"date": f["date"], "text": f["text"], "comment": f["comment_full"]}


def fetch_th(day: _date) -> dict:
    """The same day's text in Thai, segmented for per-chunk tooltips."""
    return parse_fields(fetch_html(day, URL_BASE_TH), segmenter=segment_th, keep_zwsp=True)


# --------------------------------------------------------------------------- #
# Sentence segmentation
# --------------------------------------------------------------------------- #

def _tidy(text: str) -> str:
    """Normalise spacing around punctuation left behind after edits."""
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN.sub(r"\1", text)
    text = _ASCII_WS.sub(" ", text)
    # a stray opening bracket with nothing to close it, or the reverse
    text = re.sub(r"\(\s*\)", "", text)
    return text.strip()


def _strip_parentheticals(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = _PARENS.sub("", text)
    return text


def _raw_segment(text: str) -> list[str]:
    """Split a run of prose into sentences, never breaking inside a "(...)"."""
    spans = [(m.start(), m.end()) for m in re.finditer(r"\([^()]*\)", text)]
    inside = lambda pos: any(a <= pos < b for a, b in spans)

    sentences: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        if inside(m.start()):
            continue
        end = m.start() + len(m.group("tail"))
        seg = text[start:end].strip()
        if seg:
            sentences.append(seg)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _sentence_token(visible: str) -> dict:
    visible = visible.strip()
    src = _tidy(_strip_parentheticals(visible))
    return {"t": "s", "tl": visible, "src": src}


def _merge_tokens(tokens: list[dict]) -> list[dict]:
    """Fold a letter-less / tiny sentence token into the sentence before it."""
    out: list[dict] = []
    for tok in tokens:
        if (
            tok["t"] == "s"
            and out
            and out[-1]["t"] == "s"
            and (not _HAS_LETTER.search(tok["src"]) or len(tok["src"]) < 3)
        ):
            out[-1]["tl"] = f'{out[-1]["tl"]} {tok["tl"]}'.strip()
            out[-1]["src"] = f'{out[-1]["src"]} {tok["src"]}'.strip()
        else:
            out.append(tok)
    return out


def segment(comment_full: str) -> list[dict]:
    text = _tidy(comment_full)

    if TRANSLATE_PARENTHETICALS:
        return _merge_tokens([_sentence_token(s) for s in _raw_segment(text)])

    tokens: list[dict] = []
    carry = ""  # an unfinished sentence waiting for the text after a "(...)"
    for part in _PAREN_TOKEN.split(text):
        if not part:
            continue
        if part[0] == "(" and part[-1] == ")":
            ref = part.strip()
            if carry:                       # citation sits mid-sentence: keep it there
                carry = f"{carry} {ref}".strip()
            else:
                tokens.append({"t": "ref", "tl": ref})
            continue
        chunk = f"{carry}{part}" if carry else part
        carry = ""
        sents = _raw_segment(chunk)
        for i, s in enumerate(sents):
            if i == len(sents) - 1 and not _ENDS_SENTENCE.search(s):
                carry = s                   # finished by a later chunk
            else:
                tokens.append(_sentence_token(s))
    if carry:
        tokens.append(_sentence_token(carry))

    return _merge_tokens(tokens)


# --------------------------------------------------------------------------- #
# Thai segmentation
# --------------------------------------------------------------------------- #
# Thai has no sentence punctuation and no spaces between words: a space marks
# the end of a sentence *or* of a clause/list item. So we split on spaces and
# then glue back the pieces that are obviously not standalone:
#   * never around the repetition mark ๆ ("จริง ๆ", "ดี ๆ" are one word);
#   * never inside a "(...)" citation — those become untranslated ref tokens;
#   * nor inside a trailing "—<citation>";
#   * a piece starting with และ ("and") / หรือ ("or"), or that is just a quoted
#     term (“...”), continues the previous one;
#   * a short piece ("เช่น" = "for example", an intro phrase, a lone list item)
#     joins the next.
# The result is sentence-or-clause chunks — the finest unit that still
# translates sensibly on its own.

_TH_JOIN_PREV = ("และ", "หรือ")
_TH_MIN_CHUNK = 20                                    # characters
# trailing "—รม. 15:4; 2 ทธ. 3:16": a dash-introduced citation at the end
_TH_DASH_REF = re.compile(r"—[^—]*\d+:\d+[^—]*$")


def _th_pieces(text: str) -> list[str]:
    spans = [(m.start(), m.end()) for m in re.finditer(r"\([^()]*\)", text)]
    spans += [(m.start(), m.end()) for m in _TH_DASH_REF.finditer(text)]
    inside = lambda pos: any(a < pos < b for a, b in spans)
    pieces, start = [], 0
    for m in re.finditer(r" +", text):
        a, b = m.start(), m.end()
        if inside(a) or (a > 0 and text[a - 1] == "ๆ") or text[b:b + 1] == "ๆ":
            continue
        pieces.append(text[start:a])
        start = b
    pieces.append(text[start:])
    return [p for p in pieces if p]


def _th_token(visible: str) -> dict:
    src = _TH_DASH_REF.sub("", visible).replace(ZWSP, "")
    src = _tidy(_strip_parentheticals(src))
    return {"t": "s", "tl": visible, "src": src}


def segment_th(comment_full: str) -> list[dict]:
    """Thai counterpart of ``segment()``; same token format (``"tl"`` holds the
    visible source text whatever the language). ``" ".join`` of the visible
    texts reproduces the source exactly."""
    tokens: list = []                       # ref dicts and runs (lists) of prose pieces
    for piece in _th_pieces(_clean(comment_full, keep_zwsp=True)):
        if piece.startswith("(") and piece.endswith(")"):
            tokens.append({"t": "ref", "tl": piece})
            continue
        if not tokens or not isinstance(tokens[-1], list):
            tokens.append([])
        tokens[-1].append(piece)

    out: list[dict] = []
    for item in tokens:
        if isinstance(item, dict):
            out.append(item)
            continue
        merged: list[str] = []
        pending = ""                        # a short piece waiting for the next one
        for piece in item:
            if pending:
                piece, pending = f"{pending} {piece}", ""
            if merged and (
                piece.startswith(_TH_JOIN_PREV)
                or (piece.startswith("“") and piece.endswith("”"))   # a quoted term
            ):
                merged[-1] = f"{merged[-1]} {piece}"
            elif len(piece.replace(ZWSP, "")) < _TH_MIN_CHUNK:
                pending = piece
            else:
                merged.append(piece)
        if pending:
            if merged:
                merged[-1] = f"{merged[-1]} {pending}"
            else:
                merged.append(pending)
        out.extend(_th_token(p) for p in merged)
    return out
