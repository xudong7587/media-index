import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_reregistering_preserves_safe_user_selected_save_path(self):
        target = MediaTarget(
            tmdb_id=8,
            media_type="tv",
            title="自定义路径剧集",
            series_year="2026",
            category="tv",
            season_number=1,
            episodes=(EpisodeTarget(1, 1, "2026-09-01", "第一集"),),
        )
        request = TrackingRegistration(
            tmdb_id=8,
            media_type="tv",
            category="tv",
            season_number=1,
            provider="quark",
        )
        custom_path = "/媒体库/tv/我选择的目录/Season 1"
        with (
            patch("app.services.tracking_registration.resolve_media_target", return_value=target),
            patch("app.services.tracking_registration.refresh_saved_episodes", return_value={"ok": True}),
        ):
            created = register_tracking_task(request)
            with db() as conn:
                conn.execute("UPDATE tracking_tasks SET save_path=? WHERE id=?", (custom_path, created["id"]))
            register_tracking_task(request)

        with db() as conn:
            stored = conn.execute("SELECT save_path FROM tracking_tasks WHERE id=?", (created["id"],)).fetchone()
        self.assertEqual(custom_path, stored["save_path"])

    def test_direct_tracking_with_parallel_first_transfer_keeps_aired_episodes_eligible(self):
        target = MediaTarget(
            tmdb_id=9,
            media_type="tv",
            title="补齐测试剧",
            series_year="2026",
            category="tv",
            season_number=1,
            episodes=(
                EpisodeTarget(1, 1, "2026-01-01", "第一集"),
                EpisodeTarget(1, 2, "2026-01-08", "第二集"),
                EpisodeTarget(1, 3, "2099-01-01", "第三集"),
            ),
        )
        request = TrackingRegistration(
            tmdb_id=9,
            media_type="tv",
            category="tv",
            season_number=1,
            provider="quark",
            backfill_existing=True,
        )
        with (
            patch("app.services.tracking_registration.resolve_media_target", return_value=target),
            patch("app.services.tracking_registration.refresh_saved_episodes", return_value={"ok": True}),
        ):
            created = register_tracking_task(request)

        with db() as conn:
            task = conn.execute(
                "SELECT auto_start_episode,next_check_at FROM tracking_tasks WHERE id=?",
                (created["id"],),
            ).fetchone()

        self.assertEqual(0, task["auto_start_episode"])
        self.assertTrue(task["next_check_at"])
        scheduled = datetime.fromisoformat(str(task["next_check_at"]).replace("Z", "+00:00"))
        self.assertGreater(scheduled, datetime.now(timezone.utc) + timedelta(minutes=119))

    def test_reregistering_does_not_unlock_an_active_tracking_execution(self):
        target = MediaTarget(
            tmdb_id=10,
            media_type="tv",
            title="执行中测试剧",
            series_year="2026",
            category="tv",
            season_number=1,
            episodes=(EpisodeTarget(1, 1, "2026-01-01", "第一集"),),
        )
        request = TrackingRegistration(
            tmdb_id=10,
            media_type="tv",
            category="tv",
            season_number=1,
            provider="quark",
            backfill_existing=True,
        )
        with (
            patch("app.services.tracking_registration.resolve_media_target", return_value=target),
            patch("app.services.tracking_registration.refresh_saved_episodes", return_value={"ok": True}),
        ):
            created = register_tracking_task(request)
            with db() as conn:
                conn.execute(
                    """
                    UPDATE tracking_tasks
                    SET decision_state='running',auto_start_episode=7,next_check_at='2030-01-02T03:04:05+00:00'
                    WHERE id=?
                    """,
                    (created["id"],),
                )
            register_tracking_task(request)

        with db() as conn:
            task = conn.execute(
                "SELECT decision_state,auto_start_episode,next_check_at FROM tracking_tasks WHERE id=?",
                (created["id"],),
            ).fetchone()
        self.assertEqual(("running", 7, "2030-01-02T03:04:05+00:00"), tuple(task))


if __name__ == "__main__":
    unittest.main()
