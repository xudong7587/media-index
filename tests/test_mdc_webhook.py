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
from app.services.scheduler import schedule_mdc_incremental_sync


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
        self.assertEqual(404, self.client.post("/api/webhooks/mdc-ng?token=secret").status_code)
        with patch.dict(os.environ, {"MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "x" * 32}, clear=False):
            get_settings.cache_clear()
            self.assertEqual(401, self.client.post("/api/webhooks/mdc-ng?token=wrong").status_code)

    @patch("app.api.mdc_webhook.schedule_mdc_incremental_sync")
    def test_finished_event_uses_saved_scope_and_ignores_body_paths(self, schedule):
        schedule.return_value = {"job_id": 7, "coalesced": False, "provider": "p115", "root_path": "/safe"}
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true",
            "MDC_WEBHOOK_TOKEN": "s" * 32,
            "MDC_WEBHOOK_PROVIDER": "p115",
            "MDC_WEBHOOK_ROOT_PATH": "/safe",
            "MDC_WEBHOOK_DEBOUNCE_SECONDS": "45",
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                f"/api/webhooks/mdc-ng?token={'s' * 32}",
                json={"event": "finished", "target_path": "/attacker-controlled"},
            )

        self.assertEqual(202, response.status_code)
        self.assertEqual("scheduled", response.json()["state"])
        schedule.assert_called_once_with("p115", "/safe", 45)

    def test_consecutive_events_coalesce_into_one_waiting_job(self):
        scheduler = type("FakeScheduler", (), {"calls": [], "add_job": lambda self, *args, **kwargs: self.calls.append((args, kwargs))})()
        with patch.dict(os.environ, {"STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm")}, clear=False), patch(
            "app.services.scheduler.start_scheduler", return_value=scheduler
        ):
            get_settings.cache_clear()
            first = schedule_mdc_incremental_sync("p115", "/media", 30)
            second = schedule_mdc_incremental_sync("p115", "/media", 30)

        self.assertFalse(first["coalesced"])
        self.assertTrue(second["coalesced"])
        self.assertEqual(first["job_id"], second["job_id"])
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE request_source='mdc-ng'").fetchone()[0]
        self.assertEqual(1, count)
        self.assertEqual(2, len(scheduler.calls))


if __name__ == "__main__":
    unittest.main()
