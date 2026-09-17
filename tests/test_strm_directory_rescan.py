import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from app.api.strm import DirectoryRescanRequest, start_directory_rescan
from app.core.config import get_settings
from app.db.database import init_db, db
from app.services.strm_jobs import create_strm_job, run_directory_rescan


class DirectoryRescanTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {
            "DB_PATH": str(Path(self.temp.name) / "test.db"),
            "P115_STRM_SOURCE_ROOT": "/media",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/纪录片"]',
            "STRM_OUTPUT_ROOT": str(Path(self.temp.name) / "strm"),
            "P115_STRM_ENABLED": "false",
        })
        self.env.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.env.stop()
        get_settings.cache_clear()
        self.temp.cleanup()

    def test_api_queues_exact_nested_directory_without_requiring_auto_generation(self):
        background = BackgroundTasks()
        result = start_directory_rescan(DirectoryRescanRequest(provider="p115", directory_path="/media/纪录片/美丽中国"), background)
        self.assertTrue(result["ok"])
        self.assertEqual(1, len(background.tasks))
        self.assertEqual({"provider": "p115", "directory_path": "/media/纪录片/美丽中国"}, background.tasks[0].kwargs)

    def test_api_rejects_escape_root_sibling_and_traversal_before_creating_job(self):
        for path in ("/media", "/media/纪录片-other", "/media/纪录片/../Movies", "/other"):
            with self.subTest(path=path), self.assertRaises(HTTPException) as caught:
                start_directory_rescan(DirectoryRescanRequest(provider="p115", directory_path=path), BackgroundTasks())
            self.assertEqual(422, caught.exception.status_code)
        with db() as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM transfer_jobs").fetchone()[0])

    def test_provider_read_failure_marks_job_failed_without_refreshing_emby(self):
        job = create_strm_job(provider="p115", mode="full", root_path="/media/纪录片/美丽中国", output_root=get_settings().strm_output_root)
        with patch("app.services.targeted_strm.index_and_reconcile_targeted_path", side_effect=RuntimeError("目录读取失败")), patch("app.services.strm_jobs.refresh_emby_library_after_strm") as refresh:
            result = run_directory_rescan(job, provider="p115", directory_path="/media/纪录片/美丽中国")
        self.assertFalse(result["ok"])
        refresh.assert_not_called()
        with db() as conn:
            self.assertEqual("failed", conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job,)).fetchone()[0])
