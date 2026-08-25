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
  enabled INTEGER NOT NULL DEFAULT 1,
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
  auto_start_episode INTEGER DEFAULT 0,
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
  external_provider_status TEXT DEFAULT '',
  request_source TEXT DEFAULT '',
  request_user TEXT DEFAULT '',
  openlist_fallback_to_p115 INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transfer_record_hidden (
  job_id INTEGER PRIMARY KEY,
  hidden_at TEXT DEFAULT CURRENT_TIMESTAMP
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

CREATE TABLE IF NOT EXISTS media_workflow_steps (
  job_id INTEGER NOT NULL,
  step_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  message TEXT DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(job_id, step_key)
);

CREATE INDEX IF NOT EXISTS ix_media_workflow_steps_job
ON media_workflow_steps(job_id, updated_at);

-- Cross-cloud transfer records are intentionally separate from the legacy
-- share-transfer jobs.  They persist only safe identifiers and progress;
-- neither temporary download URLs nor cookies may be stored here.
CREATE TABLE IF NOT EXISTS cross_cloud_transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_key TEXT NOT NULL,
  source_provider TEXT NOT NULL DEFAULT 'quark',
  source_account_id TEXT DEFAULT '',
  source_parent_id TEXT NOT NULL DEFAULT '',
  source_file_id TEXT NOT NULL,
  source_revision TEXT DEFAULT '',
  source_name TEXT NOT NULL DEFAULT '',
  source_size INTEGER NOT NULL DEFAULT 0,
  source_sha1 TEXT DEFAULT '',
  source_md5 TEXT DEFAULT '',
  target_provider TEXT NOT NULL DEFAULT 'p115',
  target_account_id TEXT DEFAULT '',
  target_parent_path TEXT NOT NULL DEFAULT '',
  target_parent_id TEXT DEFAULT '',
  target_name TEXT NOT NULL DEFAULT '',
  target_file_id TEXT DEFAULT '',
  strategy TEXT NOT NULL DEFAULT 'rapid_then_stream',
  state TEXT NOT NULL DEFAULT 'created',
  stage_message TEXT DEFAULT '',
  attempt INTEGER NOT NULL DEFAULT 0,
  rapid_probe_result TEXT DEFAULT '',
  remote_upload_id TEXT DEFAULT '',
  fingerprinted_bytes INTEGER NOT NULL DEFAULT 0,
  uploaded_bytes INTEGER NOT NULL DEFAULT 0,
  total_bytes INTEGER NOT NULL DEFAULT 0,
  last_error_code TEXT DEFAULT '',
  last_error_message_safe TEXT DEFAULT '',
  cleanup_state TEXT NOT NULL DEFAULT 'not_needed',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_cross_cloud_transfers_recent
ON cross_cloud_transfers(created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_cross_cloud_transfers_execution
ON cross_cloud_transfers(execution_key, state);

CREATE TABLE IF NOT EXISTS cross_cloud_transfer_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  transfer_id INTEGER NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL,
  message TEXT DEFAULT '',
  fingerprinted_bytes INTEGER NOT NULL DEFAULT 0,
  uploaded_bytes INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_cross_cloud_transfer_events_transfer
ON cross_cloud_transfer_events(transfer_id, id);

-- Assets are the authority for playback, STRM and deletion decisions.  A
-- provider file ID remains stable across a rename/move, unlike a displayed
-- path or a generated .strm filename.
CREATE TABLE IF NOT EXISTS media_assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  account_id TEXT NOT NULL DEFAULT '',
  file_id TEXT NOT NULL,
  parent_id TEXT DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  relative_path TEXT DEFAULT '',
  inventory_root_path TEXT DEFAULT '',
  size INTEGER NOT NULL DEFAULT 0,
  sha1 TEXT DEFAULT '',
  md5 TEXT DEFAULT '',
  revision TEXT DEFAULT '',
  media_type TEXT DEFAULT '',
  tmdb_id INTEGER,
  season_number INTEGER,
  episode_number INTEGER,
  quality_profile TEXT DEFAULT '',
  source_transfer_id INTEGER,
  status TEXT NOT NULL DEFAULT 'discovered',
  missing_scan_count INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider,account_id,file_id)
);

CREATE INDEX IF NOT EXISTS ix_media_assets_library
ON media_assets(status, media_type, tmdb_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS strm_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  library_root_id TEXT NOT NULL DEFAULT 'default',
  relative_path TEXT NOT NULL,
  content_version TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  last_error_safe TEXT DEFAULT '',
  last_written_at TEXT,
  last_verified_at TEXT,
  missing_scan_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(asset_id,library_root_id),
  UNIQUE(library_root_id,relative_path)
);

CREATE TABLE IF NOT EXISTS deletion_intents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  trigger_source TEXT NOT NULL,
  trigger_ref TEXT DEFAULT '',
  state TEXT NOT NULL DEFAULT 'requested',
  not_before TEXT,
  references_at_request INTEGER NOT NULL DEFAULT 0,
  trash_receipt_json TEXT DEFAULT '',
  message_safe TEXT DEFAULT '',
  requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
  confirmed_at TEXT,
  completed_at TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_deletion_intents_asset
ON deletion_intents(asset_id, state, requested_at DESC);

CREATE TABLE IF NOT EXISTS channel_subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL UNIQUE,
  display_name TEXT DEFAULT '',
  provider TEXT NOT NULL DEFAULT 'quark',
  enabled INTEGER NOT NULL DEFAULT 1,
  auto_transfer INTEGER NOT NULL DEFAULT 0,
  require_douban_match INTEGER NOT NULL DEFAULT 0,
  douban_titles_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channel_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subscription_id INTEGER NOT NULL,
  channel_id TEXT NOT NULL,
  message_id INTEGER NOT NULL,
  text_preview TEXT DEFAULT '',
  link_count INTEGER NOT NULL DEFAULT 0,
  matched_wishlist_id INTEGER,
  state TEXT NOT NULL DEFAULT 'ignored',
  message_safe TEXT DEFAULT '',
  transfer_job_id INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(channel_id,message_id)
);

CREATE INDEX IF NOT EXISTS ix_channel_messages_subscription
ON channel_messages(subscription_id, created_at DESC);

CREATE TABLE IF NOT EXISTS channel_resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_message_id INTEGER NOT NULL,
  subscription_id INTEGER NOT NULL,
  channel_id TEXT NOT NULL,
  message_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  share_url TEXT NOT NULL,
  source_title TEXT DEFAULT '',
  content_preview TEXT DEFAULT '',
  search_text TEXT DEFAULT '',
  message_url TEXT DEFAULT '',
  published_at TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(channel_id,message_id,share_url)
);

CREATE INDEX IF NOT EXISTS ix_channel_resources_lookup
ON channel_resources(subscription_id, provider, published_at DESC);

CREATE INDEX IF NOT EXISTS ix_channel_resources_message
ON channel_resources(channel_message_id);

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
    with db() as conn:
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
        ensure_column(conn, "wishlist", "enabled", "INTEGER NOT NULL DEFAULT 1")
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
        ensure_column(conn, "tracking_tasks", "auto_start_episode", "INTEGER DEFAULT 0")
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
        ensure_column(conn, "transfer_jobs", "request_source", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "request_user", "TEXT DEFAULT ''")
        ensure_column(conn, "transfer_jobs", "openlist_fallback_to_p115", "INTEGER NOT NULL DEFAULT 0")
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
        ensure_column(conn, "channel_subscriptions", "last_checked_at", "TEXT")
        ensure_column(conn, "channel_subscriptions", "last_error", "TEXT DEFAULT ''")
        ensure_column(conn, "channel_subscriptions", "last_resource_at", "TEXT")
        ensure_column(conn, "media_assets", "relative_path", "TEXT DEFAULT ''")
        ensure_column(conn, "media_assets", "inventory_root_path", "TEXT DEFAULT ''")
        ensure_column(conn, "media_assets", "missing_scan_count", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "strm_entries", "missing_scan_count", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_media_assets_inventory_scope "
            "ON media_assets(provider,inventory_root_path,status)"
        )
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
              auto_start_episode INTEGER DEFAULT 0, last_storage_check_at TEXT, storage_check_message TEXT DEFAULT '',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
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
              enabled INTEGER NOT NULL DEFAULT 1,
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
