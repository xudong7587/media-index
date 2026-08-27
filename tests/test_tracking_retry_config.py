import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.api.config import ConfigUpdate, _update_config, status
from app.core.config import Settings, get_settings
from app.db.database import db, init_db
from app.services.tracking_engine_v2 import _execution_retry_state, _resolution_needs_review, run_tracking_task


class TrackingRetryConfigTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env_path = Path(self.tempdir.name) / ".env"
        self.env_path.write_text("UNRELATED_LOCAL_SETTING=keep-me\n", encoding="utf-8")
        self.environment = patch.dict(
            os.environ,
            {
                "MEDIA_CONFIG_PATH": str(self.env_path),
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "TRACKING_SCHEDULER_ENABLED": "false",
                "WISHLIST_SCHEDULER_ENABLED": "false",
                "NOTIFICATION_EXTERNAL_ENABLED": "false",
            },
            clear=False,
        )
        self.environment.start()
        get_settings.cache_clear()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_retry_settings_save_through_existing_config_contract(self):
        with patch("app.api.config.stop_scheduler"), patch("app.api.config.start_scheduler"):
            result = _update_config(ConfigUpdate(
                tracking_retry_interval_minutes=90,
                tracking_max_retries=3,
            ))

        saved = self.env_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn("TRACKING_RETRY_INTERVAL_MINUTES=90", saved)
        self.assertIn("TRACKING_MAX_RETRIES=3", saved)
        self.assertIn("UNRELATED_LOCAL_SETTING=keep-me", saved)
        self.assertEqual(90, status()["tracking_retry_interval_minutes"])
        self.assertEqual(3, status()["tracking_max_retries"])

    def test_new_and_empty_tracking_times_default_to_noon_without_overwriting_existing_value(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
        self.assertEqual("12:00", settings.tracking_check_time)
        self.assertEqual(12, settings.tracking_check_hour)

        init_db()
        with db() as conn:
            default_id = int(conn.execute(
                "INSERT INTO tracking_tasks(tmdb_id,media_type,title,provider) VALUES(1,'tv','默认时间','p115')"
            ).lastrowid)
            existing_id = int(conn.execute(
                "INSERT INTO tracking_tasks(tmdb_id,media_type,title,provider,check_time) VALUES(2,'tv','已设时间','p115','09:30')"
            ).lastrowid)
            conn.execute("UPDATE tracking_tasks SET check_time=NULL WHERE id=?", (default_id,))

        init_db()
        with db() as conn:
            default_time = conn.execute("SELECT check_time FROM tracking_tasks WHERE id=?", (default_id,)).fetchone()["check_time"]
            existing_time = conn.execute("SELECT check_time FROM tracking_tasks WHERE id=?", (existing_id,)).fetchone()["check_time"]
        self.assertEqual("12:00", default_time)
        self.assertEqual("09:30", existing_time)

    def test_execution_failures_obey_max_retries_but_missing_sources_stay_silent(self):
        settings = SimpleNamespace(tracking_max_retries=2, tracking_retry_interval_minutes=30)
        with patch("app.services.tracking_engine_v2.get_settings", return_value=settings):
            retry_state, retry_at = _execution_retry_state(1)
            review_state, review_at = _execution_retry_state(2)

        self.assertEqual("retry_wait", retry_state)
        self.assertTrue(retry_at)
        self.assertEqual(("needs_review", ""), (review_state, review_at))
        self.assertFalse(_resolution_needs_review("source_not_updated"))
        self.assertFalse(_resolution_needs_review("no_resource"))

    def test_terminal_internal_failure_enters_review_and_notifies_once(self):
        init_db()
        with db() as conn:
            task_id = int(conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,provider,retry_count,decision_state)
                VALUES(3,'tv','异常追更','p115',1,'pending')
                """
            ).lastrowid)

        with (
            patch("app.services.tracking_engine_v2.get_transfer_provider"),
            patch("app.services.tracking_engine_v2.resolve_media_target", side_effect=RuntimeError("boom")),
            patch("app.services.tracking_engine_v2._execution_retry_state", return_value=("needs_review", "")),
            patch("app.services.tracking_engine_v2._notify_job_once") as notify,
        ):
            result = run_tracking_task(task_id, tmdb=object(), qas=object(), job_id=99)

        with db() as conn:
            state = conn.execute("SELECT decision_state FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()["decision_state"]
        self.assertEqual("internal_error", result["stage"])
        self.assertEqual("needs_review", state)
        notify.assert_called_once_with(99, "异常追更", "boom", None)


if __name__ == "__main__":
    unittest.main()
