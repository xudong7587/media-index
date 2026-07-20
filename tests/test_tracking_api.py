import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.tracking import list_tracking
from app.core.config import get_settings
from app.db.database import db, init_db


class TrackingApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {"DB_PATH": str(Path(self.tempdir.name) / "test.db")},
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_triggered_count_remains_cumulative_after_qas_confirmation(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number)
                VALUES(1,'tv','测试剧',3)
                """
            ).lastrowid
            conn.executemany(
                """
                INSERT INTO tracking_episodes(
                    task_id,season_number,episode_number,status,source_file,rename_to
                ) VALUES(?,3,?,?,?,?)
                """,
                [
                    (task_id, 1, "saved", "", ""),
                    (task_id, 2, "saved", "02.mp4", "测试剧.2026.S03E02.mp4"),
                    (task_id, 3, "triggered", "03.mp4", "测试剧.2026.S03E03.mp4"),
                    (task_id, 4, "pending", "", ""),
                ],
            )

        task = list_tracking()[0]

        self.assertEqual(2, task["saved_count"])
        self.assertEqual(2, task["triggered_count"])
        self.assertEqual(4, task["episode_count"])


if __name__ == "__main__":
    unittest.main()
