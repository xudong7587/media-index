import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.strm_jobs import create_strm_job, run_strm_job
from app.services.strm_reconciler import StrmReconcileResult
from app.services.cloud_inventory import InventoryResult


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
        scan = InventoryResult(provider="p115", root_path="/Movies", directories_scanned=1, files_indexed=3, truncated=False)
        with patch("app.services.strm_jobs.scan_p115_inventory", return_value=scan) as scan_mock, patch("app.services.strm_jobs.reconcile_strm", return_value=StrmReconcileResult(created=2)):
            run_strm_job(job_id, provider="p115", mode="incremental", root_path="/Movies", output_root="D:/strm", playback_base_url="http://127.0.0.1:8000")
        scan_mock.assert_called_once_with("/Movies", mark_missing=False)
        with db() as conn:
            row = dict(conn.execute("SELECT provider,status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual("strm", row["provider"])
        self.assertEqual("done", row["status"])
        self.assertEqual("strm_completed", row["stage"])
        self.assertIn("新增 2", row["message"])
        self.assertNotIn("刮削", row["message"])

    def test_quark_full_job_uses_native_inventory_and_marks_missing(self):
        job_id = create_strm_job(provider="quark", mode="full", root_path="/TV", output_root="D:/strm")
        scan = InventoryResult(provider="quark", root_path="/TV", directories_scanned=2, files_indexed=5, truncated=False)
        with patch("app.services.strm_jobs.scan_quark_inventory", return_value=scan) as scan_mock, patch("app.services.strm_jobs.reconcile_strm", return_value=StrmReconcileResult(unchanged=5)) as reconcile_mock:
            run_strm_job(job_id, provider="quark", mode="full", root_path="/TV", output_root="D:/strm")
        scan_mock.assert_called_once_with("/TV", mark_missing=True)
        reconcile_mock.assert_called_once_with(output_root="D:/strm", playback_base_url=None, provider="quark")
        with db() as conn:
            row = dict(conn.execute("SELECT status,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual("done", row["status"])
        self.assertIn("全量扫描 5 个文件", row["message"])
