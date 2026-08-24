import os
import unittest
from unittest.mock import ANY, patch

from app.core.config import get_settings
from app.services import scheduler


class SchedulerTests(unittest.TestCase):
    def tearDown(self):
        scheduler.stop_scheduler()
        get_settings.cache_clear()

    def test_tracking_scheduler_runs_due_cards_immediately_after_start(self):
        with patch.dict(
            os.environ,
            {
                "TRACKING_SCHEDULER_ENABLED": "true",
                "WISHLIST_SCHEDULER_ENABLED": "false",
                "NOTIFICATION_EXTERNAL_ENABLED": "false",
                "OPENLIST_ENABLED": "false",
            },
        ):
            get_settings.cache_clear()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                instance = scheduler_class.return_value
                scheduler.start_scheduler()

        tracking_call = next(
            call for call in instance.add_job.call_args_list
            if call.args and call.args[0] is scheduler.run_due_tracking_tasks
        )
        self.assertEqual("interval", tracking_call.args[1])
        self.assertEqual(ANY, tracking_call.kwargs["next_run_time"])
        instance.start.assert_called_once()

    def test_openlist_auto_sync_does_not_schedule_full_library_copy(self):
        with patch.dict(
            os.environ,
            {
                "TRACKING_SCHEDULER_ENABLED": "false",
                "WISHLIST_SCHEDULER_ENABLED": "false",
                "NOTIFICATION_EXTERNAL_ENABLED": "false",
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
            },
        ):
            get_settings.cache_clear()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                self.assertIsNone(scheduler.start_scheduler())

        scheduler_class.assert_not_called()

    def test_provider_cron_schedules_incremental_strm_only(self):
        with patch.dict(os.environ, {
            "TRACKING_SCHEDULER_ENABLED": "false",
            "WISHLIST_SCHEDULER_ENABLED": "false",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
            "P115_STRM_INCREMENTAL_CRON": "0 */6 * * *",
        }, clear=False):
            get_settings.cache_clear()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                instance = scheduler_class.return_value
                scheduler.start_scheduler()
        cron_call = next(call for call in instance.add_job.call_args_list if call.kwargs.get("id") == "media-index-p115-strm-incremental")
        self.assertIs(cron_call.args[0], scheduler.run_scheduled_strm_scan)
        self.assertEqual(["p115"], cron_call.kwargs["args"])


if __name__ == "__main__":
    unittest.main()
