import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.strm_jobs import create_strm_job, run_strm_job
from app.services.strm_reconciler import StrmReconcileResult


class StrmJobTests(unittest.TestCase):
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

    def test_incremental_job_is_persisted_and_completes_with_reconcile_summary(self):
        job_id = create_strm_job(provider="p115", mode="incremental", root_path="/Movies", output_root="D:/strm", playback_base_url="http://127.0.0.1:8000")
        with patch("app.services.strm_jobs.reconcile_strm", return_value=StrmReconcileResult(created=2, scraped=1)):
            run_strm_job(job_id, provider="p115", mode="incremental", root_path="/Movies", output_root="D:/strm", playback_base_url="http://127.0.0.1:8000")
        with db() as conn:
            row = dict(conn.execute("SELECT provider,status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual("strm", row["provider"])
        self.assertEqual("done", row["status"])
        self.assertEqual("strm_completed", row["stage"])
        self.assertIn("新增 2", row["message"])
        self.assertIn("刮削 1", row["message"])
