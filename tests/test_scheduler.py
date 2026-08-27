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
            if call.args and call.args[0] is scheduler.run_scheduled_tracking_patrol
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

    def test_cover_refresh_uses_five_field_cron(self):
        with patch.dict(os.environ, {
            "TRACKING_SCHEDULER_ENABLED": "false",
            "WISHLIST_SCHEDULER_ENABLED": "false",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
            "EMBY_COVER_REFRESH_ENABLED": "true",
            "EMBY_COVER_REFRESH_CRON": "15 2 1 * *",
        }, clear=False):
            get_settings.cache_clear()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                instance = scheduler_class.return_value
                scheduler.start_scheduler()

        cover_call = next(call for call in instance.add_job.call_args_list if call.kwargs.get("id") == "media-index-emby-covers")
        self.assertIs(cover_call.args[0], scheduler.run_scheduled_emby_cover_refresh)
        self.assertEqual("cron[month='*', day='1', day_of_week='*', hour='2', minute='15']", str(cover_call.args[1]))

    def test_external_notifications_schedule_library_delivery_without_cover_refresh(self):
        with patch.dict(os.environ, {
            "TRACKING_SCHEDULER_ENABLED": "false",
            "WISHLIST_SCHEDULER_ENABLED": "false",
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
            "EMBY_COVER_REFRESH_ENABLED": "false",
            "P115_STRM_INCREMENTAL_CRON": "",
            "QUARK_STRM_INCREMENTAL_CRON": "",
            "P115_STRM_LIFE_MONITOR_ENABLED": "false",
            "MDC_WEBHOOK_ENABLED": "false",
            "CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false",
        }, clear=False):
            get_settings.cache_clear()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                instance = scheduler_class.return_value
                scheduler.start_scheduler()

        delivery_calls = [
            call for call in instance.add_job.call_args_list
            if call.kwargs.get("id") == "media-index-library-notifications"
        ]
        self.assertEqual(1, len(delivery_calls))
        delivery_call = delivery_calls[0]
        self.assertIs(delivery_call.args[0], scheduler.deliver_pending_library_notifications)
        self.assertEqual("interval", delivery_call.args[1])
        self.assertEqual(1, delivery_call.kwargs["minutes"])
        self.assertEqual(1, delivery_call.kwargs["max_instances"])
        self.assertTrue(delivery_call.kwargs["coalesce"])
        self.assertFalse(any(
            call.kwargs.get("id") == "media-index-emby-covers"
            for call in instance.add_job.call_args_list
        ))

    def test_external_notifications_and_cover_refresh_do_not_duplicate_library_delivery(self):
        with patch.dict(os.environ, {
            "TRACKING_SCHEDULER_ENABLED": "false",
            "WISHLIST_SCHEDULER_ENABLED": "false",
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
            "EMBY_COVER_REFRESH_ENABLED": "true",
            "P115_STRM_INCREMENTAL_CRON": "",
            "QUARK_STRM_INCREMENTAL_CRON": "",
            "P115_STRM_LIFE_MONITOR_ENABLED": "false",
            "MDC_WEBHOOK_ENABLED": "false",
            "CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false",
        }, clear=False):
            get_settings.cache_clear()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                instance = scheduler_class.return_value
                scheduler.start_scheduler()

        delivery_calls = [
            call for call in instance.add_job.call_args_list
            if call.kwargs.get("id") == "media-index-library-notifications"
        ]
        self.assertEqual(1, len(delivery_calls))
        self.assertTrue(any(
            call.kwargs.get("id") == "media-index-emby-covers"
            for call in instance.add_job.call_args_list
        ))

    def test_event_only_cloud_download_organizer_does_not_register_a_polling_job(self):
        with patch.dict(os.environ, {
            "TRACKING_SCHEDULER_ENABLED": "false",
            "WISHLIST_SCHEDULER_ENABLED": "false",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
            "EMBY_COVER_REFRESH_ENABLED": "false",
            "P115_STRM_INCREMENTAL_CRON": "",
            "QUARK_STRM_INCREMENTAL_CRON": "",
            "P115_STRM_LIFE_MONITOR_ENABLED": "false",
            "MDC_WEBHOOK_ENABLED": "false",
            "CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "true",
            "P115_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "true",
            "QUARK_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false",
            "P115_CLOUD_DOWNLOAD_ORGANIZER_SCOPE_MODE": "all",
            "CLOUD_DOWNLOAD_ORGANIZER_TRIGGERS_JSON": '["event"]',
            "CLOUD_DOWNLOAD_ORGANIZER_INTERVAL_MINUTES": "7",
        }, clear=False):
            get_settings.cache_clear()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                instance = scheduler_class.return_value
                scheduler.start_scheduler()
        self.assertFalse(any(
            call.kwargs.get("id") == "media-index-cloud-download-organizer"
            for call in instance.add_job.call_args_list
        ))

    def test_scheduled_cloud_download_organizer_restores_bounded_interval_job(self):
        with patch.dict(os.environ, {
            "TRACKING_SCHEDULER_ENABLED": "false",
            "WISHLIST_SCHEDULER_ENABLED": "false",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
            "EMBY_COVER_REFRESH_ENABLED": "false",
            "P115_STRM_INCREMENTAL_CRON": "",
            "QUARK_STRM_INCREMENTAL_CRON": "",
            "P115_STRM_LIFE_MONITOR_ENABLED": "false",
            "MDC_WEBHOOK_ENABLED": "false",
            "P115_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "true",
            "QUARK_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false",
            "P115_CLOUD_DOWNLOAD_ORGANIZER_SCOPE_MODE": "all",
            "CLOUD_DOWNLOAD_ORGANIZER_TRIGGERS_JSON": '["scheduled"]',
            "CLOUD_DOWNLOAD_ORGANIZER_INTERVAL_MINUTES": "7",
        }, clear=False):
            get_settings.cache_clear()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                instance = scheduler_class.return_value
                scheduler.start_scheduler()

        organizer_call = next(
            call for call in instance.add_job.call_args_list
            if call.kwargs.get("id") == "media-index-cloud-download-organizer"
        )
        self.assertIs(organizer_call.args[0], scheduler.run_scheduled_cloud_download_organizer)
        self.assertEqual("interval", organizer_call.args[1])
        self.assertEqual(7, organizer_call.kwargs["minutes"])
        self.assertEqual(1, organizer_call.kwargs["max_instances"])
        self.assertTrue(organizer_call.kwargs["coalesce"])
        self.assertEqual(ANY, organizer_call.kwargs["next_run_time"])

    def test_cloud_download_organizer_result_message_keeps_all_outcomes(self):
        self.assertEqual(
            "云下载整理完成：扫描 9 项，等待稳定 2 项，已整理 4 项，待复核 1 项，失败 2 项",
            scheduler._scheduled_result_message({
                "scanned": 9,
                "waiting": 2,
                "organized": 4,
                "review": 1,
                "failed": 2,
            }),
        )


if __name__ == "__main__":
    unittest.main()
