import os
import unittest
from unittest.mock import patch

from app.core.config import get_settings
from app.services.post_transfer_pipeline import run_post_transfer_pipeline
from app.services.strm_reconciler import StrmReconcileResult
from app.services.targeted_strm import TargetedStrmResult


class PostTransferPipelineTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

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
        with patch.dict(os.environ, environment), patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress, patch("app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm", return_value=targeted_result) as targeted, patch("app.services.post_transfer_pipeline.refresh_emby_library_after_strm", return_value="刷新已提交") as refresh, patch("app.services.post_transfer_pipeline._notification_group", return_value="group"), patch("app.services.post_transfer_pipeline.add_notification", return_value=True) as notify:
            get_settings.cache_clear()
            run_post_transfer_pipeline(9, provider="quark", title="测试影片", poster_url="https://image.test/poster.jpg", target_path="/Media/Movies/测试影片 (2026)", target_files=outputs)
        targeted.assert_called_once()
        self.assertEqual(outputs, targeted.call_args.kwargs["target_files"])
        self.assertEqual("/Media/Movies/测试影片 (2026)", targeted.call_args.kwargs["target_path"])
        refresh.assert_called_once_with("/strm")
        notify.assert_called_once()
        self.assertIn((9, "library_notification", "done", "入库通知已聚合，等待 Emby 入库后发送"), [call.args for call in progress.call_args_list])

    def test_legacy_qas_does_not_impersonate_native_quark_strm(self):
        with patch.dict(os.environ, {"QUARK_STRM_ENABLED": "true", "NOTIFICATION_EXTERNAL_ENABLED": "false"}), patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress, patch("app.services.post_transfer_pipeline.index_and_reconcile_targeted_strm") as targeted, patch("app.services.post_transfer_pipeline.add_notification") as notify:
            get_settings.cache_clear()
            run_post_transfer_pipeline(10, provider="qas", title="旧任务")
        targeted.assert_not_called()
        notify.assert_not_called()
        self.assertIn((10, "strm_generate", "skipped", "当前网盘未启用自动 STRM 生成"), [call.args for call in progress.call_args_list])


if __name__ == "__main__":
    unittest.main()
