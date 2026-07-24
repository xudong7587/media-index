import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.tracking import TrackingProviderUpdate, list_tracking, update_provider
from app.core.config import get_settings
from app.db.database import db, init_db


class TrackingApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "ENABLED_CLOUD_PROVIDERS": "qas,p115",
                "P115_COOKIE": "UID=1_A1_1; CID=test; SEID=test",
            },
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

    def test_enabling_second_provider_preserves_first_provider_storage_state(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,year,season_number,provider,save_path,last_saved_episode
                ) VALUES(2,'tv','测试剧','2026',1,'qas','/strm/tv/测试剧(2026)',8)
                """
            ).lastrowid
            conn.execute(
                "INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,provider) VALUES(?,1,1,'saved','qas')",
                (task_id,),
            )

        result = update_provider(task_id, TrackingProviderUpdate(provider="p115"))

        self.assertEqual("p115", result["provider"])
        with db() as conn:
            tasks = conn.execute(
                "SELECT provider,last_saved_episode FROM tracking_tasks WHERE tmdb_id=2 ORDER BY provider"
            ).fetchall()
            episode = conn.execute("SELECT provider,status FROM tracking_episodes WHERE task_id=?", (task_id,)).fetchone()
        self.assertEqual([("p115", 0), ("qas", 8)], [tuple(row) for row in tasks])
        self.assertEqual(("qas", "saved"), tuple(episode))
        grouped = list_tracking()
        self.assertEqual(1, len(grouped))
        self.assertEqual(["qas", "p115"], [state["provider"] for state in grouped[0]["provider_states"]])


if __name__ == "__main__":
    unittest.main()
