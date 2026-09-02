import os
import unittest
from unittest.mock import patch

from app.core.config import get_settings
from app.services.post_transfer_pipeline import (
    run_confirmed_native_transfer_post_processing,
    run_post_transfer_pipeline,
    try_targeted_cloud_download_organization,
)
from app.services.strm_reconciler import StrmReconcileResult
from app.services.targeted_strm import TargetedStrmResult


class PostTransferPipelineTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def test_disabled_quark_organizer_reports_that_openlist_completion_will_not_start(self):
        with patch.dict(
            os.environ,
            {"QUARK_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false", "CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false"},
            clear=False,
        ):
            get_settings.cache_clear()
            handled, message = try_targeted_cloud_download_organization(
                provider="quark",
                target_path="/strm/download/03电视剧/秘令 (2020)",
                target_files=({"file_id": "q-1", "file_name": "秘令.2020.S02E01.mkv"},),
                media_title="秘令",
                media_year="2020",
            )
        self.assertFalse(handled)
        self.assertIn("夸克云下载整理未启用", message)
        self.assertIn("115/OpenList", message)

    def test_native_quark_generates_only_exact_transfer_outputs_and_refreshes_emby(self):
        environment = {
            "QUARK_STRM_ENABLED": "true",
            "QUARK_ROOT_PATH": "/Media",
            "QUARK_STRM_SOURCE_ROOT": "/Media",
            "QUARK_STRM_INCLUDED_DIRECTORIES_JSON": '["/Media/Movies"]',
            "STRM_OUTPUT_ROOT": "/strm",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
        }
        targeted_result = TargetedStrmResult(1, (41,), StrmReconcileResult(created=1))
        outputs = ({"file_id": "q-1", "parent_id": "d-1", "file_name": "测试影片.2026.mkv", "path": "/Media/Movies/测试影片 (2026)"},)
        with patch.dict(os.environ, environment), patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress, patch("app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm", return_value=targeted_result) as targeted, patch("app.services.post_transfer_pipeline.refresh_emby_library_after_strm", return_value="刷新已提交") as refresh:
            get_settings.cache_clear()
            run_post_transfer_pipeline(9, provider="quark", title="测试影片", poster_url="https://image.test/poster.jpg", target_path="/Media/Movies/测试影片 (2026)", target_files=outputs)
        targeted.assert_called_once()
        self.assertEqual(outputs, targeted.call_args.kwargs["target_files"])
        self.assertEqual("/Media/Movies/测试影片 (2026)", targeted.call_args.kwargs["target_path"])
        refresh.assert_called_once_with("/strm")
        self.assertIn((9, "library_notification", "running", "已请求 Emby 刷新，等待入库 Webhook 确认后通知"), [call.args for call in progress.call_args_list])

    def test_legacy_qas_does_not_impersonate_native_quark_strm(self):
        with patch.dict(os.environ, {"QUARK_STRM_ENABLED": "true", "NOTIFICATION_EXTERNAL_ENABLED": "false"}), patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress, patch("app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm") as targeted:
            get_settings.cache_clear()
            run_post_transfer_pipeline(10, provider="qas", title="旧任务")
        targeted.assert_not_called()
        self.assertIn((10, "strm_generate", "skipped", "当前网盘未启用自动 STRM 生成"), [call.args for call in progress.call_args_list])

    def test_provider_without_strm_stops_after_transfer_even_when_other_provider_has_strm(self):
        environment = {
            "P115_STRM_ENABLED": "true",
            "QUARK_STRM_ENABLED": "false",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
        }
        with (
            patch.dict(os.environ, environment),
            patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress,
            patch("app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm") as targeted,
        ):
            get_settings.cache_clear()
            run_post_transfer_pipeline(11, provider="quark", title="仅转存测试")

        targeted.assert_not_called()
        steps = {call.args[1]: call.args[2:] for call in progress.call_args_list}
        self.assertEqual(("skipped", "当前网盘未启用自动 STRM 生成"), steps["strm_generate"])
        self.assertEqual("skipped", steps["emby_refresh"][0])
        self.assertEqual(("skipped", "当前网盘在转存完成后结束流程"), steps["library_notification"])

    def test_tracking_batch_defers_library_notification_until_all_provider_lanes_finish(self):
        environment = {
            "QUARK_STRM_ENABLED": "true",
            "QUARK_ROOT_PATH": "/Media",
            "QUARK_STRM_SOURCE_ROOT": "/Media",
            "QUARK_STRM_INCLUDED_DIRECTORIES_JSON": '["/Media/Shows"]',
            "STRM_OUTPUT_ROOT": "/strm",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
        }
        outputs = ({"file_id": "q-1", "file_name": "测试剧.S01E01.mkv"},)
        targeted_result = TargetedStrmResult(1, (41,), StrmReconcileResult(created=1))
        with (
            patch.dict(os.environ, environment),
            patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress,
            patch(
                "app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm",
                return_value=targeted_result,
            ),
            patch("app.services.post_transfer_pipeline.refresh_emby_library_after_strm", return_value="刷新已提交") as refresh,
        ):
            get_settings.cache_clear()
            run_post_transfer_pipeline(
                12,
                provider="quark",
                title="测试剧",
                target_path="/Media/Shows/测试剧/Season 1",
                target_files=outputs,
                defer_library_notification=True,
            )

        refresh.assert_called_once_with("/strm")
        self.assertIn(
            (12, "library_notification", "running", "等待 Emby 入库 Webhook；连续剧集确认后合并通知"),
            [call.args for call in progress.call_args_list],
        )

    def test_openlist_workflow_distinguishes_batch_waiting_from_submitted_copy(self):
        environment = {
            "OPENLIST_ENABLED": "true",
            "OPENLIST_AUTO_SYNC": "true",
            "QUARK_STRM_ENABLED": "false",
        }
        cases = (
            ("等待同批网盘转存全部结束后核对 115 缺失文件", "pending"),
            ("OpenList 已提交后台复制任务 #77", "running"),
        )
        for job_id, (message, expected) in enumerate(cases, start=12):
            with self.subTest(message=message), patch.dict(os.environ, environment), patch(
                "app.services.post_transfer_pipeline.update_media_workflow_step"
            ) as progress:
                get_settings.cache_clear()
                run_post_transfer_pipeline(job_id, provider="quark", title="同步状态测试", openlist_message=message)
            openlist_steps = [call.args for call in progress.call_args_list if call.args[1] == "openlist_sync"]
            self.assertEqual(expected, openlist_steps[-1][2])

    def test_non_mutating_or_conflicted_reconcile_never_refreshes_emby(self):
        environment = {
            "QUARK_STRM_ENABLED": "true",
            "QUARK_ROOT_PATH": "/Media",
            "QUARK_STRM_SOURCE_ROOT": "/Media",
            "QUARK_STRM_INCLUDED_DIRECTORIES_JSON": '["/Media/Movies"]',
            "STRM_OUTPUT_ROOT": "/strm",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
        }
        outputs = ({"file_id": "q-1", "file_name": "测试影片.mkv"},)
        cases = (
            (StrmReconcileResult(conflicts=1), "failed", "路径冲突"),
            (StrmReconcileResult(filtered=1), "skipped", "目标均被过滤"),
            (StrmReconcileResult(), "skipped", "未产生可生成的 STRM 结果"),
            (StrmReconcileResult(unchanged=1), "done", "保持 1"),
        )
        for offset, (reconcile, expected_status, expected_message) in enumerate(cases, start=20):
            with self.subTest(reconcile=reconcile):
                targeted_result = TargetedStrmResult(1, (41,), reconcile)
                with patch.dict(os.environ, environment, clear=False), patch(
                    "app.services.post_transfer_pipeline.update_media_workflow_step"
                ) as progress, patch(
                    "app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm",
                    return_value=targeted_result,
                ), patch(
                    "app.services.post_transfer_pipeline.refresh_emby_library_after_strm"
                ) as refresh:
                    get_settings.cache_clear()
                    run_post_transfer_pipeline(
                        offset,
                        provider="quark",
                        title="测试影片",
                        target_path="/Media/Movies/测试影片",
                        target_files=outputs,
                    )
                refresh.assert_not_called()
                strm_steps = [call.args for call in progress.call_args_list if call.args[1] == "strm_generate"]
                emby_steps = [call.args for call in progress.call_args_list if call.args[1] == "emby_refresh"]
                self.assertEqual(expected_status, strm_steps[-1][2])
                self.assertIn(expected_message, strm_steps[-1][3])
                self.assertEqual("skipped", emby_steps[-1][2])

    def test_strm_or_emby_failure_returns_false_and_settles_notification(self):
        environment = {
            "QUARK_STRM_ENABLED": "true",
            "QUARK_ROOT_PATH": "/Media",
            "QUARK_STRM_SOURCE_ROOT": "/Media",
            "QUARK_STRM_INCLUDED_DIRECTORIES_JSON": '["/Media/Shows"]',
            "STRM_OUTPUT_ROOT": "/strm",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
        }
        outputs = ({"file_id": "q-1", "file_name": "测试剧.S01E01.mkv"},)
        targeted_result = TargetedStrmResult(1, (41,), StrmReconcileResult(created=1))
        with (
            patch.dict(os.environ, environment),
            patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress,
            patch(
                "app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm",
                return_value=targeted_result,
            ),
            patch("app.services.post_transfer_pipeline.refresh_emby_library_after_strm", side_effect=RuntimeError("offline")),
        ):
            get_settings.cache_clear()
            result = run_post_transfer_pipeline(
                30,
                provider="quark",
                title="测试剧",
                target_path="/Media/Shows/测试剧/Season 1",
                target_files=outputs,
            )

        self.assertFalse(result)
        self.assertIn(
            (30, "library_notification", "skipped", "Emby 入库未完成，未发送入库通知"),
            [call.args for call in progress.call_args_list],
        )

    def test_scheduled_organizer_claims_its_scope_without_generating_source_strm(self):
        environment = {
            "P115_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "true",
            "P115_CLOUD_DOWNLOAD_ORGANIZER_SCOPE_MODE": "all",
            "P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON": "[]",
            "P115_CLOUD_DOWNLOAD_PATH": "/downloads",
            "P115_ROOT_PATH": "/Media",
            "CLOUD_DOWNLOAD_ORGANIZER_TRIGGERS_JSON": '["scheduled"]',
        }
        with patch.dict(os.environ, environment, clear=False), patch(
            "app.services.cloud_download_organizer.run_targeted_cloud_download_organizer"
        ) as targeted:
            get_settings.cache_clear()
            handled, message = try_targeted_cloud_download_organization(
                provider="p115",
                target_path="/downloads/Movies/Film.2026",
                target_files=({"file_name": "Film.2026.mkv"},),
            )

        self.assertTrue(handled)
        self.assertIn("定时云下载整理", message)
        targeted.assert_not_called()

    def test_confirmed_interaction_staging_never_falls_back_to_raw_strm(self):
        save_path = "/downloads/Movies/Film (2026)"
        outputs = ({"file_id": "q-1", "file_name": "Film.2026.mkv", "path": save_path},)
        with (
            patch.dict(
                os.environ,
                {
                    "QUARK_CLOUD_DOWNLOAD_PATH": "/downloads",
                    "QUARK_ROOT_PATH": "/Media",
                    "QUARK_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false",
                },
                clear=False,
            ),
            patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress,
            patch("app.services.post_transfer_pipeline.run_post_transfer_pipeline") as raw_pipeline,
        ):
            get_settings.cache_clear()
            handled = run_confirmed_native_transfer_post_processing(
                31,
                provider="quark",
                save_path=save_path,
                outputs=outputs,
                title="Film",
                media_year="2026",
                cloud_download_child="Movies",
            )

        self.assertTrue(handled)
        raw_pipeline.assert_not_called()
        self.assertIn(
            (31, "strm_generate", "skipped", "云下载原始文件等待整理，不生成 STRM"),
            [call.args for call in progress.call_args_list],
        )


if __name__ == "__main__":
    unittest.main()
