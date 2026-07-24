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
  category TEXT DEFAULT '',
  title TEXT NOT NULL,
  year TEXT DEFAULT '',
  poster_url TEXT DEFAULT '',
  overview TEXT DEFAULT '',
  season_number INTEGER,
  save_target TEXT DEFAULT 'cloud',
  provider TEXT DEFAULT '',
  check_hour INTEGER DEFAULT 9,
  tmdb_date TEXT DEFAULT '',
  next_check_at TEXT,
  last_checked_at TEXT,
  last_error TEXT DEFAULT '',
  retry_count INTEGER DEFAULT 0,
  notification_sent_at TEXT,
  status TEXT DEFAULT 'pending',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(tmdb_id, media_type, provider)
);

CREATE TABLE IF NOT EXISTS tracking_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tmdb_id INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  category TEXT DEFAULT '',
  title TEXT NOT NULL,
  year TEXT DEFAULT '',
  poster_url TEXT DEFAULT '',
  overview TEXT DEFAULT '',
  season_number INTEGER DEFAULT 1,
  save_target TEXT DEFAULT 'cloud',
  provider TEXT DEFAULT '',
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
  check_time TEXT DEFAULT '10:00',
  last_saved_episode INTEGER DEFAULT 0,
  last_storage_check_at TEXT,
  storage_check_message TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(tmdb_id, media_type, season_number, provider)
);

CREATE TABLE IF NOT EXISTS tracking_episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  season_number INTEGER NOT NULL,
  episode_number INTEGER NOT NULL,
  air_date TEXT DEFAULT '',
  title TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  provider TEXT DEFAULT '',
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
  batch_id INTEGER,
  media_id INTEGER,
  task_id INTEGER,
  wishlist_id INTEGER,
  tmdb_id INTEGER,
  media_type TEXT DEFAULT '',
  display_title TEXT DEFAULT '',
  season_number INTEGER,
  target TEXT NOT NULL,
  provider TEXT DEFAULT '',
  status TEXT DEFAULT 'queued',
  stage TEXT DEFAULT 'created',
  message TEXT DEFAULT '',
  share_url TEXT DEFAULT '',
  source_file TEXT DEFAULT '',
  renamed_file TEXT DEFAULT '',
  rename_pairs_json TEXT DEFAULT '[]',
  save_path TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  notification_sent_at TEXT,
  review_state TEXT DEFAULT '',
  execution_key TEXT DEFAULT '',
  external_job_id TEXT DEFAULT '',
  external_provider_status TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS transfer_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tmdb_id INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  display_title TEXT DEFAULT '',
  target TEXT NOT NULL DEFAULT 'cloud',
  status TEXT NOT NULL DEFAULT 'running',
  message TEXT DEFAULT '',
  providers_json TEXT NOT NULL DEFAULT '[]',
  seasons_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS transfer_batch_jobs (
  batch_id INTEGER NOT NULL,
  job_id INTEGER NOT NULL,
  PRIMARY KEY(batch_id,job_id)
);

CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL,
  share_url TEXT NOT NULL,
  source_title TEXT DEFAULT '',
  search_query TEXT DEFAULT '',
  source TEXT DEFAULT '',
  cloud_type TEXT DEFAULT '',
  provider TEXT DEFAULT '',
  published_at TEXT DEFAULT '',
  file_count INTEGER DEFAULT 0,
  files_json TEXT DEFAULT '[]',
  score REAL DEFAULT 0,
  match_stage TEXT DEFAULT '',
  is_fuzzy INTEGER DEFAULT 0,
  rejected INTEGER DEFAULT 0,
  reasons_json TEXT DEFAULT '[]',
  decision TEXT DEFAULT 'pending',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_key TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL DEFAULT 'info',
  title TEXT NOT NULL,
  message TEXT DEFAULT '',
  action_page TEXT DEFAULT '',
  poster_url TEXT DEFAULT '',
  poster_key TEXT DEFAULT '',
  is_read INTEGER NOT NULL DEFAULT 0,
  is_cleared INTEGER NOT NULL DEFAULT 0,
  external_status TEXT NOT NULL DEFAULT '',
  external_attempted_at TEXT,
  external_error TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_notifications_visible
ON notifications(is_cleared, is_read, created_at DESC);

CREATE TABLE IF NOT EXISTS wecom_interactions (
  user_id TEXT PRIMARY KEY,
  interaction_type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect() -> sqlite3.Connection:
    settings = get_settings()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
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
        ensure_column(conn, "wishlist", "season_number", "INTEGER")
        ensure_column(conn, "wishlist", "category", "TEXT DEFAULT ''")
        ensure_column(conn, "wishlist", "save_target", "TEXT DEFAULT 'cloud'")
        ensure_column(conn, "wishlist", "provider", "TEXT DEFAULT ''")
        ensure_column(conn, "wishlist", "check_hour", "INTEGER DEFAULT 9")
        ensure_column(conn, "wishlist", "tmdb_date", "TEXT DEFAULT ''")
        ensure_column(conn, "wishlist", "next_check_at", "TEXT")
        ensure_column(conn, "wishlist", "last_checked_at", "TEXT")
        ensure_column(conn, "wishlist", "last_error", "TEXT DEFAULT ''")
        ensure_column(conn, "wishlist", "retry_count", "INTEGER DEFAULT 0")
        ensure_column(conn, "wishlist", "notification_sent_at", "TEXT")
        ensure_column(conn, "wishlist", "updated_at", "TEXT")
        ensure_column(conn, "tracking_tasks", "poster_url", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_tasks", "category", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_tasks", "provider", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_tasks", "overview", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_tasks", "current_share_url", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_tasks", "decision_state", "TEXT DEFAULT 'pending'")
        ensure_column(conn, "tracking_tasks", "retry_count", "INTEGER DEFAULT 0")
        ensure_column(conn, "tracking_tasks", "next_retry_at", "TEXT")
        ensure_column(conn, "tracking_tasks", "last_search_at", "TEXT")
        ensure_column(conn, "tracking_tasks", "check_time", "TEXT DEFAULT '10:00'")
        ensure_column(conn, "tracking_tasks", "last_saved_episode", "INTEGER DEFAULT 0")
        ensure_column(conn, "tracking_tasks", "last_storage_check_at", "TEXT")
        ensure_column(conn, "tracking_tasks", "storage_check_message", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "match_tokens_json", "TEXT DEFAULT '[]'")
        ensure_column(conn, "tracking_episodes", "desc_hint", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "source_file", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "rename_to", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "confidence", "TEXT DEFAULT ''")
        ensure_column(conn, "tracking_episodes", "candidate_id", "INTEGER")
        ensure_column(conn, "tracking_episodes", "provider", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "tmdb_id", "INTEGER")
        ensure_column(conn, "transfer_jobs", "wishlist_id", "INTEGER")
        ensure_column(conn, "transfer_jobs", "media_type", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "display_title", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "season_number", "INTEGER")
        ensure_column(conn, "transfer_jobs", "notification_sent_at", "TEXT")
        ensure_column(conn, "transfer_jobs", "review_state", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "rename_pairs_json", "TEXT DEFAULT '[]'")
        ensure_column(conn, "transfer_jobs", "execution_key", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "provider", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "external_job_id", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "external_provider_status", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "batch_id", "INTEGER")
        ensure_column(conn, "candidates", "search_query", "TEXT DEFAULT ''")
        ensure_column(conn, "candidates", "source", "TEXT DEFAULT ''")
        ensure_column(conn, "candidates", "published_at", "TEXT DEFAULT ''")
        ensure_column(conn, "candidates", "rejected", "INTEGER DEFAULT 0")
        ensure_column(conn, "candidates", "reasons_json", "TEXT DEFAULT '[]'")
        ensure_column(conn, "candidates", "decision", "TEXT DEFAULT 'pending'")
        ensure_column(conn, "candidates", "cloud_type", "TEXT DEFAULT ''")
        ensure_column(conn, "candidates", "provider", "TEXT DEFAULT ''")
        ensure_column(conn, "notifications", "external_status", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "notifications", "external_attempted_at", "TEXT")
        ensure_column(conn, "notifications", "external_error", "TEXT DEFAULT ''")
        ensure_column(conn, "notifications", "poster_url", "TEXT DEFAULT ''")
        ensure_column(conn, "notifications", "poster_key", "TEXT DEFAULT ''")
        migrate_provider_task_constraints(conn)
        conn.execute("UPDATE wishlist SET check_hour=9 WHERE check_hour IS NULL")
        conn.execute("UPDATE wishlist SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL OR updated_at=''")
        conn.execute("UPDATE tracking_tasks SET check_time='10:00' WHERE check_time IS NULL OR check_time=''")
        conn.execute("DROP INDEX IF EXISTS uq_transfer_active_execution")
        migrate_provider_data(conn)
        conn.execute(
            """
            UPDATE wishlist SET next_check_at=CURRENT_TIMESTAMP
            WHERE status IN ('pending','retry_wait') AND (next_check_at IS NULL OR next_check_at='')
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_transfer_active_execution ON transfer_jobs(execution_key) "
            "WHERE execution_key!='' AND status IN ('running','ready','triggered')"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_transfer_jobs_batch ON transfer_jobs(batch_id,id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_transfer_batch_jobs_job ON transfer_batch_jobs(job_id,batch_id)"
        )


def migrate_provider_data(conn: sqlite3.Connection) -> None:
    """Backfill the implicit legacy QAS provider without rewriting old stages."""
    conn.execute("UPDATE wishlist SET provider='qas' WHERE save_target='cloud' AND COALESCE(provider,'')=''")
    conn.execute("UPDATE wishlist SET provider='' WHERE save_target='local'")
    conn.execute("UPDATE tracking_tasks SET provider='qas' WHERE save_target='cloud' AND COALESCE(provider,'')=''")
    conn.execute("UPDATE tracking_tasks SET provider='' WHERE save_target='local'")
    conn.execute("UPDATE transfer_jobs SET provider='qas' WHERE target='cloud' AND COALESCE(provider,'')=''")
    conn.execute("UPDATE transfer_jobs SET provider='' WHERE target='local'")
    conn.execute(
        """
        UPDATE tracking_episodes
        SET provider=COALESCE((SELECT provider FROM tracking_tasks WHERE tracking_tasks.id=tracking_episodes.task_id),'')
        WHERE COALESCE(provider,'')=''
        """
    )
    conn.execute(
        """
        UPDATE candidates
        SET provider=COALESCE((SELECT provider FROM transfer_jobs WHERE transfer_jobs.id=candidates.job_id),'')
        WHERE COALESCE(provider,'')=''
        """
    )
    conn.execute("UPDATE candidates SET cloud_type='quark' WHERE provider='qas' AND COALESCE(cloud_type,'')=''")
    conn.execute(
        """
        UPDATE transfer_jobs
        SET execution_key=execution_key || ':qas'
        WHERE provider='qas' AND execution_key!=''
          AND status IN ('running','ready','triggered')
          AND execution_key NOT LIKE '%:qas'
        """
    )
    conn.execute(
        """
        UPDATE transfer_jobs
        SET execution_key=execution_key || ':'
        WHERE provider='' AND target='local' AND execution_key!=''
          AND status IN ('running','ready','triggered')
          AND substr(execution_key,-1)!=':'
        """
    )


def migrate_provider_task_constraints(conn: sqlite3.Connection) -> None:
    """Allow one independently scheduled row per provider while preserving legacy ids."""
    tracking_sql = (conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tracking_tasks'"
    ).fetchone() or {"sql": ""})["sql"] or ""
    if "UNIQUE(tmdb_id, media_type, season_number, provider)" not in tracking_sql.replace("\n", " "):
        conn.execute("ALTER TABLE tracking_tasks RENAME TO tracking_tasks_legacy_provider")
        conn.execute(
            """
            CREATE TABLE tracking_tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT, tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL,
              category TEXT DEFAULT '', title TEXT NOT NULL, year TEXT DEFAULT '', poster_url TEXT DEFAULT '',
              overview TEXT DEFAULT '', season_number INTEGER DEFAULT 1, save_target TEXT DEFAULT 'cloud',
              provider TEXT DEFAULT '', save_root TEXT DEFAULT '', save_path TEXT DEFAULT '', status TEXT DEFAULT 'active',
              last_checked_at TEXT, next_check_at TEXT, last_error TEXT DEFAULT '', current_share_url TEXT DEFAULT '',
              decision_state TEXT DEFAULT 'pending', retry_count INTEGER DEFAULT 0, next_retry_at TEXT,
              last_search_at TEXT, check_time TEXT DEFAULT '10:00', last_saved_episode INTEGER DEFAULT 0,
              last_storage_check_at TEXT, storage_check_message TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(tmdb_id, media_type, season_number, provider)
            )
            """
        )
        legacy_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(tracking_tasks_legacy_provider)").fetchall()
        }
        columns = [
            row["name"] for row in conn.execute("PRAGMA table_info(tracking_tasks)").fetchall()
            if row["name"] in legacy_columns
        ]
        column_list = ",".join(columns)
        conn.execute(
            f"INSERT INTO tracking_tasks({column_list}) SELECT {column_list} FROM tracking_tasks_legacy_provider"
        )
        conn.execute("DROP TABLE tracking_tasks_legacy_provider")

    wishlist_sql = (conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='wishlist'"
    ).fetchone() or {"sql": ""})["sql"] or ""
    if "UNIQUE(tmdb_id, media_type, provider)" not in wishlist_sql.replace("\n", " "):
        conn.execute("ALTER TABLE wishlist RENAME TO wishlist_legacy_provider")
        conn.execute(
            """
            CREATE TABLE wishlist (
              id INTEGER PRIMARY KEY AUTOINCREMENT, tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL,
              category TEXT DEFAULT '', title TEXT NOT NULL, year TEXT DEFAULT '', poster_url TEXT DEFAULT '',
              overview TEXT DEFAULT '', season_number INTEGER, save_target TEXT DEFAULT 'cloud', provider TEXT DEFAULT '',
              check_hour INTEGER DEFAULT 9, tmdb_date TEXT DEFAULT '', next_check_at TEXT, last_checked_at TEXT,
              last_error TEXT DEFAULT '', retry_count INTEGER DEFAULT 0, notification_sent_at TEXT,
              status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(tmdb_id, media_type, provider)
            )
            """
        )
        legacy_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(wishlist_legacy_provider)").fetchall()
        }
        columns = [
            row["name"] for row in conn.execute("PRAGMA table_info(wishlist)").fetchall()
            if row["name"] in legacy_columns
        ]
        column_list = ",".join(columns)
        conn.execute(f"INSERT INTO wishlist({column_list}) SELECT {column_list} FROM wishlist_legacy_provider")
        conn.execute("DROP TABLE wishlist_legacy_provider")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
