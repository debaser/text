"""In-memory progress reporting for the synchronous cold-fetch path, so the
frontend can show what's happening ("downloading", "translating with
Google/Azure") instead of a bare spinner during a slow cache miss.

Single-process, single-user app — a plain dict keyed by date is enough; no
locking, no persistence.
"""
from __future__ import annotations

MESSAGES = {
    "fetch": "Descargando el texto de wol.jw.org…",
    "translate_google": "Traduciendo con Google…",
    "translate_google_cloud": "Google no disponible, traduciendo con Google Cloud Translation…",
}

_stages: dict[str, str] = {}


def set_stage(date_str: str, stage: str) -> None:
    _stages[date_str] = stage


def get_message(date_str: str) -> str:
    stage = _stages.get(date_str)
    return MESSAGES.get(stage, "") if stage else ""


def clear(date_str: str) -> None:
    _stages.pop(date_str, None)
