import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.media_workflow import (
    complete_transfer_workflow_step,
    initialize_media_workflow,
    list_media_workflow,
    update_media_workflow_progress,
)


class MediaWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {
            "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
            "P115_STRM_ENABLED": "true",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "false",
        })
        self.environment.start()
        get_settings.cache_clear()
        init_db()
        with db() as conn:
            self.job_id = int(conn.execute(
                "INSERT INTO transfer_jobs(tmdb_id,media_type,target,provider,status,stage,message) VALUES(?,?,?,?,?,?,?)",
                (42, "movie", "cloud", "p115", "running", "searching", "正在查询"),
            ).lastrowid)

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_initializes_workflow_with_real_landing_confirmation_step(self):
        initialize_media_workflow(self.job_id)
        result = list_media_workflow(42, "movie")
        self.assertEqual([
            "resource_search", "tmdb_rename", "transfer", "landing_confirm", "openlist_sync",
            "strm_generate", "emby_refresh", "library_notification",
        ], [step["key"] for step in result["steps"]])
        notification = next(step for step in result["steps"] if step["key"] == "library_notification")
        self.assertEqual("skipped", notification["status"])

    def test_provider_triggered_waits_for_landing_confirmation(self):
        initialize_media_workflow(self.job_id)
        complete_transfer_workflow_step(self.job_id, "triggered", "provider_triggered", "已提交，等待目录确认")

        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}

        self.assertEqual("done", steps["transfer"]["status"])
        self.assertEqual("running", steps["landing_confirm"]["status"])

    def test_provider_completed_means_target_directory_was_confirmed(self):
        initialize_media_workflow(self.job_id)
        complete_transfer_workflow_step(self.job_id, "done", "provider_completed", "目标目录已确认全部文件存在")

        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}

        self.assertEqual("done", steps["transfer"]["status"])
        self.assertEqual("done", steps["landing_confirm"]["status"])
        self.assertIn("目标目录", steps["landing_confirm"]["message"])

    def test_external_submission_does_not_claim_landing_confirmation(self):
        initialize_media_workflow(self.job_id)
        complete_transfer_workflow_step(self.job_id, "done", "provider_submitted", "外部任务已提交")

        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}

        self.assertEqual("done", steps["transfer"]["status"])
        self.assertEqual("skipped", steps["landing_confirm"]["status"])
        self.assertIn("未向 MediaIndex 提供", steps["landing_confirm"]["message"])

    def test_idle_media_does_not_offer_a_pending_openlist_step(self):
        with db() as conn:
            conn.execute("DELETE FROM transfer_jobs")

        result = list_media_workflow(999, "tv")
        openlist = next(step for step in result["steps"] if step["key"] == "openlist_sync")

        self.assertEqual("skipped", openlist["status"])

    def test_variety_workflow_keeps_its_media_type(self):
        with db() as conn:
            variety_job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(tmdb_id,media_type,target,provider,status,stage,message)
                VALUES(77,'variety','cloud','quark','running','searching','正在查询综艺')
                """
            ).lastrowid)
        initialize_media_workflow(variety_job_id)

        result = list_media_workflow(77, "variety")

        self.assertEqual(variety_job_id, result["job_id"])
        self.assertEqual("quark", result["provider"])

    def test_progress_completes_search_before_tmdb_review(self):
        initialize_media_workflow(self.job_id)
        update_media_workflow_progress(self.job_id, "candidate_review", "请核对名称")
        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}
        self.assertEqual("done", steps["resource_search"]["status"])
        self.assertEqual("review", steps["tmdb_rename"]["status"])

    def test_completed_search_never_returns_to_running(self):
        initialize_media_workflow(self.job_id)
        update_media_workflow_progress(self.job_id, "matching_files", "正在匹配")
        update_media_workflow_progress(self.job_id, "checking_saved", "正在复核目录")

        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}

        self.assertEqual("done", steps["resource_search"]["status"])

    def test_not_due_settles_every_spinner(self):
        initialize_media_workflow(self.job_id, openlist_fallback_to_p115=True)
        update_media_workflow_progress(self.job_id, "tmdb_resolving", "正在读取 TMDB")
        update_media_workflow_progress(self.job_id, "checking_saved", "正在复核目录")

        complete_transfer_workflow_step(self.job_id, "done", "not_due", "当前没有新内容")
        steps = list_media_workflow(42, "movie")["steps"]

        self.assertFalse(any(step["status"] in {"pending", "running"} for step in steps))
        self.assertEqual("done", steps[0]["status"])

    def test_storage_failure_settles_unreached_steps(self):
        initialize_media_workflow(self.job_id)
        update_media_workflow_progress(self.job_id, "tmdb_resolving", "正在读取 TMDB")
        update_media_workflow_progress(self.job_id, "checking_saved", "正在复核目录")

        complete_transfer_workflow_step(self.job_id, "failed", "storage_check_failed", "读取目录失败")
        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}

        self.assertEqual("failed", steps["resource_search"]["status"])
        self.assertFalse(any(step["status"] in {"pending", "running"} for step in steps.values()))

    def test_internal_failure_settles_search_and_all_downstream_steps(self):
        initialize_media_workflow(self.job_id, openlist_fallback_to_p115=True)

        complete_transfer_workflow_step(self.job_id, "failed", "internal_error", "转存决策异常")
        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}

        self.assertEqual("failed", steps["transfer"]["status"])
        self.assertFalse(any(step["status"] in {"pending", "running"} for step in steps.values()))

    def test_openlist_step_is_pending_only_for_explicit_quark_to_115_fallback(self):
        initialize_media_workflow(self.job_id, openlist_fallback_to_p115=True)

        steps = {step["key"]: step for step in list_media_workflow(42, "movie")["steps"]}

        self.assertEqual("pending", steps["openlist_sync"]["status"])
        self.assertIn("夸克转存完成", steps["openlist_sync"]["message"])

    def test_batch_returns_provider_lanes_with_provider_specific_strm_flow(self):
        with db() as conn:
            batch_id = int(conn.execute(
                """
                INSERT INTO transfer_batches(tmdb_id,media_type,display_title,target,status)
                VALUES(42,'movie','双盘测试','cloud','running')
                """
            ).lastrowid)
            quark_job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(tmdb_id,media_type,target,provider,status,stage,message)
                VALUES(42,'movie','cloud','quark','running','searching','正在查询夸克')
                """
            ).lastrowid)
            conn.executemany(
                "INSERT INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)",
                ((batch_id, self.job_id), (batch_id, quark_job_id)),
            )

        initialize_media_workflow(self.job_id)
        initialize_media_workflow(quark_job_id)
        result = list_media_workflow(42, "movie")
        lanes = {lane["provider"]: lane for lane in result["providers"]}

        self.assertEqual({"p115", "quark"}, set(lanes))
        self.assertEqual(batch_id, lanes["p115"]["batch_id"])
        self.assertEqual(batch_id, lanes["quark"]["batch_id"])
        p115_steps = {step["key"]: step for step in lanes["p115"]["steps"]}
        quark_steps = {step["key"]: step for step in lanes["quark"]["steps"]}
        self.assertEqual("pending", p115_steps["strm_generate"]["status"])
        self.assertEqual("skipped", quark_steps["strm_generate"]["status"])
        self.assertEqual("skipped", quark_steps["emby_refresh"]["status"])
        self.assertEqual("skipped", quark_steps["library_notification"]["status"])


if __name__ == "__main__":
    unittest.main()
