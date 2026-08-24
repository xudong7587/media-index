import os
import unittest
from unittest.mock import patch

from app.core.config import get_settings
from app.services.cloud_inventory import InventoryResult
from app.services.post_transfer_pipeline import run_post_transfer_pipeline
from app.services.strm_reconciler import StrmReconcileResult


class PostTransferPipelineTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def test_native_quark_runs_incremental_metadata_scan_and_emby_refresh(self):
        environment = {
            "QUARK_STRM_ENABLED": "true",
            "QUARK_ROOT_PATH": "/Media",
            "QUARK_STRM_SOURCE_ROOT": "/Media",
            "STRM_OUTPUT_ROOT": "/strm",
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
        }
        scan = InventoryResult(provider="quark", root_path="/Media", directories_scanned=2, files_indexed=4, truncated=False)
        with patch.dict(os.environ, environment), patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress, patch("app.services.post_transfer_pipeline.scan_quark_inventory", return_value=scan) as scan_mock, patch("app.services.post_transfer_pipeline.reconcile_strm", return_value=StrmReconcileResult(created=1)) as reconcile, patch("app.services.post_transfer_pipeline.refresh_emby_library_after_strm", return_value="刷新已提交") as refresh, patch("app.services.post_transfer_pipeline.add_notification", return_value=True) as notify:
            get_settings.cache_clear()
            run_post_transfer_pipeline(9, provider="quark", title="测试影片", poster_url="https://image.test/poster.jpg")
        scan_mock.assert_called_once_with("/Media", mark_missing=False)
        reconcile.assert_called_once_with(output_root="/strm", provider="quark", source_root_path="/Media")
        refresh.assert_called_once_with("/strm")
        notify.assert_called_once()
        self.assertIn((9, "library_notification", "done", "入库通知已聚合，等待 Emby 入库后发送"), [call.args for call in progress.call_args_list])

    def test_legacy_qas_does_not_impersonate_native_quark_strm(self):
        with patch.dict(os.environ, {"QUARK_STRM_ENABLED": "true", "NOTIFICATION_EXTERNAL_ENABLED": "false"}), patch("app.services.post_transfer_pipeline.update_media_workflow_step") as progress, patch("app.services.post_transfer_pipeline.scan_quark_inventory") as scan_mock, patch("app.services.post_transfer_pipeline.add_notification") as notify:
            get_settings.cache_clear()
            run_post_transfer_pipeline(10, provider="qas", title="旧任务")
        scan_mock.assert_not_called()
        notify.assert_not_called()
        self.assertIn((10, "strm_generate", "skipped", "当前网盘未启用自动 STRM 生成"), [call.args for call in progress.call_args_list])


if __name__ == "__main__":
    unittest.main()
