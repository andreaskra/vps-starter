"""SQLite storage: editable settings, leads, runs, connected domains."""
import os
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    domain       TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    url          TEXT NOT NULL,
    snippet      TEXT DEFAULT '',
    score        INTEGER,
    reason       TEXT DEFAULT '',
    source_query TEXT DEFAULT '',
    run_id       INTEGER,
    notion_ok    INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    queries     INTEGER DEFAULT 0,
    found       INTEGER DEFAULT 0,
    new         INTEGER DEFAULT 0,
    message     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS domains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT UNIQUE NOT NULL,
    include_www INTEGER DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL
);
"""

# settings the dashboard may read/write, with defaults
SETTING_DEFAULTS = {
    "tavily_api_key": "",
    "anthropic_api_key": "",
    "notion_token": "",
    "notion_parent_page": "",
    "notion_db_id": "",           # cached, created on first run
    "certbot_email": "",
    "icp_description": "",
    "run_hour": "2",              # server time (UTC on a fresh VPS)
    "max_queries": "6",
    "max_new_leads": "15",
    "model": "claude-opus-4-8",
    "last_auto_run_date": "",
}

SECRET_SETTINGS = {"tavily_api_key", "anthropic_api_key", "notion_token"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def init() -> None:
    global _conn
    os.makedirs(config.DATA_DIR, exist_ok=True)
    _conn = sqlite3.connect(
        os.path.join(config.DATA_DIR, "leadfinder.db"), check_same_thread=False
    )
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(SCHEMA)
        # a container restart mid-run leaves a 'running' row behind — close it
        _conn.execute(
            "UPDATE runs SET status='aborted', finished_at=? WHERE status='running'",
            (now(),),
        )
        _conn.commit()


def _c() -> sqlite3.Connection:
    assert _conn is not None, "db.init() not called"
    return _conn


# ---- settings ----

def get_setting(key: str) -> str:
    with _lock:
        row = _c().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else SETTING_DEFAULTS.get(key, "")


def set_setting(key: str, value: str) -> None:
    with _lock:
        _c().execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        _c().commit()


def all_settings() -> dict:
    return {k: get_setting(k) for k in SETTING_DEFAULTS}


# ---- leads ----

def lead_domains() -> set[str]:
    with _lock:
        rows = _c().execute("SELECT domain FROM leads").fetchall()
    return {r["domain"] for r in rows}


def insert_lead(lead: dict) -> int:
    with _lock:
        cur = _c().execute(
            "INSERT INTO leads(domain,name,url,snippet,score,reason,source_query,run_id,notion_ok,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                lead["domain"], lead["name"], lead["url"], lead.get("snippet", ""),
                lead.get("score"), lead.get("reason", ""), lead.get("source_query", ""),
                lead.get("run_id"), 1 if lead.get("notion_ok") else 0, now(),
            ),
        )
        _c().commit()
        return cur.lastrowid


def mark_notion_ok(lead_id: int) -> None:
    with _lock:
        _c().execute("UPDATE leads SET notion_ok=1 WHERE id=?", (lead_id,))
        _c().commit()


def list_leads(limit: int = 500) -> list[sqlite3.Row]:
    with _lock:
        return _c().execute(
            "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


# ---- runs ----

def start_run() -> int:
    with _lock:
        cur = _c().execute("INSERT INTO runs(started_at) VALUES(?)", (now(),))
        _c().commit()
        return cur.lastrowid


def finish_run(run_id: int, status: str, queries: int, found: int, new: int, message: str) -> None:
    with _lock:
        _c().execute(
            "UPDATE runs SET finished_at=?, status=?, queries=?, found=?, new=?, message=? WHERE id=?",
            (now(), status, queries, found, new, message, run_id),
        )
        _c().commit()


def last_runs(limit: int = 10) -> list[sqlite3.Row]:
    with _lock:
        return _c().execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


# ---- domains ----

def add_domain(domain: str, include_www: bool) -> None:
    with _lock:
        _c().execute(
            "INSERT INTO domains(domain,include_www,created_at) VALUES(?,?,?) "
            "ON CONFLICT(domain) DO UPDATE SET include_www=excluded.include_www, status='active'",
            (domain, 1 if include_www else 0, now()),
        )
        _c().commit()


def remove_domain(domain: str) -> None:
    with _lock:
        _c().execute("DELETE FROM domains WHERE domain=?", (domain,))
        _c().commit()


def list_domains() -> list[sqlite3.Row]:
    with _lock:
        return _c().execute("SELECT * FROM domains ORDER BY id").fetchall()
