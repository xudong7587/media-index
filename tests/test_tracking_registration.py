import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import EpisodeTarget, MediaTarget
from app.services.tracking_registration import TrackingRegistration, register_tracking_task


class TrackingRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "ENABLED_CLOUD_PROVIDERS": "quark",
                "QUARK_COOKIE": "__puus=test",
                "QUARK_ROOT_PATH": "/媒体库",
                "TRACKING_CHECK_TIME": "12:00",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_registration_uses_tmdb_episode_dates_and_preserves_saved_time(self):
        target = MediaTarget(
            tmdb_id=7,
            media_type="tv",
            title="测试剧",
            series_year="2026",
            category="tv",
            season_number=2,
            episodes=(EpisodeTarget(2, 1, "2026-09-01", "第一集"),),
        )
        request = TrackingRegistration(
            tmdb_id=7,
            media_type="tv",
            category="tv",
            season_number=2,
            provider="quark",
        )
        with (
            patch("app.services.tracking_registration.resolve_media_target", return_value=target),
            patch("app.services.tracking_registration.refresh_saved_episodes", return_value={"ok": True}),
        ):
            created = register_tracking_task(request)
            with db() as conn:
                conn.execute("UPDATE tracking_tasks SET check_time='09:30' WHERE id=?", (created["id"],))
            updated = register_tracking_task(request)

        with db() as conn:
            task = conn.execute(
                "SELECT check_time,provider,status FROM tracking_tasks WHERE id=?",
                (created["id"],),
            ).fetchone()
            episode = conn.execute(
                "SELECT air_date,title,provider FROM tracking_episodes WHERE task_id=? AND episode_number=1",
                (created["id"],),
            ).fetchone()
        self.assertEqual("12:00", created["check_time"])
        self.assertEqual("09:30", updated["check_time"])
        self.assertEqual(("09:30", "quark", "active"), tuple(task))
        self.assertEqual(("2026-09-01", "第一集", "quark"), tuple(episode))


if __name__ == "__main__":
    unittest.main()
