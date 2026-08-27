"""Translation backend, pluggable and parallel.

Default chases Google's free endpoint first (deep-translator, no key, no
cost — same as the old PHP project). Google periodically IP-blocks that
endpoint (a 429 "Sorry..." page, not a per-request rate limit — a single lone
call fails exactly like a burst of five). When that happens the second no-key
endpoint (clients5, the Chrome extension's) is tried, which is limited
separately; then the same endpoints via our Cloudflare Worker, so the request
leaves from a Cloudflare IP instead of the home one. Only if all of those are
blocked does the whole batch fall back to the official Google Cloud Translation API (needs a key via
GOOGLE_TRANSLATE_API_KEY) and the free endpoint isn't tried again until the
next UTC day — retrying a blocked IP mid-batch or on every later request just
wastes time. DeepL is not an option here: it doesn't support Tagalog as a
source language. (Azure Translator was tried first but its free F0 tier
wasn't accepting new sign-ups on Joel's subscription.)
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from deep_translator import GoogleTranslator

from daily_text import SOURCE_LANGUAGE, TARGET_LANGUAGE

_RETRIES = 2
_BACKOFF = 1.0          # seconds * attempt number
_MAX_WORKERS = 5        # parallel calls on a cache miss


class TranslationError(RuntimeError):
    pass


class GoogleFreeBackend:
    """The unofficial, no-key translate.google.com endpoint — gets IP-blocked
    from time to time."""

    name = "google_free"

    def translate(self, text: str, sl: str) -> str:
        return GoogleTranslator(
            source=sl, target=TARGET_LANGUAGE
        ).translate(text) or ""


class GoogleClients5Backend:
    """Another no-key Google endpoint (the one the Chrome dictionary extension
    uses). It's rate-limited separately from translate.google.com, so it keeps
    working while the main free endpoint has us IP-blocked."""

    name = "google_clients5"

    def translate(self, text: str, sl: str) -> str:
        resp = httpx.get(
            "https://clients5.google.com/translate_a/t",
            params={
                "client": "dict-chrome-ex",
                "sl": sl,
                "tl": TARGET_LANGUAGE,
                "q": text,
            },
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # Shape varies: ["text"] or [["text", "src_lang"]].
        first = data[0]
        return first[0] if isinstance(first, list) else first


class WorkerProxyBackend:
    """Same no-key Google endpoints, but called from our Cloudflare Worker
    (worker/worker.js) so the request leaves from Cloudflare's IPs instead of
    the home one. Needs TEXT_PROXY_URL + TEXT_PROXY_KEY."""

    name = "worker_proxy"
    # Cloudflare's egress IP changes between requests and only some of them
    # are blocked by Google (~half in testing), so retrying pays off and a
    # failure doesn't mean it's blocked for the day.
    retries = 8
    rotating = True

    def __init__(self) -> None:
        self.url = os.environ.get("TEXT_PROXY_URL", "")
        self.key = os.environ.get("TEXT_PROXY_KEY", "")

    def available(self) -> bool:
        return bool(self.url and self.key)

    def translate(self, text: str, sl: str) -> str:
        resp = httpx.post(
            self.url,
            json={"q": text, "sl": sl, "tl": TARGET_LANGUAGE},
            headers={"X-Proxy-Key": self.key},
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.json()["text"]


class GoogleCloudBackend:
    """Official Google Cloud Translation API (Basic/v2). Needs
    GOOGLE_TRANSLATE_API_KEY."""

    name = "google_cloud"

    def __init__(self) -> None:
        self.key = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "")

    def available(self) -> bool:
        return bool(self.key)

    def translate(self, text: str, sl: str) -> str:
        resp = httpx.post(
            "https://translation.googleapis.com/language/translate/v2",
            params={"key": self.key},
            json={
                "q": text,
                "source": sl,
                "target": TARGET_LANGUAGE,
                "format": "text",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()["data"]["translations"][0]["translatedText"]


# Free (no-key) backends, tried in order; the Worker only when configured.
_free_backends = [
    b for b in (GoogleFreeBackend(), GoogleClients5Backend(), WorkerProxyBackend())
    if getattr(b, "available", lambda: True)()
]
_fallback = GoogleCloudBackend()

# Once Google IP-blocks an endpoint it stays blocked for hours — a lone probe
# fails just like a burst does, so there's no point re-trying it before the
# next day. Keyed by backend name.
_blocked_on: dict[str, str] = {}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _is_available(backend) -> bool:
    return _blocked_on.get(backend.name) != _today()


def _mark_blocked(backend) -> None:
    if not getattr(backend, "rotating", False):
        _blocked_on[backend.name] = _today()


def _call_with_retries(backend, text: str, sl: str) -> str:
    last_exc: Exception | None = None
    retries = getattr(backend, "retries", _RETRIES)
    rotating = getattr(backend, "rotating", False)
    for attempt in range(1, retries + 1):
        try:
            return backend.translate(text, sl) or ""
        except Exception as exc:  # deep-translator/httpx raise a grab-bag of types
            last_exc = exc
            if attempt < retries:
                time.sleep(0.5 if rotating else _BACKOFF * attempt)
    raise last_exc  # type: ignore[misc]


_BATCH_MAX_CHARS = 4500  # deep-translator refuses > 5000


def _translate_batch(items: list[str], on_stage, sl: str) -> list[str] | None:
    """Translate the whole day in ONE request (lines joined with "\\n") — one
    call a day instead of a dozen keeps us well clear of Google's IP blocks.
    Returns None when that isn't possible (every free backend blocked, or the
    answer came back with lines merged/split) so the caller goes per-item.
    """
    joined = "\n".join(items)
    if any("\n" in t for t in items) or len(joined) > _BATCH_MAX_CHARS:
        return None
    for backend in _free_backends:
        if not _is_available(backend):
            continue
        if on_stage:
            on_stage("translate_google")
        try:
            out = _call_with_retries(backend, joined, sl).split("\n")
        except Exception:
            _mark_blocked(backend)
            continue
        if len(out) == len(items):
            return [line.strip() for line in out]
        return None  # backend works but mangled the lines: per-item with it
    return None


def _translate_first(text: str, on_stage, sl: str) -> tuple[str, object]:
    """Translate the first item, which doubles as today's probe: decide (and
    pin) the backend for the rest of the batch. Returns (translation, backend).
    """
    for backend in _free_backends:
        if not _is_available(backend):
            continue
        if on_stage:
            on_stage("translate_google")
        try:
            return _call_with_retries(backend, text, sl), backend
        except Exception:
            _mark_blocked(backend)

    if not _fallback.available():
        raise TranslationError(
            "Google (gratuito) no disponible y no hay backend de reserva configurado "
            "(falta GOOGLE_TRANSLATE_API_KEY)"
        )
    if on_stage:
        on_stage("translate_google_cloud")
    try:
        return _call_with_retries(_fallback, text, sl), _fallback
    except Exception as exc:
        raise TranslationError(f"Fallo al traducir con Google Cloud: {exc}") from exc


def _translate_rest(texts: list[str], backend, sl: str) -> list[str]:
    def one(t: str) -> str:
        t = (t or "").strip()
        if not t:
            return ""
        try:
            return _call_with_retries(backend, t, sl)
        except Exception as exc:
            raise TranslationError(f"Fallo al traducir con {backend.name}: {exc}") from exc

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        return list(pool.map(one, texts))


def translate_content(content: dict, on_stage=None, source: str = SOURCE_LANGUAGE) -> dict:
    """Fill in translations for a parsed daily text.

    Normally the whole day goes out as a single request. If that can't be
    done, the first item pins the backend (Google, or Google Cloud on
    fallback) for the rest, which then runs concurrently. Mutates the ``"s"`` comment tokens in place
    to add an ``"es"`` field; returns just the date/theme translations.

    ``on_stage(stage)`` — one of ``"translate_google"``/``"translate_google_cloud"``
    — is called once the backend for this batch is decided, so callers can
    surface progress to the user.
    """
    s_tokens = [tok for tok in content["comment"] if tok["t"] == "s"]
    items = [content["date"], content["text"], *[tok["src"] for tok in s_tokens]]
    out = translate_texts(items, source, on_stage)

    for tok, es in zip(s_tokens, out[2:]):
        tok["es"] = es
    return {"date": out[0], "text": out[1]}


def translate_texts(items: list[str], source: str, on_stage=None) -> list[str]:
    """Translate a list of texts to Spanish, in one request when possible.
    Raises TranslationError when every backend is down."""
    items = [t.replace("​", "") for t in items]   # Thai word-boundary marks
    if not items:
        return []
    out = _translate_batch(items, on_stage, source)
    if out is None:
        first, backend = _translate_first(items[0], on_stage, source)
        rest = _translate_rest(items[1:], backend, source) if len(items) > 1 else []
        out = [first, *rest]
    return out
