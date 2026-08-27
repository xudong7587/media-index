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
    run_webhook_targeted_sync,
    schedule_interaction_strm_directory_scan,
    schedule_interaction_strm_scans,
    schedule_webhook_targeted_sync,
)
from app.services.strm_reconciler import StrmReconcileResult
from app.services.targeted_strm import TargetedStrmResult


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

    def test_disabled_and_wrong_credentials_cannot_trigger_targeted_work(self):
        response = self.client.post("/api/webhooks/strm-incremental?token=secret", json={"file_path": "/media/Movies/a.mkv"})
        self.assertEqual(409, response.status_code)
        with patch.dict(os.environ, {"MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "x" * 32}, clear=False):
            get_settings.cache_clear()
            self.assertEqual(401, self.client.post("/api/webhooks/strm-incremental?token=wrong", json={"file_path": "/media/Movies/a.mkv"}).status_code)

    @patch("app.api.mdc_webhook.schedule_webhook_targeted_sync")
    def test_finished_event_maps_external_root_and_schedules_exact_file(self, schedule):
        schedule.return_value = {"job_id": 7, "coalesced": False, "provider": "p115", "file_path": "/safe/Movies/a.mkv"}
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32,
            "MDC_WEBHOOK_PROVIDER": "p115", "MDC_WEBHOOK_ROOT_PATH": "/mdc-media",
            "P115_STRM_SOURCE_ROOT": "/safe", "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/safe/Movies"]',
            "MDC_WEBHOOK_DEBOUNCE_SECONDS": "45",
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                f"/api/webhooks/strm-incremental?token={'s' * 32}",
                json={"event": "finished", "file_path": "/mdc-media/Movies/a.mkv", "provider": "quark"},
            )
        self.assertEqual(202, response.status_code)
        self.assertEqual("scheduled", response.json()["state"])
        schedule.assert_called_once_with("p115", "/safe/Movies/a.mkv", 45)

    def test_settings_test_validates_without_creating_a_job(self):
        with patch.dict(os.environ, {"MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32}, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                f"/api/webhooks/mdc-ng?token={'s' * 32}",
                json={"event": "finished", "source": "mediaindex-settings-test"},
            )
        self.assertEqual(202, response.status_code)
        self.assertEqual("validated", response.json()["state"])
        with db() as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE request_source='mdc-ng'").fetchone()[0])

    def test_missing_or_out_of_scope_path_is_rejected(self):
        environment = {
            "MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32,
            "P115_STRM_SOURCE_ROOT": "/safe", "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/safe/Movies"]',
        }
        with patch.dict(os.environ, environment, clear=False):
            get_settings.cache_clear()
            missing = self.client.post(f"/api/webhooks/mdc-ng?token={'s' * 32}", json={"event": "finished"})
            outside = self.client.post(f"/api/webhooks/mdc-ng?token={'s' * 32}", json={"file_path": "/safe/TV/a.mkv"})
        self.assertEqual(422, missing.status_code)
        self.assertEqual(422, outside.status_code)

    def test_consecutive_events_coalesce_only_the_same_exact_file(self):
        scheduler = type("FakeScheduler", (), {"calls": [], "add_job": lambda self, *args, **kwargs: self.calls.append((args, kwargs))})()
        with patch.dict(os.environ, {"STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"), "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies"]'}, clear=False), patch("app.services.scheduler.start_scheduler", return_value=scheduler):
            get_settings.cache_clear()
            first = schedule_webhook_targeted_sync("p115", "/media/Movies/a.mkv", 30)
            second = schedule_webhook_targeted_sync("p115", "/media/Movies/a.mkv", 30)
            third = schedule_webhook_targeted_sync("p115", "/media/Movies/b.mkv", 30)
        self.assertFalse(first["coalesced"])
        self.assertTrue(second["coalesced"])
        self.assertFalse(third["coalesced"])
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertNotEqual(first["job_id"], third["job_id"])
        with db() as conn:
            self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE request_source='mdc-ng'").fetchone()[0])

    @patch("app.services.scheduler.index_and_reconcile_targeted_strm")
    def test_webhook_runner_calls_targeted_service_not_scan_job(self, targeted):
        targeted.return_value = TargetedStrmResult(1, (4,), StrmReconcileResult(created=1))
        with db() as conn:
            job_id = int(conn.execute("""INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                VALUES('local','strm','ready','mdc_webhook_waiting','等待','mdc-ng')""").lastrowid)
        with patch.dict(os.environ, {"STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm")}, clear=False):
            get_settings.cache_clear()
            run_webhook_targeted_sync(job_id, "p115", "/media/Movies/a.mkv")
        targeted.assert_called_once()
        self.assertEqual(({"file_name": "a.mkv", "path": "/media/Movies/a.mkv"},), targeted.call_args.kwargs["target_files"])
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(("done", "mdc_target_completed"), (row["status"], row["stage"]))
        self.assertIn("未扫描其他目录", row["message"])

    @patch("app.services.scheduler.create_strm_job", side_effect=[21, 22])
    def test_interaction_scan_schedules_enabled_115_and_quark_with_saved_scopes(self, create_job):
        scheduler = type("FakeScheduler", (), {"calls": [], "add_job": lambda self, *args, **kwargs: self.calls.append((args, kwargs))})()
        with patch.dict(os.environ, {
            "P115_STRM_ENABLED": "true", "QUARK_STRM_ENABLED": "true",
            "P115_STRM_SOURCE_ROOT": "/115", "QUARK_STRM_SOURCE_ROOT": "/quark",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/115/Movies"]', "QUARK_STRM_INCLUDED_DIRECTORIES_JSON": '["/quark/Movies"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False), patch("app.services.scheduler.start_scheduler", return_value=scheduler):
            get_settings.cache_clear()
            jobs = schedule_interaction_strm_scans("incremental")
        self.assertEqual(["p115", "quark"], [item["provider"] for item in jobs])
        self.assertTrue(all(item["ok"] for item in jobs))
        self.assertEqual(2, create_job.call_count)

    @patch("app.services.scheduler.create_strm_job", return_value=23)
    def test_interaction_directory_scan_is_full_and_confined_to_one_direct_child(self, create_job):
        scheduler = type("FakeScheduler", (), {"calls": [], "add_job": lambda self, *args, **kwargs: self.calls.append((args, kwargs))})()
        with patch.dict(os.environ, {"P115_STRM_ENABLED": "true", "P115_STRM_SOURCE_ROOT": "/媒体库", "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm")}, clear=False), patch("app.services.scheduler.start_scheduler", return_value=scheduler):
            get_settings.cache_clear()
            result = schedule_interaction_strm_directory_scan("p115", "/媒体库/剧集")
            with self.assertRaisesRegex(ValueError, "一级子目录"):
                schedule_interaction_strm_directory_scan("p115", "/媒体库/剧集/Season 1")
        self.assertEqual(23, result["job_id"])


if __name__ == "__main__":
    unittest.main()
