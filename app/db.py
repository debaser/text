"""SQLite-backed cache for the daily text.

One row per calendar date: the fully-parsed + translated payload as JSON, plus
a view counter. This replaces the old MariaDB table `dailytext(date, content
[php-serialized], hits)`.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(os.environ.get("TEXT_DB", "/app/data/text.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_text (
    date       TEXT PRIMARY KEY,          -- YYYY-MM-DD
    content    TEXT NOT NULL,             -- JSON: {date, text, comment[], translations{...}}
    hits       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
    return _conn


def get_content(date: str) -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT content FROM daily_text WHERE date = ?", (date,)
        ).fetchone()
    return json.loads(row["content"]) if row else None


def save_content(date: str, content: dict) -> None:
    payload = json.dumps(content, ensure_ascii=False)
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO daily_text (date, content) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET content = excluded.content, "
            "updated_at = datetime('now')",
            (date, payload),
        )
        conn.commit()


def record_view(date: str) -> int:
    """Increment and return the view counter for a date (row must exist)."""
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE daily_text SET hits = hits + 1 WHERE date = ?", (date,)
        )
        conn.commit()
        row = conn.execute(
            "SELECT hits FROM daily_text WHERE date = ?", (date,)
        ).fetchone()
    return row["hits"] if row else 0
