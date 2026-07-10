import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import get_settings


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS media (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tmdb_id INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  title TEXT NOT NULL,
  original_title TEXT DEFAULT '',
  year TEXT DEFAULT '',
  poster_url TEXT DEFAULT '',
  backdrop_url TEXT DEFAULT '',
  overview TEXT DEFAULT '',
  status TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(tmdb_id, media_type)
);

CREATE TABLE IF NOT EXISTS wishlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tmdb_id INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  title TEXT NOT NULL,
  year TEXT DEFAULT '',
  poster_url TEXT DEFAULT '',
  overview TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(tmdb_id, media_type)
);

CREATE TABLE IF NOT EXISTS tracking_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tmdb_id INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  title TEXT NOT NULL,
  year TEXT DEFAULT '',
  poster_url TEXT DEFAULT '',
  overview TEXT DEFAULT '',
  season_number INTEGER DEFAULT 1,
  save_target TEXT DEFAULT 'cloud',
  save_root TEXT DEFAULT '',
  save_path TEXT DEFAULT '',
  status TEXT DEFAULT 'active',
  last_checked_at TEXT,
  next_check_at TEXT,
  last_error TEXT DEFAULT '',
  current_share_url TEXT DEFAULT '',
  decision_state TEXT DEFAULT 'pending',
  retry_count INTEGER DEFAULT 0,
  next_retry_at TEXT,
  last_search_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(tmdb_id, media_type, season_number)
);

CREATE TABLE IF NOT EXISTS tracking_episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  season_number INTEGER NOT NULL,
  episode_number INTEGER NOT NULL,
  air_date TEXT DEFAULT '',
  title TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  matched_file TEXT DEFAULT '',
  share_url TEXT DEFAULT '',
  save_path TEXT DEFAULT '',
  retry_count INTEGER DEFAULT 0,
  last_error TEXT DEFAULT '',
  match_tokens_json TEXT DEFAULT '[]',
  desc_hint TEXT DEFAULT '',
  source_file TEXT DEFAULT '',
  rename_to TEXT DEFAULT '',
  confidence TEXT DEFAULT '',
  candidate_id INTEGER,
  saved_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(task_id, season_number, episode_number)
);

CREATE TABLE IF NOT EXISTS transfer_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  media_id INTEGER,
  task_id INTEGER,
  tmdb_id INTEGER,
  media_type TEXT DEFAULT '',
  season_number INTEGER,
  target TEXT NOT NULL,
  status TEXT DEFAULT 'queued',
  stage TEXT DEFAULT 'created',
  message TEXT DEFAULT '',
  share_url TEXT DEFAULT '',
  source_file TEXT DEFAULT '',
  renamed_file TEXT DEFAULT '',
  save_path TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL,
  share_url TEXT NOT NULL,
  source_title TEXT DEFAULT '',
  search_query TEXT DEFAULT '',
  source TEXT DEFAULT '',
  published_at TEXT DEFAULT '',
  file_count INTEGER DEFAULT 0,
  files_json TEXT DEFAULT '[]',
  score REAL DEFAULT 0,
  match_stage TEXT DEFAULT '',
  is_fuzzy INTEGER DEFAULT 0,
  rejected INTEGER DEFAULT 0,
  reasons_json TEXT DEFAULT '[]',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect() -> sqlite3.Connection:
    settings = get_settings()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        ensure_column(conn, "tracking_tasks", "poster_url", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_tasks", "overview", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_tasks", "current_share_url", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_tasks", "decision_state", "TEXT DEFAULT 'pending'")
        ensure_column(conn, "tracking_tasks", "retry_count", "INTEGER DEFAULT 0")
        ensure_column(conn, "tracking_tasks", "next_retry_at", "TEXT")
        ensure_column(conn, "tracking_tasks", "last_search_at", "TEXT")
        ensure_column(conn, "tracking_episodes", "match_tokens_json", "TEXT DEFAULT '[]'")
        ensure_column(conn, "tracking_episodes", "desc_hint", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "source_file", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "rename_to", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "confidence", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "candidate_id", "INTEGER")
        ensure_column(conn, "transfer_jobs", "tmdb_id", "INTEGER")
        ensure_column(conn, "transfer_jobs", "media_type", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "season_number", "INTEGER")
        ensure_column(conn, "candidates", "search_query", "TEXT DEFAULT ''")
        ensure_column(conn, "candidates", "source", "TEXT DEFAULT ''")
        ensure_column(conn, "candidates", "published_at", "TEXT DEFAULT ''")
        ensure_column(conn, "candidates", "rejected", "INTEGER DEFAULT 0")
        ensure_column(conn, "candidates", "reasons_json", "TEXT DEFAULT '[]'")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
