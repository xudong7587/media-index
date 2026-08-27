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
    run_webhook_targeted_sync,
    schedule_interaction_strm_directory_scan,
    schedule_interaction_strm_scans,
    schedule_webhook_incremental_sync,
    schedule_webhook_targeted_sync,
)
from app.services.strm_reconciler import StrmReconcileResult
from app.services.targeted_strm import TargetedStrmError, TargetedStrmResult


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

    @patch("app.api.mdc_webhook.schedule_webhook_incremental_sync")
    def test_finished_event_uses_saved_provider_root_and_ignores_external_scope(self, schedule):
        schedule.return_value = {"job_id": 7, "coalesced": False, "provider": "p115", "root_path": "/safe"}
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
        schedule.assert_called_once_with("p115", "/safe", 45)

    @patch("app.api.mdc_webhook.schedule_webhook_incremental_sync")
    def test_post_body_does_not_need_a_file_path(self, schedule):
        schedule.return_value = {"job_id": 8, "coalesced": False, "provider": "p115", "root_path": "/safe/Movies"}
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32,
            "MDC_WEBHOOK_ROOT_PATH": "/media/output", "P115_STRM_SOURCE_ROOT": "/safe/Movies",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/safe/Movies/TEST-001"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                f"/api/webhooks/mdc-ng?token={'s' * 32}",
                json={"event": "finished"},
            )
        self.assertEqual(202, response.status_code)
        schedule.assert_called_once_with("p115", "/safe/Movies", 30)

    @patch("app.api.mdc_webhook.schedule_webhook_incremental_sync")
    def test_get_query_cannot_override_saved_scan_root(self, schedule):
        schedule.return_value = {"job_id": 9, "coalesced": False, "provider": "p115", "root_path": "/safe"}
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32,
            "MDC_WEBHOOK_ROOT_PATH": "/mdc-media", "P115_STRM_SOURCE_ROOT": "/safe",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/safe/Movies"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.get(
                "/api/webhooks/mdc-ng",
                params={
                    "token": "s" * 32,
                    "path": "/mdc-media/Movies/source.mkv",
                    "target_path": "/mdc-media/Movies/a.mkv",
                },
            )
        self.assertEqual(202, response.status_code)
        schedule.assert_called_once_with("p115", "/safe", 30)

    def test_settings_test_validates_without_creating_a_job(self):
        with patch.dict(os.environ, {"MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32}, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                f"/api/webhooks/mdc-ng?token={'s' * 32}",
                headers={"X-MediaIndex-Settings-Test": "1"},
                json={"event": "finished", "source": "mediaindex-settings-test"},
            )
        self.assertEqual(202, response.status_code)
        self.assertEqual("validated", response.json()["state"])
        with db() as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE request_source='mdc-ng'").fetchone()[0])

    @patch("app.api.mdc_webhook.schedule_webhook_incremental_sync")
    def test_missing_or_outside_request_path_still_uses_saved_scope(self, schedule):
        schedule.return_value = {"job_id": 10, "coalesced": False, "provider": "p115", "root_path": "/safe"}
        environment = {
            "MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32,
            "P115_STRM_SOURCE_ROOT": "/safe", "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/safe/Movies"]',
        }
        with patch.dict(os.environ, environment, clear=False):
            get_settings.cache_clear()
            missing = self.client.post(f"/api/webhooks/mdc-ng?token={'s' * 32}", json={"event": "finished"})
            outside = self.client.post(f"/api/webhooks/mdc-ng?token={'s' * 32}", json={"file_path": "/safe/TV/a.mkv"})
        self.assertEqual(202, missing.status_code)
        self.assertEqual(202, outside.status_code)
        self.assertEqual(
            [("p115", "/safe", 30), ("p115", "/safe", 30)],
            [call.args for call in schedule.call_args_list],
        )

    def test_consecutive_events_coalesce_by_saved_scan_root(self):
        scheduler = type("FakeScheduler", (), {"calls": [], "add_job": lambda self, *args, **kwargs: self.calls.append((args, kwargs))})()
        with patch.dict(os.environ, {"STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"), "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies"]'}, clear=False), patch("app.services.scheduler.start_scheduler", return_value=scheduler):
            get_settings.cache_clear()
            first = schedule_webhook_incremental_sync("p115", "/media", 30)
            second = schedule_webhook_incremental_sync("p115", "/media", 30)
            third = schedule_webhook_incremental_sync("p115", "/other", 30)
        self.assertFalse(first["coalesced"])
        self.assertTrue(second["coalesced"])
        self.assertFalse(third["coalesced"])
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertNotEqual(first["job_id"], third["job_id"])
        with db() as conn:
            self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE request_source='mdc-ng'").fetchone()[0])

    @patch("app.services.scheduler.run_strm_job")
    def test_incremental_runner_uses_saved_directories_and_simplifies_success_message(self, run_job):
        with db() as conn:
            job_id = int(conn.execute("""INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                VALUES('local','strm','ready','webhook_waiting','等待','mdc-ng')""").lastrowid)

        def complete(job_id, **_kwargs):
            with db() as conn:
                conn.execute(
                    "UPDATE transfer_jobs SET status='done',stage='strm_completed',message='扫描 99，跳过 3' WHERE id=?",
                    (job_id,),
                )

        run_job.side_effect = complete
        with patch.dict(os.environ, {
            "P115_STRM_SOURCE_ROOT": "/media",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies", "/media/TV"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False):
            get_settings.cache_clear()
            run_webhook_incremental_sync(job_id, "p115", "/media")
        self.assertEqual("incremental", run_job.call_args.kwargs["mode"])
        self.assertEqual(("/media/Movies", "/media/TV"), run_job.call_args.kwargs["include_directories"])
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(("done", "strm_completed", "已完成 STRM 生成"), tuple(row))

    @patch("app.services.scheduler.refresh_emby_library_after_strm", return_value="；已通知 Emby 刷新")
    @patch("app.services.scheduler.index_and_reconcile_targeted_strm")
    def test_webhook_runner_calls_targeted_service_then_refreshes_emby(self, targeted, refresh_emby):
        targeted.return_value = TargetedStrmResult(1, (4,), StrmReconcileResult(created=1))
        with db() as conn:
            job_id = int(conn.execute("""INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                VALUES('local','strm','ready','mdc_webhook_waiting','等待','mdc-ng')""").lastrowid)
        with patch.dict(os.environ, {"STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm")}, clear=False):
            get_settings.cache_clear()
            run_webhook_targeted_sync(job_id, "p115", "/media/Movies/a.mkv")
        targeted.assert_called_once()
        self.assertEqual(({"file_name": "a.mkv", "path": "/media/Movies/a.mkv"},), targeted.call_args.kwargs["target_files"])
        refresh_emby.assert_called_once_with(str(Path(self.tempdir.name) / "strm"))
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(("done", "mdc_target_completed"), (row["status"], row["stage"]))
        self.assertIn("未扫描其他目录", row["message"])
        self.assertIn("已通知 Emby 刷新", row["message"])

    @patch("app.services.scheduler.index_and_reconcile_targeted_strm", side_effect=TargetedStrmError("目标文件未唯一确认：a.mkv；token=not-safe"))
    def test_webhook_runner_persists_safe_failure_detail(self, targeted):
        with db() as conn:
            job_id = int(conn.execute("""INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                VALUES('local','strm','ready','mdc_webhook_waiting','等待','mdc-ng')""").lastrowid)
        run_webhook_targeted_sync(job_id, "p115", "/media/Movies/a.mkv")
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(("failed", "mdc_target_failed"), (row["status"], row["stage"]))
        self.assertIn("目标文件未唯一确认：a.mkv", row["message"])
        self.assertIn("token=[已隐藏]", row["message"])
        self.assertNotIn("not-safe", row["message"])

    def test_webhook_runner_classifies_non_mutating_results_without_emby_refresh(self):
        cases = (
            (StrmReconcileResult(conflicts=1), "failed", "mdc_target_failed", "STRM 路径冲突"),
            (StrmReconcileResult(filtered=1), "done", "mdc_target_skipped", "目标均被过滤"),
            (StrmReconcileResult(), "done", "mdc_target_skipped", "未产生可生成的 STRM 结果"),
            (StrmReconcileResult(unchanged=1), "done", "mdc_target_completed", "已跳过 Emby 刷新"),
        )
        with patch.dict(os.environ, {"STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm")}, clear=False), patch(
            "app.services.scheduler.index_and_reconcile_targeted_strm",
            side_effect=[TargetedStrmResult(1, (4,), result) for result, *_ in cases],
        ), patch("app.services.scheduler.refresh_emby_library_after_strm") as refresh_emby:
            get_settings.cache_clear()
            for index, (_result, expected_status, expected_stage, expected_message) in enumerate(cases):
                with db() as conn:
                    job_id = int(conn.execute(
                        """INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                           VALUES('local','strm','ready','mdc_webhook_waiting','等待','mdc-ng')"""
                    ).lastrowid)
                run_webhook_targeted_sync(job_id, "p115", f"/media/Movies/{index}.mkv")
                with db() as conn:
                    row = conn.execute(
                        "SELECT status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)
                    ).fetchone()
                self.assertEqual((expected_status, expected_stage), (row["status"], row["stage"]))
                self.assertIn(expected_message, row["message"])
        refresh_emby.assert_not_called()

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
