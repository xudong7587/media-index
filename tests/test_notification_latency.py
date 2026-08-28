import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.api.emby import _queue_emby_library_notification
from app.api.transfers import MediaPlanInput, TransferCreate, _predictable_multi_episode_batch
from app.core.config import get_settings
from app.db.database import init_db
from app.services.scheduler import _add_webhook_incremental_job, _add_webhook_job


class NotificationLatencyTests(unittest.TestCase):
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

    def test_only_contiguous_multi_episode_snapshot_defers_batch_notification(self):
        def payload(episodes, urls=()):
            return TransferCreate(
                tmdb_id=1,
                media_type="tv",
                title="测试剧",
                episode_numbers=list(episodes),
                preferred_share_urls=list(urls),
            )

        self.assertTrue(_predictable_multi_episode_batch([(payload((1, 2, 3), ("https://example.test/share",)), 1)]))
        self.assertFalse(_predictable_multi_episode_batch([(payload((1,), ("https://example.test/share",)), 1)]))
        self.assertFalse(_predictable_multi_episode_batch([(payload((1, 3), ("https://example.test/share",)), 1)]))
        self.assertFalse(_predictable_multi_episode_batch([(payload((1, 2, 3)), 1)]))
        movie = TransferCreate(tmdb_id=2, media_type="movie", title="电影", preferred_share_urls=["https://example.test/share"])
        self.assertFalse(_predictable_multi_episode_batch([(movie, 2)]))
        planned = payload(())
        planned.media_plan = MediaPlanInput(
            entrypoint="discover",
            episode_numbers=[5, 6],
            preferred_share_urls=["https://example.test/frozen"],
        )
        self.assertTrue(_predictable_multi_episode_batch([(planned, 3)]))

    @patch("app.api.emby._cache_emby_notification_poster", return_value="poster")
    @patch("app.api.emby.add_notification", return_value=True)
    def test_emby_single_item_library_feedback_is_delivered_immediately(self, add, _poster):
        with patch("app.api.emby._should_defer_emby_library_notification", return_value=False):
            self.assertTrue(_queue_emby_library_notification({"Event": "library.new", "Name": "测试电影"}, "入库"))
        self.assertTrue(add.call_args.kwargs["deliver"])

    @patch("app.api.emby._cache_emby_notification_poster", return_value="poster")
    @patch("app.api.emby.add_notification", return_value=True)
    def test_known_multi_episode_library_feedback_remains_aggregated(self, add, _poster):
        with patch("app.api.emby._should_defer_emby_library_notification", return_value=True):
            self.assertTrue(_queue_emby_library_notification({"Event": "library.new", "SeriesName": "测试剧"}, "入库"))
        self.assertFalse(add.call_args.kwargs["deliver"])

    def test_webhook_jobs_are_scheduled_without_a_debounce_delay(self):
        scheduler = MagicMock()
        before = datetime.now(timezone.utc)
        _add_webhook_job(scheduler, 1, "p115", "/media/a.mkv", 300)
        _add_webhook_incremental_job(scheduler, 2, "p115", "/media", 300, scan_path="/media/Movies")
        after = datetime.now(timezone.utc)
        for call in scheduler.add_job.call_args_list:
            run_date = call.kwargs["run_date"]
            self.assertGreaterEqual(run_date, before - timedelta(seconds=1))
            self.assertLessEqual(run_date, after + timedelta(seconds=1))

if __name__ == "__main__":
    unittest.main()
