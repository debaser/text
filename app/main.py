"""text — Tagalog daily text with per-sentence Spanish tooltips.

Flow: fetch the day's page from wol.jw.org -> drop parenthetical citations and
segment the Tagalog comment into sentences -> translate each sentence tl->es
(free Google backend, parallel) -> store in SQLite (cache + view counter) ->
render the Tagalog text with each sentence's translation in a tooltip. The
official Spanish edition of the same day is fetched too, for the language
toggle (plain text, no tooltips).
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.requests import Request

import db
import progress
from daily_text import DailyTextError, fetch_html, fetch_official_es, fetch_th, parse_fields
from study import align_marks, sentence_parts, speech, split_words, word_entries
from translate import TranslationError, translate_content

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("text")

TZ = ZoneInfo("Europe/Madrid")
STATIC = Path(__file__).parent / "static"

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("application/manifest+json", ".webmanifest")


def _static_version() -> str:
    """Short hash of the cacheable assets, used as a ?v= cache-buster so a
    deploy is never shadowed by a stale CDN copy."""
    h = hashlib.sha1()
    for name in ("main.css", "app.js", "sw.js", "manifest.webmanifest"):
        p = STATIC / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


STATIC_VER = _static_version()

app = FastAPI(title="text", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["v"] = STATIC_VER

_ZW_MARK = Markup('<span class="zw" aria-hidden="true"></span>​')


def _zw(text: str | None) -> Markup:
    """Escape ``text`` and put a (hidden by default) marker at each Thai word
    boundary (U+200B), for the "mostrar espacios" option. The marker goes
    before the U+200B so a line break there leaves it at the end of the line."""
    return _ZW_MARK.join(escape(p) for p in (text or "").split("​"))


templates.env.filters["zw"] = _zw


def today_str() -> str:
    return datetime.now(TZ).date().isoformat()


def _normalize_date(value: str | None) -> str:
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return today_str()


def _nav(date_str: str) -> dict:
    d = date.fromisoformat(date_str)
    tstr = today_str()
    return {
        "date_str": date_str,
        "prev_date": (d - timedelta(days=1)).isoformat(),
        "next_date": (d + timedelta(days=1)).isoformat(),
        "today": tstr,
        "is_today": date_str == tstr,
    }


def _build(date_str: str) -> dict:
    """Return the day's content, from cache or freshly fetched+translated.

    The cached content is the Tagalog day (top-level keys, the original
    format) plus ``th`` (Thai, same shape) and ``es`` (official Spanish, plain).
    Only the Tagalog fetch is fatal; a missing translation, Thai or Spanish
    part still shows what we have and is filled in on a later view.
    """
    content = db.get_content(date_str)
    if content is None:
        try:
            progress.set_stage(date_str, "fetch")
            day = date.fromisoformat(date_str)
            fields = parse_fields(fetch_html(day))
            _translate_into(date_str, fields, "tl")
            fields["th"] = _fetch_th(date_str)
            fields["es"] = _fetch_es(date_str)
            db.save_content(date_str, fields)
            n_s = sum(1 for t in fields["comment"] if t["t"] == "s")
            n_ref = sum(1 for t in fields["comment"] if t["t"] == "ref")
            log.info("built %s (%d sentences, %d refs)", date_str, n_s, n_ref)
            return fields
        finally:
            progress.clear(date_str)
    log.info("cache hit %s", date_str)
    if not _complete(content):
        _fill_in(date_str, content)
    return content


def _translate_into(date_str: str, block: dict, source: str) -> bool:
    """Translate one language block in place (tokens get ``es``; the block
    gets ``translations`` + ``translation_available``). False if every
    backend is down — the untranslated text is still worth showing."""
    try:
        block["translations"] = translate_content(
            block, on_stage=lambda s: progress.set_stage(date_str, s), source=source
        )
        block["translation_available"] = True
    except TranslationError as exc:
        log.warning("%s translation unavailable for %s: %s", source, date_str, exc)
        block["translations"] = block.get("translations") or {"date": "", "text": ""}
        block["translation_available"] = False
    finally:
        progress.clear(date_str)
    return block["translation_available"]


def _fetch_th(date_str: str) -> dict | None:
    try:
        th = fetch_th(date.fromisoformat(date_str))
    except DailyTextError as exc:
        log.warning("Thai text unavailable for %s: %s", date_str, exc)
        return None
    _translate_into(date_str, th, "th")
    return th


def _fetch_es(date_str: str) -> dict | None:
    try:
        return fetch_official_es(date.fromisoformat(date_str))
    except DailyTextError as exc:
        log.warning("official Spanish text unavailable for %s: %s", date_str, exc)
        return None


def _complete(content: dict) -> bool:
    """Every part is in: Tagalog + Thai, both translated, and the Spanish."""
    th = content.get("th")
    return (
        content.get("translation_available", True)
        and bool(th) and th.get("translation_available", True)
        and bool(content.get("es"))
    )


def _fill_in(date_str: str, content: dict) -> None:
    """Complete a cached day: cached before Thai/Spanish existed, or saved
    while a backend or wol.jw.org was down. Cheap when still down — blocked
    translation backends are skipped for the rest of the UTC day."""
    changed = False
    if not content.get("translation_available", True):
        changed |= _translate_into(date_str, content, "tl")
    if not content.get("th"):
        content["th"] = _fetch_th(date_str)
        changed |= content["th"] is not None
    elif not content["th"].get("translation_available", True):
        changed |= _translate_into(date_str, content["th"], "th")
    if not content.get("es"):
        content["es"] = _fetch_es(date_str)
        changed |= content["es"] is not None
    if changed:
        db.save_content(date_str, content)
        log.info("filled in missing parts of %s", date_str)


def _lang_ctx(block: dict | None) -> dict | None:
    """Template view of one segmented language block (Tagalog or Thai)."""
    if not block:
        return None
    tr = block.get("translations") or {"date": "", "text": ""}
    return {
        "date": block["date"],
        "date_es": tr["date"],
        "text": block["text"],
        "text_es": tr["text"],
        "tokens": block["comment"],
        "translated": block.get("translation_available", True),
    }


LANG_COOKIE = "lang"   # last language viewed, set by app.js


def _view_ctx(content: dict, hits: int, request: Request) -> dict:
    th, tl = _lang_ctx(content.get("th")), _lang_ctx(content)
    es = content.get("es")
    available = [code for code, v in (("th", th), ("tl", tl), ("es", es)) if v]
    pref = request.cookies.get(LANG_COOKIE)
    return {
        "error": False,
        "th": th,
        "tl": tl,
        "es": es,
        # the viewer's last language if this day has it, else Thai
        "default_lang": pref if pref in available else available[0],
        "hits": hits,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, date: str | None = Query(default=None)):
    date_str = _normalize_date(date)
    ctx: dict = {"request": request, **_nav(date_str)}

    cached = db.get_content(date_str)
    if cached is not None and not _complete(cached):
        cached = _build(date_str)  # fills in whatever is missing
    if cached is not None:
        # Render the content straight into the page — no fetch round-trip,
        # no loading flash for a day that's already been seen.
        ctx.update(_view_ctx(cached, db.record_view(date_str), request))
        ctx["prerendered"] = True
    else:
        ctx["prerendered"] = False
    return templates.TemplateResponse("index.html", ctx)


# Tells the service worker not to keep this response (error card, or a day
# missing its translation or official Spanish text) — past days are otherwise
# cached forever.
_INCOMPLETE = {"X-Text-Incomplete": "1"}


@app.get("/fragment", response_class=HTMLResponse)
def fragment(request: Request, date: str | None = Query(default=None)):
    date_str = _normalize_date(date)
    ctx: dict = {"request": request, **_nav(date_str)}
    try:
        content = _build(date_str)
    except DailyTextError as exc:
        log.warning("fragment %s failed: %s", date_str, exc)
        ctx["error"] = True
        return templates.TemplateResponse("_content.html", ctx, status_code=200, headers=_INCOMPLETE)
    ctx.update(_view_ctx(content, db.record_view(date_str), request))
    headers = {} if _complete(content) else _INCOMPLETE
    return templates.TemplateResponse("_content.html", ctx, headers=headers)


@app.get("/api/day")
def api_day(date: str | None = Query(default=None)):
    date_str = _normalize_date(date)
    try:
        content = _build(date_str)
    except DailyTextError as exc:
        return JSONResponse({"error": str(exc), "date": date_str}, status_code=502)
    hits = db.record_view(date_str)
    th = content.get("th")
    return JSONResponse(
        {
            "date": date_str,
            "th": th and {
                "heading": {"th": th["date"], "es": th["translations"]["date"]},
                "theme": {"th": th["text"], "es": th["translations"]["text"]},
                "comment": th["comment"],
                "translation_available": th.get("translation_available", True),
            },
            "heading": {"tl": content["date"], "es": content["translations"]["date"]},
            "theme": {"tl": content["text"], "es": content["translations"]["text"]},
            "comment": content["comment"],
            "sentences": [t for t in content["comment"] if t["t"] == "s"],
            "hits": hits,
            "translation_available": content.get("translation_available", True),
            "official_es": content.get("es"),
        },
        headers={} if _complete(content) else _INCOMPLETE,
    )


@app.get("/api/progress", include_in_schema=False)
def api_progress(date: str | None = Query(default=None)):
    date_str = _normalize_date(date)
    return {"message": progress.get_message(date_str)}


def _sentence(date_str: str, lang: str, i: int) -> tuple[dict, dict, dict]:
    """(content, language block, sentence token) for a cached day, or 404.
    ``i == -1`` is the theme scripture."""
    content = db.get_content(date_str)
    block = (content.get("th") if lang == "th" else content) if content else None
    if i == -1 and block:
        return content, block, {"t": "s", "tl": block["text"], "src": block["text"]}
    tokens = block["comment"] if block else []
    if not (0 <= i < len(tokens)) or tokens[i]["t"] != "s":
        raise HTTPException(status_code=404)
    return content, block, tokens[i]


@app.get("/api/words")
def api_words(date: str, lang: Literal["th", "tl"], i: int):
    """Word-by-word translation of sentence ``i``; computed once, then cached."""
    date_str = _normalize_date(date)
    content, block, tok = _sentence(date_str, lang, i)   # i == -1: the theme
    cache = block.setdefault("words", {})
    if str(i) not in cache:
        try:
            cache[str(i)] = word_entries(tok["tl"], lang)
        except TranslationError as exc:
            log.warning("word translation unavailable for %s %s #%d: %s", date_str, lang, i, exc)
            return JSONResponse({"error": "translation unavailable"}, status_code=503)
        db.save_content(date_str, content)
    words = cache[str(i)]
    return {"words": words, "parts": sentence_parts(tok["tl"], [x["w"] for x in words])}


@app.get("/api/tts")
async def api_tts(date: str, lang: Literal["th", "tl"], i: int, w: int | None = None):
    """MP3 of sentence ``i`` (or of its word ``w``)."""
    date_str = _normalize_date(date)
    _, _, tok = _sentence(date_str, lang, i)
    if w is None:
        text = tok["src"]
    else:
        words = split_words(tok["tl"], lang)
        if not (0 <= w < len(words)):
            raise HTTPException(status_code=404)
        text = words[w].replace(" ๆ", "ๆ")
    try:
        path, _ = await speech(text, lang)
    except Exception as exc:  # edge-tts raises a grab-bag (network, protocol)
        log.warning("speech unavailable for %s %s #%d: %s", date_str, lang, i, exc)
        return JSONResponse({"error": "speech unavailable"}, status_code=503)
    return FileResponse(path, media_type="audio/mpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/marks")
async def api_marks(date: str, lang: Literal["th", "tl"], i: int):
    """When each word of sentence ``i`` is spoken in its audio: ``[[ms, k_first,
    k_last], ...]`` (word indexes as in /api/words), to light them up in sync."""
    date_str = _normalize_date(date)
    _, _, tok = _sentence(date_str, lang, i)   # i == -1: the theme
    try:
        _, boundaries = await speech(tok["src"], lang)
    except Exception as exc:
        log.warning("speech unavailable for %s %s #%d: %s", date_str, lang, i, exc)
        return JSONResponse({"error": "speech unavailable"}, status_code=503)
    return {"marks": align_marks(split_words(tok["tl"], lang), boundaries)}


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    body = (STATIC / "sw.js").read_text(encoding="utf-8").replace("%VER%", STATIC_VER)
    return Response(
        body,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
