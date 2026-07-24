import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.api.review import _supersede_related_reviews, dismiss_candidate
from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import EpisodeTarget, MediaTarget
from app.services.tracking_engine_v2 import _record_tracking_job


class ReviewCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db")})
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_success_supersedes_only_other_reviews_for_same_media(self):
        with db() as conn:
            jobs = []
            for tmdb_id in (10, 10, 20):
                cursor = conn.execute(
                    "INSERT INTO transfer_jobs(tmdb_id,media_type,target,status) VALUES(?, 'tv', 'cloud', 'needs_review')",
                    (tmdb_id,),
                )
                jobs.append(int(cursor.lastrowid))
                conn.execute("INSERT INTO candidates(job_id,share_url) VALUES(?, 'https://example.test/share')", (jobs[-1],))

        count = _supersede_related_reviews({"id": jobs[0], "tmdb_id": 10, "media_type": "tv"})

        self.assertEqual(1, count)
        with db() as conn:
            rows = conn.execute(
                "SELECT status,stage FROM transfer_jobs WHERE id IN (?,?) ORDER BY id",
                (jobs[1], jobs[2]),
            ).fetchall()
            decisions = conn.execute(
                "SELECT decision FROM candidates WHERE job_id IN (?,?) ORDER BY job_id",
                (jobs[1], jobs[2]),
            ).fetchall()
        self.assertEqual(("failed", "superseded"), tuple(rows[0]))
        self.assertEqual(("needs_review", "created"), tuple(rows[1]))
        self.assertEqual("superseded", decisions[0][0])
        self.assertEqual("pending", decisions[1][0])

    def test_dismissing_last_tracking_candidate_releases_episode_for_retry(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,status,decision_state)
                VALUES(261391,'variety','喜剧之王单口季','active','needs_review')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO tracking_episodes(task_id,season_number,episode_number,air_date,status,last_error)
                VALUES(?,3,10,'2026-07-17','needs_review','存在歧义')
                """,
                (task_id,),
            )
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(task_id,tmdb_id,media_type,target,status,stage)
                VALUES(?,261391,'variety','cloud','needs_review','needs_review')
                """,
                (task_id,),
            ).lastrowid
            candidate_id = conn.execute(
                "INSERT INTO candidates(job_id,share_url) VALUES(?,'https://pan.quark.cn/s/test')",
                (job_id,),
            ).lastrowid
            conn.execute(
                "INSERT INTO candidates(job_id,share_url) VALUES(?,'https://pan.quark.cn/s/alternate')",
                (job_id,),
            )

        result = dismiss_candidate(int(candidate_id))

        self.assertEqual(0, result["remaining"])
        with db() as conn:
            task = conn.execute(
                "SELECT decision_state,last_error FROM tracking_tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            episode = conn.execute(
                "SELECT status,last_error FROM tracking_episodes WHERE task_id=? AND episode_number=10",
                (task_id,),
            ).fetchone()
            decisions = conn.execute(
                "SELECT decision FROM candidates WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        self.assertEqual("retry_wait", task["decision_state"])
        self.assertIn("重新搜索", task["last_error"])
        self.assertEqual(("retry_wait", ""), tuple(episode))
        self.assertEqual(["dismissed", "dismissed"], [row["decision"] for row in decisions])

    def test_research_archives_old_execution_key_and_creates_new_job(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,status,decision_state,save_target,save_path)
                VALUES(261391,'variety','喜剧之王单口季','active','pending','local','/下载_未整理/tv/test')
                """
            ).lastrowid
            old_job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(task_id,tmdb_id,media_type,target,status,stage,execution_key)
                VALUES(?,261391,'variety','local','failed','dismissed',?)
                """,
                (task_id, f"tracking:{task_id}:3:10,11:local"),
            ).lastrowid
        target = MediaTarget(
            261391,
            "variety",
            "喜剧之王单口季",
            season_number=3,
            episodes=(EpisodeTarget(3, 10), EpisodeTarget(3, 11)),
        )
        resolution = SimpleNamespace(ok=True, stage="ready", message="匹配成功", share_url="https://pan.quark.cn/s/new", rename_pairs=())

        new_job_id = _record_tracking_job(
            {"id": task_id, "save_target": "local", "save_path": "/下载_未整理/tv/test"},
            target,
            resolution,
        )

        self.assertNotEqual(old_job_id, new_job_id)
        with db() as conn:
            old_job = conn.execute("SELECT execution_key,stage FROM transfer_jobs WHERE id=?", (old_job_id,)).fetchone()
            new_job = conn.execute("SELECT execution_key,status FROM transfer_jobs WHERE id=?", (new_job_id,)).fetchone()
        self.assertIn(":archived:", old_job["execution_key"])
        self.assertEqual("superseded", old_job["stage"])
        self.assertEqual((f"tracking:{task_id}:3:10,11:local:", "ready"), tuple(new_job))


if __name__ == "__main__":
    unittest.main()
