import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services import generic_webhooks
from app.services import scheduler as scheduler_service
from app.services.scheduler import run_generic_webhook_scan


class WebhookScanActionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {
            "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
            "P115_STRM_SOURCE_ROOT": "/媒体库",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/媒体库/08Bilibili"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False)
        self.environment.start()
        get_settings.cache_clear()
        init_db()
        self.action = {
            "type": "strm_scan", "provider": "p115", "directory": "/媒体库/08Bilibili",
            "mode": "incremental", "delay_seconds": 30,
        }

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_saved_scope_rejects_other_or_escaping_directories(self):
        for directory in ("/媒体库/13其他", "/媒体库/08Bilibili/../13其他", "/其他/08Bilibili", "/媒体库/08Bilibili/Season1"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                generic_webhooks.create_connection(
                    "Bili", "inbound", "", ["*"], {**self.action, "directory": directory}
                )

    @patch("app.services.scheduler.start_scheduler", return_value=MagicMock())
    def test_authenticated_event_coalesces_but_test_signal_never_scans(self, _start):
        connection = generic_webhooks.create_connection("Bili", "inbound", "", ["*"], self.action)
        headers = {"authorization": f"Bearer {connection['signing_secret']}"}
        first, _ = generic_webhooks.accept_inbound(
            connection["endpoint_key"], b'{"id":"bili-1","event":"finished"}', headers
        )
        duplicate, _ = generic_webhooks.accept_inbound(
            connection["endpoint_key"], b'{"id":"bili-1","event":"finished"}', headers
        )
        second, _ = generic_webhooks.accept_inbound(
            connection["endpoint_key"], b'{"id":"bili-2","event":"finished"}', headers
        )
        test, _ = generic_webhooks.accept_inbound(
            connection["endpoint_key"], b'{"id":"test-1"}',
            {**headers, "x-mediaindex-connection-test": "1"},
        )
        self.assertEqual(first["scan_job_id"], second["scan_job_id"])
        self.assertTrue(second["scan_coalesced"])
        self.assertTrue(duplicate["duplicate"])
        self.assertNotIn("scan_job_id", test)
        with db() as conn:
            jobs = conn.execute("SELECT id FROM transfer_jobs WHERE stage='webhook_action_waiting'").fetchall()
        self.assertEqual(1, len(jobs))

    @patch("app.services.scheduler.start_scheduler", return_value=MagicMock())
    @patch("app.services.scheduler.run_strm_job")
    def test_worker_rechecks_saved_scope_and_blocks_disabled_connection(self, runner, _start):
        connection = generic_webhooks.create_connection("Bili", "inbound", "", ["*"], self.action)
        result, _ = generic_webhooks.accept_inbound(
            connection["endpoint_key"], b'{"id":"bili-1"}',
            {"authorization": f"Bearer {connection['signing_secret']}"},
        )
        job_id = result["scan_job_id"]
        generic_webhooks.update_connection(connection["id"], enabled=False)
        run_generic_webhook_scan(job_id, connection["id"])
        runner.assert_not_called()
        with db() as conn:
            row = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(("failed", "strm_scope_missing"), (row["status"], row["stage"]))

    @patch("app.services.scheduler.start_scheduler", return_value=MagicMock())
    @patch("app.services.scheduler.run_strm_job")
    def test_full_action_passes_only_selected_directory(self, runner, _start):
        connection = generic_webhooks.create_connection("Bili", "inbound", "", ["*"], {**self.action, "mode": "full"})
        result, _ = generic_webhooks.accept_inbound(
            connection["endpoint_key"], b'{"id":"bili-1"}',
            {"authorization": f"Bearer {connection['signing_secret']}"},
        )
        run_generic_webhook_scan(result["scan_job_id"], connection["id"])
        self.assertEqual("full", runner.call_args.kwargs["mode"])
        self.assertEqual(("/媒体库/08Bilibili",), runner.call_args.kwargs["include_directories"])

    def test_restart_restores_waiting_action_without_scanning(self):
        connection = generic_webhooks.create_connection("Bili", "inbound", "", ["*"], self.action)
        with db() as conn:
            job_id = int(conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,renamed_file,
                       request_source,execution_key) VALUES('local','strm','ready',
                       'webhook_action_waiting','等待',?,?,?)""",
                (json.dumps(self.action), f"webhook-connection:{connection['id']}", "test-action"),
            ).lastrowid)
        try:
            scheduler_service.stop_scheduler()
            with patch("app.services.scheduler.BackgroundScheduler") as scheduler_class:
                instance = scheduler_class.return_value
                scheduler_service.start_scheduler()
            calls = [
                call for call in instance.add_job.call_args_list
                if call.args and call.args[0] is scheduler_service.run_generic_webhook_scan
            ]
            self.assertEqual(1, len(calls))
            self.assertEqual([job_id, connection["id"]], calls[0].kwargs["args"])
        finally:
            scheduler_service.stop_scheduler()

    def test_failed_dispatch_keeps_receipt_and_duplicate_retry_resumes_pending_job(self):
        connection = generic_webhooks.create_connection("Bili", "inbound", "", ["*"], self.action)
        headers = {"authorization": f"Bearer {connection['signing_secret']}"}
        body = b'{"id":"bili-retry","event":"finished"}'
        with patch("app.services.scheduler.dispatch_generic_webhook_scan", side_effect=RuntimeError("scheduler down")):
            with self.assertRaisesRegex(RuntimeError, "scheduler down"):
                generic_webhooks.accept_inbound(connection["endpoint_key"], body, headers)
        with db() as conn:
            deliveries = conn.execute("SELECT id FROM webhook_deliveries").fetchall()
            pending = conn.execute("SELECT id FROM transfer_jobs WHERE stage='webhook_action_waiting'").fetchall()
        self.assertEqual((1, 1), (len(deliveries), len(pending)))
        with patch("app.services.scheduler.dispatch_generic_webhook_scan") as dispatch:
            result, duplicate = generic_webhooks.accept_inbound(connection["endpoint_key"], body, headers)
        self.assertTrue(duplicate)
        self.assertEqual(pending[0]["id"], result["scan_job_id"])
        dispatch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
