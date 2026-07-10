import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks

from app.api.transfers import TransferCreate, _run_transfer_job, create_transfer
from app.core.config import get_settings
from app.db.database import db, init_db


class TransferApiTests(unittest.TestCase):
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

    def test_create_returns_running_job_before_worker_finishes(self):
        background = BackgroundTasks()
        payload = TransferCreate(tmdb_id=1, media_type="movie", title="测试电影", target="cloud")
        response = create_transfer(payload, background)
        self.assertEqual("running", response["status"])
        self.assertEqual("tmdb_resolving", response["stage"])
        self.assertEqual(1, len(background.tasks))
        with db() as conn:
            row = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (response["id"],)).fetchone()
        self.assertEqual(("running", "tmdb_resolving"), tuple(row))

    def test_worker_persists_progress_and_terminal_result(self):
        background = BackgroundTasks()
        payload = TransferCreate(tmdb_id=1, media_type="movie", title="测试电影", target="cloud")
        response = create_transfer(payload, background)

        def fake_execute(*args, on_progress=None, **kwargs):
            on_progress("searching_sources", "正在搜索资源")
            return {"ok": False, "stage": "internal_error", "message": "模拟失败", "save_path": ""}

        with patch("app.api.transfers.execute_transfer_v2", side_effect=fake_execute):
            _run_transfer_job(payload, response["id"])
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (response["id"],)).fetchone()
        self.assertEqual(("failed", "internal_error", "模拟失败"), tuple(row))


if __name__ == "__main__":
    unittest.main()
