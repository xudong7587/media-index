import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.media_workflow import initialize_media_workflow, list_media_workflow, update_media_workflow_progress


class MediaWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {
            "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
            "P115_STRM_ENABLED": "true",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
        })
        self.environment.start()
        get_settings.cache_clear()
        init_db()
        with db() as conn:
            self.job_id = int(conn.execute(
                "INSERT INTO transfer_jobs(tmdb_id,media_type,target,provider,status,stage,message) VALUES(?,?,?,?,?,?,?)",
                (42, "movie", "cloud", "p115", "running", "searching", "正在查询"),
            ).lastrowid)

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_initializes_exact_seven_steps_with_safe_notification_default(self):
        initialize_media_workflow(self.job_id)
        result = list_media_workflow(42, "movie")
        self.assertEqual([
            "resource_search", "tmdb_rename", "transfer", "openlist_sync",
            "strm_generate", "emby_refresh", "library_notification",
        ], [step["key"] for step in result["steps"]])
        notification = next(step for step in result["steps"] if step["key"] == "library_notification")
        self.assertEqual("skipped", notification["status"])

    def test_progress_completes_search_before_tmdb_review(self):
        initialize_media_workflow(self.job_id)
        update_media_workflow_progress(self.job_id, "candidate_review", "请核对名称")
        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}
        self.assertEqual("done", steps["resource_search"]["status"])
        self.assertEqual("review", steps["tmdb_rename"]["status"])


if __name__ == "__main__":
    unittest.main()
