import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.mdc_webhook import _complete_unique_interaction_download, router
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services import scheduler as scheduler_service
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

    def test_mdc_completion_closes_only_one_unambiguous_interaction_waiter(self):
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                   VALUES('cloud','p115','triggered','provider_target_monitoring','等待外部完成','telegram')"""
            )
            job_id = int(cursor.lastrowid)
        self.assertEqual(job_id, _complete_unique_interaction_download("p115", 77))
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual("done", row["status"])
        self.assertEqual("provider_completed", row["stage"])
        self.assertIn("#77", row["message"])

    def test_mdc_completion_does_not_guess_between_multiple_waiters(self):
        with db() as conn:
            for source in ("telegram", "wecom"):
                conn.execute(
                    """INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                       VALUES('cloud','p115','triggered','provider_target_monitoring','等待外部完成',?)""",
                    (source,),
                )
        self.assertIsNone(_complete_unique_interaction_download("p115", 78))

    def test_disabled_and_wrong_credentials_cannot_trigger_targeted_work(self):
        response = self.client.post("/api/webhooks/strm-incremental?token=secret", json={"file_path": "/media/Movies/a.mkv"})
        self.assertEqual(409, response.status_code)
        with patch.dict(os.environ, {"MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "x" * 32}, clear=False):
            get_settings.cache_clear()
            self.assertEqual(401, self.client.post("/api/webhooks/strm-incremental?token=wrong", json={"file_path": "/media/Movies/a.mkv"}).status_code)

    @patch("app.api.mdc_webhook.schedule_webhook_targeted_sync")
    def test_finished_event_maps_external_root_and_schedules_targeted_path(self, schedule):
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
        self.assertEqual("targeted", response.json()["scope"])
        schedule.assert_called_once_with("p115", "/safe/Movies/a.mkv", 45)

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
        self.assertEqual("saved_incremental", response.json()["scope"])
        schedule.assert_called_once_with("p115", "/safe/Movies", 30)

    @patch("app.api.mdc_webhook.schedule_webhook_incremental_sync")
    def test_configured_scan_path_makes_webhook_a_path_independent_signal(self, schedule):
        schedule.return_value = {
            "job_id": 18,
            "coalesced": False,
            "provider": "p115",
            "root_path": "/safe",
            "scan_path": "/safe/Movies",
        }
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32,
            "MDC_WEBHOOK_PROVIDER": "p115", "MDC_WEBHOOK_SCAN_PATH": "/safe/Movies",
            "P115_STRM_SOURCE_ROOT": "/safe",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/safe/Movies", "/safe/TV"]',
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                f"/api/webhooks/mdc-ng?token={'s' * 32}",
                json={"event": "finished", "target_path": "/wrong/container/path.mkv"},
            )
        self.assertEqual(202, response.status_code)
        self.assertEqual("configured_incremental", response.json()["scope"])
        schedule.assert_called_once_with("p115", "/safe", 30, scan_path="/safe/Movies")

    @patch("app.api.mdc_webhook.schedule_webhook_incremental_sync")
    def test_configured_scan_path_accepts_an_authorized_deep_directory(self, schedule):
        schedule.return_value = {
            "job_id": 19, "coalesced": False, "provider": "p115",
            "root_path": "/safe", "scan_path": "/safe/Movies/Series/Season 1",
        }
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32,
            "MDC_WEBHOOK_PROVIDER": "p115", "MDC_WEBHOOK_SCAN_PATH": "/safe/Movies/Series/Season 1",
            "P115_STRM_SOURCE_ROOT": "/safe",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/safe/Movies", "/safe/TV"]',
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(f"/api/webhooks/mdc-ng?token={'s' * 32}", json={"event": "finished"})
        self.assertEqual(202, response.status_code)
        self.assertEqual("configured_incremental", response.json()["scope"])
        schedule.assert_called_once_with("p115", "/safe", 30, scan_path="/safe/Movies/Series/Season 1")

    @patch("app.api.mdc_webhook.schedule_webhook_targeted_sync")
    def test_finished_event_accepts_an_authorized_nested_directory(self, schedule):
        schedule.return_value = {"job_id": 81, "coalesced": False, "provider": "p115", "file_path": "/safe/Movies/Series/Season 1"}
        with patch.dict(os.environ, {
            "MDC_WEBHOOK_ENABLED": "true", "MDC_WEBHOOK_TOKEN": "s" * 32,
            "MDC_WEBHOOK_PROVIDER": "p115", "MDC_WEBHOOK_ROOT_PATH": "/mdc-media",
            "P115_STRM_SOURCE_ROOT": "/safe", "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/safe/Movies"]',
        }, clear=False):
            get_settings.cache_clear()
            response = self.client.post(
                f"/api/webhooks/mdc-ng?token={'s' * 32}",
                json={"event": "finished", "target_path": "/mdc-media/Movies/Series/Season 1"},
            )
        self.assertEqual(202, response.status_code)
        self.assertEqual("targeted", response.json()["scope"])
        schedule.assert_called_once_with("p115", "/safe/Movies/Series/Season 1", 30)

    @patch("app.api.mdc_webhook.schedule_webhook_targeted_sync")
    def test_get_query_prefers_target_path_but_cannot_override_provider(self, schedule):
        schedule.return_value = {"job_id": 9, "coalesced": False, "provider": "p115", "file_path": "/safe/Movies/a.mkv"}
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
        schedule.assert_called_once_with("p115", "/safe/Movies/a.mkv", 30)

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
    def test_missing_or_outside_request_path_falls_back_to_saved_scope(self, schedule):
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
        self.assertEqual("saved_incremental", missing.json()["scope"])
        self.assertEqual("saved_incremental", outside.json()["scope"])
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

    def test_startup_restores_targeted_waiting_rows_without_widening_scope(self):
        with db() as conn:
            legacy_job_ids = [
                int(conn.execute(
                    """INSERT INTO transfer_jobs(
                           target,provider,status,stage,message,display_title,save_path,source_file,
                           request_source,execution_key
                       ) VALUES(
                           'local','strm','ready','mdc_webhook_waiting','等待旧任务恢复',
                           'MDC-NG 定点 STRM',?,?, 'mdc-ng',?
                       )""",
                    (str(Path(self.tempdir.name) / "strm"), source_file, execution_key),
                ).lastrowid)
                for source_file, execution_key in (
                    ("/media/Movies/a.mkv", "strm-webhook:p115:legacy-a"),
                    ("/media/TV/b.mkv", "strm-webhook:p115:legacy-b"),
                )
            ]

        environment = {
            "TRACKING_SCHEDULER_ENABLED": "false",
            "WISHLIST_SCHEDULER_ENABLED": "false",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
            "EMBY_COVER_REFRESH_ENABLED": "false",
            "P115_STRM_INCREMENTAL_CRON": "",
            "QUARK_STRM_INCREMENTAL_CRON": "",
            "P115_STRM_LIFE_MONITOR_ENABLED": "false",
            "CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false",
            "MDC_WEBHOOK_ENABLED": "true",
            "MDC_WEBHOOK_PROVIDER": "p115",
            "P115_STRM_SOURCE_ROOT": "/media",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies", "/media/TV"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }
        try:
            scheduler_service.stop_scheduler()
            with patch.dict(os.environ, environment, clear=False), patch(
                "app.services.scheduler.BackgroundScheduler"
            ) as scheduler_class:
                get_settings.cache_clear()
                instance = scheduler_class.return_value
                scheduler_service.start_scheduler()

            restored_calls = [
                call
                for call in instance.add_job.call_args_list
                if call.args and call.args[0] is scheduler_service.run_webhook_targeted_sync
            ]
            self.assertEqual(2, len(restored_calls))
            self.assertEqual(
                set(legacy_job_ids),
                {int(call.kwargs["args"][0]) for call in restored_calls},
            )
            self.assertEqual(2, len({str(call.kwargs["id"]) for call in restored_calls}))
            self.assertTrue(all(
                str(call.kwargs["id"]).endswith(f"-{call.kwargs['args'][0]}")
                for call in restored_calls
            ))
            with db() as conn:
                restored_rows = conn.execute(
                    """SELECT id,stage,source_file,execution_key FROM transfer_jobs
                       WHERE id IN (?,?) ORDER BY id""",
                    tuple(legacy_job_ids),
                ).fetchall()
            self.assertEqual(
                [
                    (legacy_job_ids[0], "mdc_webhook_waiting", "/media/Movies/a.mkv"),
                    (legacy_job_ids[1], "mdc_webhook_waiting", "/media/TV/b.mkv"),
                ],
                [(int(row["id"]), row["stage"], row["source_file"]) for row in restored_rows],
            )
            restored_execution_keys = {str(row["execution_key"]) for row in restored_rows}
            self.assertEqual(2, len(restored_execution_keys))
            self.assertTrue(all(key.startswith("strm-webhook:p115:") for key in restored_execution_keys))
        finally:
            scheduler_service.stop_scheduler()

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

    @patch("app.services.scheduler.run_strm_job")
    def test_incremental_runner_can_limit_work_to_configured_webhook_directory(self, run_job):
        with db() as conn:
            job_id = int(conn.execute("""INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                VALUES('local','strm','ready','webhook_waiting','等待','mdc-ng')""").lastrowid)
        with patch.dict(os.environ, {
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies", "/media/TV"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False):
            get_settings.cache_clear()
            run_webhook_incremental_sync(job_id, "p115", "/media", "/media/TV")
        self.assertEqual(("/media/TV",), run_job.call_args.kwargs["include_directories"])

    @patch("app.services.scheduler.run_strm_job")
    def test_incremental_runner_can_limit_work_to_authorized_deep_directory(self, run_job):
        with db() as conn:
            job_id = int(conn.execute("""INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                VALUES('local','strm','ready','webhook_waiting','等待','mdc-ng')""").lastrowid)
        with patch.dict(os.environ, {
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies", "/media/TV"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False):
            get_settings.cache_clear()
            run_webhook_incremental_sync(job_id, "p115", "/media", "/media/TV/Series/Season 1")
        self.assertEqual(("/media/TV/Series/Season 1",), run_job.call_args.kwargs["include_directories"])

    @patch("app.services.scheduler.refresh_emby_library_after_strm", return_value="；已通知 Emby 刷新")
    @patch("app.services.scheduler.index_and_reconcile_targeted_path")
    def test_webhook_runner_calls_targeted_service_then_refreshes_emby(self, targeted, refresh_emby):
        targeted.return_value = TargetedStrmResult(1, (4,), StrmReconcileResult(created=1))
        with db() as conn:
            job_id = int(conn.execute("""INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source)
                VALUES('local','strm','ready','mdc_webhook_waiting','等待','mdc-ng')""").lastrowid)
        with patch.dict(os.environ, {"STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm")}, clear=False):
            get_settings.cache_clear()
            run_webhook_targeted_sync(job_id, "p115", "/media/Movies/a.mkv")
        targeted.assert_called_once()
        self.assertEqual("/media/Movies/a.mkv", targeted.call_args.kwargs["target_path"])
        refresh_emby.assert_called_once_with(str(Path(self.tempdir.name) / "strm"))
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(("done", "mdc_target_completed"), (row["status"], row["stage"]))
        self.assertIn("未扫描范围外目录", row["message"])
        self.assertIn("定点处理", row["message"])
        self.assertIn("已通知 Emby 刷新", row["message"])

    @patch("app.services.scheduler.index_and_reconcile_targeted_path", side_effect=TargetedStrmError("目标文件未唯一确认：a.mkv；token=not-safe"))
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
            "app.services.scheduler.index_and_reconcile_targeted_path",
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
