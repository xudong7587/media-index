import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.transfers import list_transfers
from app.api.review import _run_confirmed_candidate, prepare_candidate_confirmation
from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import LinkResolution, MediaTarget, RenamePair
from app.providers.base import ProviderCapability, TransferPlan
from app.providers.moviepilot_115 import MoviePilot115TransferProvider
from app.providers.qas import QasTransferProvider
from app.providers.registry import resolve_provider_key
from app.providers.status import normalize_provider_stage, transfer_status_for_stage


class FakeQas:
    def __init__(self):
        self.runs = []

    def configured(self):
        return True

    def tasklist(self):
        return []

    def run_task(self, task):
        self.runs.append(task)
        return {"success": True, "confirmed": True}

    def savepath_detail(self, path):
        return {
            "success": True,
            "data": {"list": [{"file_name": "测试.2026.mkv", "size": 10, "dir": False}]},
        }


class FakeMoviePilot115:
    def configured(self):
        return True

    def submit_share(self, share_url):
        from app.clients.moviepilot_115 import MoviePilot115Submission

        return MoviePilot115Submission(True, "转存成功", "/媒体/电影", "123")


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "ENABLED_CLOUD_PROVIDERS": "qas",
                "DEFAULT_CLOUD_PROVIDER": "qas",
                "CLOUD_SAVE_PATH": "/strm",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_qas_provider_preserves_execution_and_returns_generic_stage(self):
        client = FakeQas()
        provider = QasTransferProvider(client)
        target = MediaTarget(1, "movie", "测试", series_year="2026")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/example",
            rename_pairs=(RenamePair("source.mkv", "source\\.mkv", "测试.2026.mkv"),),
        )
        result = provider.execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))

        self.assertTrue(result.ok)
        self.assertTrue(result.confirmed)
        self.assertEqual("provider_completed", result.stage)
        self.assertEqual(1, len(client.runs))
        self.assertIn(ProviderCapability.EXECUTION_RECONCILE, provider.capabilities())

    def test_provider_selection_keeps_legacy_defaults_and_requires_115_configuration(self):
        self.assertEqual("qas", resolve_provider_key("cloud"))
        self.assertEqual("", resolve_provider_key("local"))
        with self.assertRaisesRegex(ValueError, "尚未配置"):
            with patch.dict(os.environ, {"ENABLED_CLOUD_PROVIDERS": "qas,moviepilot_115"}):
                get_settings.cache_clear()
                resolve_provider_key("cloud", "moviepilot_115")

    def test_local_115_requires_enabled_provider_and_cookie(self):
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "p115",
                "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
            },
        ):
            get_settings.cache_clear()
            self.assertEqual("p115", resolve_provider_key("local", "p115"))

    def test_default_provider_falls_back_to_first_enabled_provider(self):
        with patch.dict(
            os.environ,
            {"ENABLED_CLOUD_PROVIDERS": "p115", "DEFAULT_CLOUD_PROVIDER": "qas"},
        ):
            get_settings.cache_clear()
            self.assertEqual("p115", get_settings().default_provider_key())

    def test_moviepilot_provider_submits_without_claiming_completion(self):
        provider = MoviePilot115TransferProvider(FakeMoviePilot115())
        target = MediaTarget(1, "movie", "测试")
        resolution = LinkResolution(True, "ready", "ready", share_url="https://115.com/s/example")
        result = provider.execute(TransferPlan(target, resolution, ""))
        self.assertTrue(result.ok)
        self.assertEqual("provider_triggered", result.stage)
        self.assertFalse(result.confirmed)
        self.assertIn(ProviderCapability.EXTERNAL_ORGANIZE, provider.capabilities())

    def test_legacy_stages_are_exposed_as_generic_without_rewriting_history(self):
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage)
                VALUES('cloud','qas','triggered','qas_triggered')
                """
            ).lastrowid
        item = next(row for row in list_transfers() if row["id"] == job_id)
        self.assertEqual("provider_triggered", item["stage"])
        with db() as conn:
            stored = conn.execute("SELECT stage FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual("qas_triggered", stored["stage"])
        self.assertEqual("provider_failed", normalize_provider_stage("qas_failed"))
        self.assertEqual("triggered", transfer_status_for_stage("qas_triggered"))

    def test_provider_migration_backfills_related_records_and_is_idempotent(self):
        with db() as conn:
            wishlist_id = conn.execute(
                "INSERT INTO wishlist(tmdb_id,media_type,title,save_target,provider) VALUES(1,'movie','电影','cloud','')"
            ).lastrowid
            task_id = conn.execute(
                "INSERT INTO tracking_tasks(tmdb_id,media_type,title,save_target,provider) VALUES(2,'tv','剧集','cloud','')"
            ).lastrowid
            conn.execute(
                "INSERT INTO tracking_episodes(task_id,season_number,episode_number,provider) VALUES(?,1,1,'')",
                (task_id,),
            )
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage,execution_key)
                VALUES('cloud','','triggered','qas_triggered','2:tv:1:cloud')
                """
            ).lastrowid
            candidate_id = conn.execute(
                "INSERT INTO candidates(job_id,share_url,provider,cloud_type) VALUES(?,'https://pan.quark.cn/s/x','','')",
                (job_id,),
            ).lastrowid
            local_job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage,execution_key)
                VALUES('local','','running','created','3:movie:0:local')
                """
            ).lastrowid

        init_db()
        init_db()
        with db() as conn:
            wishlist = conn.execute("SELECT provider FROM wishlist WHERE id=?", (wishlist_id,)).fetchone()
            task = conn.execute("SELECT provider FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
            episode = conn.execute("SELECT provider FROM tracking_episodes WHERE task_id=?", (task_id,)).fetchone()
            job = conn.execute("SELECT provider,execution_key FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
            candidate = conn.execute(
                "SELECT provider,cloud_type FROM candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            local_job = conn.execute(
                "SELECT provider,execution_key FROM transfer_jobs WHERE id=?", (local_job_id,)
            ).fetchone()
        self.assertEqual("qas", wishlist["provider"])
        self.assertEqual("qas", task["provider"])
        self.assertEqual("qas", episode["provider"])
        self.assertEqual(("qas", "2:tv:1:cloud:qas"), tuple(job))
        self.assertEqual(("qas", "quark"), tuple(candidate))
        self.assertEqual(("", "3:movie:0:local:"), tuple(local_job))

    def test_init_db_adds_provider_columns_to_legacy_schema(self):
        legacy_path = Path(self.tempdir.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.executescript(
            """
            CREATE TABLE wishlist (
              id INTEGER PRIMARY KEY, tmdb_id INTEGER, media_type TEXT, title TEXT,
              save_target TEXT, status TEXT, check_hour INTEGER
            );
            CREATE TABLE tracking_tasks (
              id INTEGER PRIMARY KEY, tmdb_id INTEGER, media_type TEXT, title TEXT,
              save_target TEXT, status TEXT, check_time TEXT
            );
            CREATE TABLE tracking_episodes (
              id INTEGER PRIMARY KEY, task_id INTEGER, season_number INTEGER,
              episode_number INTEGER, status TEXT
            );
            CREATE TABLE transfer_jobs (
              id INTEGER PRIMARY KEY, target TEXT, status TEXT, stage TEXT,
              save_path TEXT, execution_key TEXT
            );
            CREATE TABLE candidates (id INTEGER PRIMARY KEY, job_id INTEGER, share_url TEXT);
            INSERT INTO wishlist VALUES(1,1,'movie','旧电影','cloud','pending',9);
            INSERT INTO transfer_jobs VALUES(1,'cloud','triggered','qas_triggered','/strm/movie/旧电影','1:movie:0:cloud');
            INSERT INTO candidates VALUES(1,1,'https://pan.quark.cn/s/legacy');
            """
        )
        connection.commit()
        connection.close()

        os.environ["DB_PATH"] = str(legacy_path)
        get_settings.cache_clear()
        init_db()
        with db() as conn:
            columns = {
                table: {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for table in ("wishlist", "tracking_tasks", "tracking_episodes", "transfer_jobs", "candidates")
            }
            wishlist = conn.execute("SELECT provider FROM wishlist WHERE id=1").fetchone()
            job = conn.execute("SELECT provider,external_job_id,external_provider_status FROM transfer_jobs WHERE id=1").fetchone()
            candidate = conn.execute("SELECT provider,cloud_type FROM candidates WHERE id=1").fetchone()
        for table in columns:
            self.assertIn("provider", columns[table])
        self.assertEqual("qas", wishlist["provider"])
        self.assertEqual(("qas", "", ""), tuple(job))
        self.assertEqual(("qas", "quark"), tuple(candidate))

    def test_115_review_confirmation_preserves_explicit_job_provider(self):
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage,execution_key)
                VALUES('cloud','moviepilot_115','needs_review','needs_review','1:movie:0:cloud:moviepilot_115')
                """
            ).lastrowid
            candidate_id = conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,cloud_type,provider,rejected,decision)
                VALUES(?,'https://115.com/s/example','115','moviepilot_115',0,'pending')
                """,
                (job_id,),
            ).lastrowid
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "qas,moviepilot_115",
                "MOVIEPILOT_BASE_URL": "https://moviepilot.example",
                "MOVIEPILOT_API_TOKEN": "secret",
            },
        ):
            get_settings.cache_clear()
            candidate, job = prepare_candidate_confirmation(candidate_id)
        self.assertEqual("moviepilot_115", candidate["provider"])
        self.assertEqual("moviepilot_115", job["provider"])
        with db() as conn:
            stored = conn.execute(
                "SELECT provider,status,stage,execution_key FROM transfer_jobs WHERE id=?", (job_id,)
            ).fetchone()
        self.assertEqual(
            ("moviepilot_115", "running", "provider_submitting", "1:movie:0:cloud:moviepilot_115"),
            tuple(stored),
        )

    def test_115_candidate_cannot_change_a_qas_job_provider(self):
        with db() as conn:
            job_id = conn.execute(
                "INSERT INTO transfer_jobs(target,provider,status,stage) VALUES('cloud','qas','needs_review','needs_review')"
            ).lastrowid
            candidate_id = conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,cloud_type,provider,rejected,decision)
                VALUES(?,'https://115.com/s/example','115','moviepilot_115',0,'pending')
                """,
                (job_id,),
            ).lastrowid
        with self.assertRaises(HTTPException) as raised:
            prepare_candidate_confirmation(candidate_id)
        self.assertEqual(409, raised.exception.status_code)

    def test_115_review_submission_is_persisted_as_triggered(self):
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(tmdb_id,media_type,target,provider,status,stage,execution_key)
                VALUES(1,'movie','cloud','moviepilot_115','needs_review','needs_review','1:movie:0:cloud:moviepilot_115')
                """
            ).lastrowid
            candidate_id = conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,source_title,cloud_type,provider,rejected,decision)
                VALUES(?,'https://115.com/s/example','测试','115','moviepilot_115',0,'pending')
                """,
                (job_id,),
            ).lastrowid
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "qas,moviepilot_115",
                "MOVIEPILOT_BASE_URL": "https://moviepilot.example",
                "MOVIEPILOT_API_TOKEN": "secret",
            },
        ):
            get_settings.cache_clear()
            candidate, job = prepare_candidate_confirmation(candidate_id)
            with patch(
                "app.api.review.get_transfer_provider",
                return_value=MoviePilot115TransferProvider(FakeMoviePilot115()),
            ):
                _run_confirmed_candidate(candidate, job, [])
        with db() as conn:
            stored = conn.execute(
                """
                SELECT provider,status,stage,share_url,external_provider_status,review_state
                FROM transfer_jobs WHERE id=?
                """,
                (job_id,),
            ).fetchone()
        self.assertEqual(
            (
                "moviepilot_115",
                "triggered",
                "provider_triggered",
                "https://115.com/s/example",
                "accepted",
                "resolved",
            ),
            tuple(stored),
        )


if __name__ == "__main__":
    unittest.main()
