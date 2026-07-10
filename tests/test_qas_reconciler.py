import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.qas_reconciler import reconcile_triggered_jobs


class EmptyDirectoryQas:
    def savepath_detail(self, path):
        return {"success": True, "data": {"list": []}}

    def task_data(self):
        return {"push_config": {}}


class QasReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "QAS_CONFIRMATION_TIMEOUT_MINUTES": "30",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_expired_triggered_job_returns_tracking_to_retry(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,save_path,decision_state)
                VALUES(1,'tv','测试剧',1,'/strm/tv/测试剧','awaiting_confirmation')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,rename_to)
                VALUES(?,1,1,'triggered','测试剧.2026.S01E01.mkv')
                """,
                (task_id,),
            )
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(task_id,tmdb_id,media_type,target,status,stage,save_path,
                                          rename_pairs_json,created_at)
                VALUES(?,1,'tv','cloud','triggered','qas_triggered','/strm/tv/测试剧',?,?)
                """,
                (task_id, '[{"replacement":"测试剧.2026.S01E01.mkv"}]', old),
            ).lastrowid

        result = reconcile_triggered_jobs(qas=EmptyDirectoryQas())
        self.assertEqual([{"job_id": job_id, "confirmed": False, "expired": True}], result)
        with db() as conn:
            job = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
            task = conn.execute("SELECT decision_state,next_check_at FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
            episode = conn.execute("SELECT status FROM tracking_episodes WHERE task_id=?", (task_id,)).fetchone()
        self.assertEqual(("failed", "qas_confirmation_timeout"), tuple(job))
        self.assertEqual("retry_wait", task["decision_state"])
        self.assertTrue(task["next_check_at"])
        self.assertEqual("retry_wait", episode["status"])

    def test_repeated_confirmation_timeout_enters_review(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,save_path,decision_state,retry_count)
                VALUES(2,'tv','测试剧',1,'/strm/tv/测试剧','awaiting_confirmation',4)
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,rename_to)
                VALUES(?,1,1,'triggered','测试剧.2026.S01E01.mkv')
                """,
                (task_id,),
            )
            conn.execute(
                """
                INSERT INTO transfer_jobs(task_id,tmdb_id,media_type,target,status,stage,save_path,
                                          rename_pairs_json,created_at)
                VALUES(?,2,'tv','cloud','triggered','qas_triggered','/strm/tv/测试剧',?,?)
                """,
                (task_id, '[{"replacement":"测试剧.2026.S01E01.mkv"}]', old),
            )
        reconcile_triggered_jobs(qas=EmptyDirectoryQas())
        with db() as conn:
            task = conn.execute("SELECT decision_state,next_check_at,retry_count FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        self.assertEqual("needs_review", task["decision_state"])
        self.assertEqual("", task["next_check_at"])
        self.assertEqual(5, task["retry_count"])


if __name__ == "__main__":
    unittest.main()
