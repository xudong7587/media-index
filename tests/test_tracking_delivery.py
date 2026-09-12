"""Real local STRM writes with simulated Emby failures; no cloud side effects."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.media_workflow import initialize_media_workflow
from app.services.post_transfer_pipeline import run_post_transfer_pipeline


class TrackingDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "strm"
        self.env = patch.dict(os.environ, {
            "DB_PATH": str(Path(self.temp.name) / "test.db"),
            "P115_STRM_ENABLED": "true",
            "P115_STRM_SOURCE_ROOT": "/媒体库",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/媒体库/12动漫"]',
            "STRM_OUTPUT_ROOT": str(self.output),
            "STRM_PLAYBACK_BASE_URL": "http://127.0.0.1:8000",
            "STRM_MIN_FILE_SIZE_MB": "0",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
            "OPENLIST_ENABLED": "false",
        })
        self.env.start()
        get_settings.cache_clear()
        init_db()
        with db() as conn:
            self.job = conn.execute("INSERT INTO transfer_jobs(provider,target,status) VALUES('p115','cloud','done')").lastrowid
        initialize_media_workflow(self.job)

    def tearDown(self):
        self.env.stop()
        get_settings.cache_clear()
        self.temp.cleanup()

    def run_pipeline(self):
        return run_post_transfer_pipeline(
            self.job, provider="p115", title="凡人修仙传",
            target_path="/媒体库/12动漫/凡人修仙传 (2020)/Season 1",
            target_files=({"file_id": "verified-191", "parent_id": "season-1", "size": 4096,
                           "file_name": "凡人修仙传.2020.S01E191.mkv"},),
        )

    def steps(self):
        with db() as conn:
            return {row["step_key"]: dict(row) for row in conn.execute(
                "SELECT * FROM media_workflow_steps WHERE job_id=?", (self.job,)
            )}

    def test_emby_retry_after_strm_success_and_replay_keeps_webhook_wait(self):
        with patch("app.services.targeted_strm.organizer_provider") as cloud, patch(
            "app.services.post_transfer_pipeline.refresh_emby_library_after_strm",
            side_effect=[RuntimeError("temporary failure"), "刷新已提交"],
        ) as emby:
            self.assertFalse(self.run_pipeline())
            files = list(self.output.rglob("*.strm"))
            self.assertEqual(1, len(files))
            self.assertIn("S01E191", files[0].name)
            self.assertEqual("failed", self.steps()["emby_refresh"]["status"])
            self.assertTrue(self.run_pipeline())
            self.assertEqual("done", self.steps()["emby_refresh"]["status"])
            self.assertEqual("running", self.steps()["library_notification"]["status"])
            self.assertTrue(self.run_pipeline())
            self.assertEqual(2, emby.call_count)
            self.assertEqual("running", self.steps()["library_notification"]["status"])
            self.assertEqual(1, len(list(self.output.rglob("*.strm"))))
            cloud.assert_not_called()

    def test_range_mismatch_reports_actionable_reason_and_never_broadens_scope(self):
        with patch.dict(os.environ, {"P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/媒体库/Movies"]'}), patch(
            "app.services.post_transfer_pipeline.refresh_emby_library_after_strm"
        ) as emby:
            get_settings.cache_clear()
            self.assertFalse(self.run_pipeline())
            self.assertIn("目标路径不属于已勾选的媒体一级子目录", self.steps()["strm_generate"]["message"])
            emby.assert_not_called()
        self.assertEqual([], list(self.output.rglob("*.strm")))

    def test_remote_errors_do_not_expose_credentials(self):
        with patch("app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm",
                   side_effect=RuntimeError("https://example.test?token=secret-value")):
            self.assertFalse(self.run_pipeline())
        self.assertNotIn("secret-value", str(self.steps()))
