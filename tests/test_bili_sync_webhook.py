import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.bili_sync_webhook import router
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services import scheduler as scheduler_service
from app.services.scheduler import _add_webhook_incremental_job, schedule_webhook_incremental_sync


class BiliSyncWebhookTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db")}, clear=False)
        self.environment.start()
        get_settings.cache_clear()
        init_db()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_disabled_and_bad_token_do_not_schedule(self):
        response = self.client.post("/api/webhooks/bili-sync", json={"event": "finished"})
        self.assertEqual(409, response.status_code)
        with patch.dict(os.environ, {
            "BILI_SYNC_WEBHOOK_ENABLED": "true",
            "BILI_SYNC_WEBHOOK_TOKEN": "b" * 32,
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                "/api/webhooks/bili-sync",
                headers={"X-MediaIndex-Webhook": "wrong"},
                json={"event": "finished"},
            )
        self.assertEqual(401, response.status_code)

    @patch("app.api.bili_sync_webhook.schedule_webhook_incremental_sync")
    def test_uses_only_bili_sync_server_scope(self, schedule):
        schedule.return_value = {"job_id": 42, "coalesced": False}
        with patch.dict(os.environ, {
            "BILI_SYNC_WEBHOOK_ENABLED": "true",
            "BILI_SYNC_WEBHOOK_TOKEN": "b" * 32,
            "BILI_SYNC_WEBHOOK_PROVIDER": "p115",
            "BILI_SYNC_WEBHOOK_SCAN_PATH": "/媒体库/08bilibili",
            "MDC_WEBHOOK_SCAN_PATH": "/媒体库/13其他",
            "P115_STRM_SOURCE_ROOT": "/媒体库",
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                "/api/webhooks/bili-sync",
                headers={"X-MediaIndex-Webhook": "b" * 32},
                json={"event": "finished", "provider": "quark", "target_path": "/other/file.mp4"},
            )
        self.assertEqual(202, response.status_code)
        self.assertEqual("/媒体库/08bilibili", response.json()["scan_path"])
        schedule.assert_called_once_with(
            "p115", "/媒体库", 300,
            scan_path="/媒体库/08bilibili", request_source="bili-sync",
        )

    def test_scan_path_must_be_within_saved_strm_selection(self):
        with patch.dict(os.environ, {
            "P115_STRM_SOURCE_ROOT": "/媒体库",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/媒体库/13其他"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False):
            get_settings.cache_clear()
            with self.assertRaisesRegex(ValueError, "不在已保存的 STRM 扫描范围"):
                schedule_webhook_incremental_sync(
                    "p115", "/媒体库", 30,
                    scan_path="/媒体库/08bilibili", request_source="bili-sync",
                )

    def test_bili_sync_scan_waits_for_cloud_upload_visibility(self):
        scheduler = MagicMock()
        before = datetime.now(timezone.utc)
        _add_webhook_incremental_job(
            scheduler, 42, "p115", "/媒体库", 300,
            scan_path="/媒体库/08bilibili", delay_seconds=300,
        )
        run_date = scheduler.add_job.call_args.kwargs["run_date"]
        self.assertGreaterEqual(run_date, before + timedelta(seconds=299))
        self.assertLessEqual(run_date, datetime.now(timezone.utc) + timedelta(seconds=301))

    def test_restart_restores_bili_sync_scope_without_using_mdc_path(self):
        with db() as conn:
            job_id = int(conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source,
                       execution_key,source_file) VALUES(
                       'local','strm','ready','webhook_waiting','等待','bili-sync',
                       'strm-webhook-scope:p115:old','/媒体库')"""
            ).lastrowid)
        environment = {
            "TRACKING_SCHEDULER_ENABLED": "false",
            "WISHLIST_SCHEDULER_ENABLED": "false",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
            "EMBY_COVER_REFRESH_ENABLED": "false",
            "P115_STRM_INCREMENTAL_CRON": "",
            "QUARK_STRM_INCREMENTAL_CRON": "",
            "P115_STRM_LIFE_MONITOR_ENABLED": "false",
            "CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false",
            "MDC_WEBHOOK_ENABLED": "false",
            "MDC_WEBHOOK_SCAN_PATH": "/媒体库/13其他",
            "BILI_SYNC_WEBHOOK_ENABLED": "true",
            "BILI_SYNC_WEBHOOK_PROVIDER": "p115",
            "BILI_SYNC_WEBHOOK_SCAN_PATH": "/媒体库/08bilibili",
            "BILI_SYNC_WEBHOOK_DEBOUNCE_SECONDS": "300",
            "P115_STRM_SOURCE_ROOT": "/媒体库",
        }
        try:
            scheduler_service.stop_scheduler()
            with patch.dict(os.environ, environment, clear=False), patch(
                "app.services.scheduler.BackgroundScheduler"
            ) as scheduler_class:
                get_settings.cache_clear()
                instance = scheduler_class.return_value
                scheduler_service.start_scheduler()
            calls = [
                call for call in instance.add_job.call_args_list
                if call.args and call.args[0] is scheduler_service.run_webhook_incremental_sync
            ]
            self.assertEqual(1, len(calls))
            self.assertEqual([job_id, "p115", "/媒体库", "/媒体库/08bilibili"], calls[0].kwargs["args"])
            self.assertGreaterEqual(
                calls[0].kwargs["run_date"], datetime.now(timezone.utc) + timedelta(seconds=299)
            )
        finally:
            scheduler_service.stop_scheduler()

    def test_bili_and_mdc_events_do_not_share_a_waiting_scan(self):
        with patch.dict(os.environ, {
            "P115_STRM_SOURCE_ROOT": "/媒体库",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/媒体库/08Bilibili"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False), patch("app.services.scheduler.start_scheduler", return_value=MagicMock()):
            get_settings.cache_clear()
            mdc = schedule_webhook_incremental_sync(
                "p115", "/媒体库", 30, scan_path="/媒体库/08Bilibili", request_source="mdc-ng"
            )
            bili = schedule_webhook_incremental_sync(
                "p115", "/媒体库", 300, scan_path="/媒体库/08Bilibili", request_source="bili-sync"
            )
        self.assertNotEqual(mdc["job_id"], bili["job_id"])
        with db() as conn:
            rows = conn.execute(
                "SELECT request_source,execution_key FROM transfer_jobs WHERE id IN (?,?)",
                (mdc["job_id"], bili["job_id"]),
            ).fetchall()
        self.assertEqual(2, len({row["execution_key"] for row in rows}))

    def test_disabled_bili_adapter_does_not_restore_its_pending_job(self):
        with db() as conn:
            job_id = int(conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source,
                       execution_key,source_file) VALUES('local','strm','ready','webhook_waiting',
                       '等待','bili-sync','old-key','/媒体库')"""
            ).lastrowid)
        try:
            scheduler_service.stop_scheduler()
            with patch.dict(os.environ, {
                "MDC_WEBHOOK_ENABLED": "true",
                "BILI_SYNC_WEBHOOK_ENABLED": "false",
            }, clear=False), patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                get_settings.cache_clear()
                scheduler_service.start_scheduler()
            calls = [
                call for call in scheduler_class.return_value.add_job.call_args_list
                if call.args and call.args[0] is scheduler_service.run_webhook_incremental_sync
            ]
            self.assertEqual([], calls)
            with db() as conn:
                row = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
            self.assertEqual(("failed", "webhook_disabled"), (row["status"], row["stage"]))
        finally:
            scheduler_service.stop_scheduler()


if __name__ == "__main__":
    unittest.main()
