import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.mdc_webhook import router
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.scheduler import (
    run_webhook_incremental_sync,
    schedule_interaction_strm_directory_scan,
    schedule_interaction_strm_scans,
    schedule_webhook_incremental_sync,
)


class MdcWebhookTests(unittest.TestCase):
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

    def test_disabled_and_wrong_credentials_cannot_trigger_a_scan(self):
        response = self.client.post("/api/webhooks/strm-incremental?token=secret")
        self.assertEqual(409, response.status_code)
        self.assertIn("未启用", response.json()["detail"])
        with patch.dict(os.environ, {"MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "x" * 32}, clear=False):
            get_settings.cache_clear()
            self.assertEqual(401, self.client.post("/api/webhooks/strm-incremental?token=wrong").status_code)

    @patch("app.api.mdc_webhook.schedule_webhook_incremental_sync")
    def test_finished_event_uses_saved_scope_and_ignores_body_paths(self, schedule):
        schedule.return_value = {"job_id": 7, "coalesced": False, "provider": "p115", "root_path": "/safe"}
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true",
            "MDC_WEBHOOK_TOKEN": "s" * 32,
            "MDC_WEBHOOK_PROVIDER": "p115",
            "MDC_WEBHOOK_ROOT_PATH": "/legacy-ignored",
            "P115_STRM_SOURCE_ROOT": "/safe",
            "MDC_WEBHOOK_DEBOUNCE_SECONDS": "45",
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                f"/api/webhooks/strm-incremental?token={'s' * 32}",
                json={"event": "finished", "target_path": "/attacker-controlled"},
            )

        self.assertEqual(202, response.status_code)
        self.assertEqual("scheduled", response.json()["state"])
        schedule.assert_called_once_with("p115", "/safe", 45)

    @patch("app.api.mdc_webhook.schedule_webhook_incremental_sync")
    def test_legacy_mdc_url_remains_compatible(self, schedule):
        schedule.return_value = {"job_id": 8, "coalesced": False, "provider": "p115", "root_path": "/safe"}
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true",
            "MDC_WEBHOOK_TOKEN": "s" * 32,
            "P115_STRM_SOURCE_ROOT": "/safe",
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(f"/api/webhooks/mdc-ng?token={'s' * 32}")

        self.assertEqual(202, response.status_code)
        schedule.assert_called_once()

    def test_consecutive_events_coalesce_into_one_waiting_job(self):
        scheduler = type("FakeScheduler", (), {"calls": [], "add_job": lambda self, *args, **kwargs: self.calls.append((args, kwargs))})()
        with patch.dict(os.environ, {
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies"]',
        }, clear=False), patch(
            "app.services.scheduler.start_scheduler", return_value=scheduler
        ):
            get_settings.cache_clear()
            first = schedule_webhook_incremental_sync("p115", "/media", 30)
            second = schedule_webhook_incremental_sync("p115", "/media", 30)

        self.assertFalse(first["coalesced"])
        self.assertTrue(second["coalesced"])
        self.assertEqual(first["job_id"], second["job_id"])
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE request_source='webhook'").fetchone()[0]
        self.assertEqual(1, count)
        self.assertEqual(2, len(scheduler.calls))

    @patch("app.services.scheduler.run_strm_job")
    def test_webhook_runner_is_always_non_destructive_incremental(self, run_strm_job):
        with patch.dict(os.environ, {
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies"]',
        }, clear=False):
            get_settings.cache_clear()
            run_webhook_incremental_sync(12, "p115", "/media")

        run_strm_job.assert_called_once()
        kwargs = run_strm_job.call_args.kwargs
        self.assertEqual("incremental", kwargs["mode"])
        self.assertEqual("p115", kwargs["provider"])
        self.assertEqual("/media", kwargs["root_path"])
        self.assertEqual(("/media/Movies",), kwargs["include_directories"])

    @patch("app.services.scheduler.run_strm_job")
    def test_webhook_runner_refuses_empty_scope_instead_of_scanning_root(self, run_strm_job):
        with db() as conn:
            job_id = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                   VALUES('local','strm','ready','webhook_waiting','等待','webhook')"""
            ).lastrowid
        with patch.dict(os.environ, {
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": "[]",
        }, clear=False):
            get_settings.cache_clear()
            run_webhook_incremental_sync(int(job_id), "p115", "/media")

        run_strm_job.assert_not_called()
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(("failed", "strm_scope_missing"), (row["status"], row["stage"]))
        self.assertIn("拒绝回退为整盘扫描", row["message"])

    def test_webhook_scheduler_refuses_empty_saved_scope(self):
        with patch.dict(os.environ, {
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": "[]",
        }, clear=False):
            get_settings.cache_clear()
            with self.assertRaisesRegex(ValueError, "扫描子目录"):
                schedule_webhook_incremental_sync("p115", "/media", 30)

    @patch("app.services.scheduler.create_strm_job", side_effect=[21, 22])
    def test_interaction_scan_schedules_enabled_115_and_quark_with_saved_scopes(self, create_job):
        scheduler = type("FakeScheduler", (), {"calls": [], "add_job": lambda self, *args, **kwargs: self.calls.append((args, kwargs))})()
        with patch.dict(os.environ, {
            "P115_STRM_ENABLED": "true", "QUARK_STRM_ENABLED": "true",
            "P115_STRM_SOURCE_ROOT": "/115", "QUARK_STRM_SOURCE_ROOT": "/quark",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/115/Movies"]',
            "QUARK_STRM_INCLUDED_DIRECTORIES_JSON": '["/quark/Movies"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False), patch("app.services.scheduler.start_scheduler", return_value=scheduler):
            get_settings.cache_clear()
            jobs = schedule_interaction_strm_scans("incremental")
        self.assertEqual(["p115", "quark"], [item["provider"] for item in jobs])
        self.assertTrue(all(item["ok"] for item in jobs))
        self.assertEqual(2, create_job.call_count)
        self.assertEqual({"p115", "quark"}, {call[1]["kwargs"]["provider"] for call in scheduler.calls})

    @patch("app.services.scheduler.create_strm_job", return_value=23)
    def test_interaction_directory_scan_is_full_and_confined_to_one_direct_child(self, create_job):
        scheduler = type("FakeScheduler", (), {"calls": [], "add_job": lambda self, *args, **kwargs: self.calls.append((args, kwargs))})()
        with patch.dict(os.environ, {
            "P115_STRM_ENABLED": "true",
            "P115_STRM_SOURCE_ROOT": "/媒体库",
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False), patch("app.services.scheduler.start_scheduler", return_value=scheduler):
            get_settings.cache_clear()
            result = schedule_interaction_strm_directory_scan("p115", "/媒体库/剧集")
            with self.assertRaisesRegex(ValueError, "一级子目录"):
                schedule_interaction_strm_directory_scan("p115", "/媒体库/剧集/Season 1")
            with self.assertRaisesRegex(ValueError, "一级子目录"):
                schedule_interaction_strm_directory_scan("p115", "/其他目录/剧集")

        self.assertEqual(23, result["job_id"])
        create_job.assert_called_once()
        kwargs = scheduler.calls[0][1]["kwargs"]
        self.assertEqual("full", kwargs["mode"])
        self.assertEqual("/媒体库", kwargs["root_path"])
        self.assertEqual(("/媒体库/剧集",), kwargs["include_directories"])


if __name__ == "__main__":
    unittest.main()
