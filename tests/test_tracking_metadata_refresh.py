import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import EpisodeTarget, MediaTarget
from app.services.tracking_engine_v2 import refresh_tracking_task_metadata, run_due_tracking_tasks


class TrackingMetadataRefreshTests(unittest.TestCase):
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

    def create_task(self) -> int:
        with db() as conn:
            task_id = int(conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,category,title,season_number,provider,status,
                    decision_state,last_saved_episode,check_time,next_check_at
                ) VALUES(261391,'variety','variety','喜剧之王单口季',3,'qas','active','idle',25,'00:00',NULL)
                """
            ).lastrowid)
            conn.execute(
                """
                INSERT INTO tracking_episodes(task_id,season_number,episode_number,air_date,title,status,provider)
                VALUES(?,3,25,'2026-08-08','第六期（三）','saved','qas')
                """,
                (task_id,),
            )
        return task_id

    def test_new_tmdb_episodes_are_added_and_wake_dormant_task(self):
        task_id = self.create_task()
        target = MediaTarget(
            261391,
            "variety",
            "喜剧之王单口季",
            category="variety",
            season_number=3,
            episodes=(
                EpisodeTarget(3, 25, "2026-08-08", "第六期（三）"),
                EpisodeTarget(3, 26, "2026-08-14", "第七期（一）"),
                EpisodeTarget(3, 27, "2026-08-14", "第七期（二）"),
            ),
        )

        result = refresh_tracking_task_metadata(task_id, target)

        self.assertEqual([26, 27], result["added_episode_numbers"])
        self.assertTrue(result["next_check_at"])
        with db() as conn:
            rows = conn.execute(
                "SELECT episode_number,status FROM tracking_episodes WHERE task_id=? ORDER BY episode_number",
                (task_id,),
            ).fetchall()
            task = conn.execute("SELECT next_check_at FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        self.assertEqual([(25, "saved"), (26, "pending"), (27, "pending")], [tuple(row) for row in rows])
        self.assertTrue(task["next_check_at"])

    def test_due_cycle_refreshes_tmdb_metadata_before_selecting_tasks(self):
        with patch("app.services.tracking_engine_v2.refresh_tracking_metadata") as refresh:
            self.assertEqual([], run_due_tracking_tasks())
        refresh.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
