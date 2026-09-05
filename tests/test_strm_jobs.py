import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import ANY, patch

from app.core.config import Settings, get_settings
from app.clients.p115 import P115Client, P115Error, P115File
from app.db.database import db, init_db
from app.services.strm_jobs import create_strm_job, run_strm_job
from app.services.strm_reconciler import StrmReconcileResult
from app.services.cloud_inventory import InventoryResult


class StrmJobTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db")})
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_incremental_job_is_persisted_and_completes_with_reconcile_summary(self):
        job_id = create_strm_job(provider="p115", mode="incremental", root_path="/Movies", output_root="D:/strm", playback_base_url="http://127.0.0.1:8000")
        scan = InventoryResult(provider="p115", root_path="/Movies", directories_scanned=1, files_indexed=3, truncated=False)
        with patch("app.services.strm_jobs.scan_p115_inventory", return_value=scan) as scan_mock, patch("app.services.strm_jobs.reconcile_strm", return_value=StrmReconcileResult(created=2)):
            run_strm_job(job_id, provider="p115", mode="incremental", root_path="/Movies", output_root="D:/strm", playback_base_url="http://127.0.0.1:8000")
        scan_mock.assert_called_once_with("/Movies", max_files=None, mark_missing=False, include_directories=None, on_progress=ANY)
        with db() as conn:
            row = dict(conn.execute("SELECT provider,status,stage,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual("strm", row["provider"])
        self.assertEqual("done", row["status"])
        self.assertEqual("strm_completed", row["stage"])
        self.assertIn("新增 2", row["message"])
        self.assertNotIn("刮削", row["message"])

    def test_quark_full_job_uses_native_inventory_and_marks_missing(self):
        job_id = create_strm_job(provider="quark", mode="full", root_path="/TV", output_root="D:/strm")
        scan = InventoryResult(provider="quark", root_path="/TV", directories_scanned=2, files_indexed=5, truncated=False, eligible_files_indexed=5)
        with patch("app.services.strm_jobs.scan_quark_inventory", return_value=scan) as scan_mock, patch("app.services.strm_jobs.reconcile_strm", return_value=StrmReconcileResult(unchanged=5)) as reconcile_mock:
            run_strm_job(job_id, provider="quark", mode="full", root_path="/TV", output_root="D:/strm")
        scan_mock.assert_called_once_with("/TV", max_files=None, mark_missing=True, include_directories=None, on_progress=ANY)
        reconcile_mock.assert_called_once_with(output_root="D:/strm", playback_base_url=None, provider="quark", source_root_path="/TV", include_directories=None, allow_removal=True)
        with db() as conn:
            row = dict(conn.execute("SELECT status,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual("done", row["status"])
        self.assertIn("全量扫描 5 个文件", row["message"])

    def test_115_bulk_405_fallback_generates_selected_subtree_strm(self):
        output = str(Path(self.tempdir.name) / "strm")
        client = P115Client(Settings(_env_file=None, p115_cookie="UID=1_A1_1; CID=fake; SEID=fake"))
        job_id = create_strm_job(provider="p115", mode="incremental", root_path="/Media", output_root=output)
        error = urllib.error.HTTPError("https://proapi.115.com", 405, "Method Not Allowed", {}, None)
        with patch("app.services.cloud_inventory.P115Client", return_value=client), patch.object(client, "directory_id", return_value="root"), patch.object(client, "list_directory", return_value=(P115File("tv", "root", "TV", "", is_dir=True), P115File("other", "root", "Other", "", is_dir=True))), patch("p115client.P115Client"), patch("p115client.tool.iter_files_with_path_skim", side_effect=error), patch.object(client, "list_directory_complete", return_value=(P115File("episode", "tv", "Episode.mkv", "", 100),)) as listing, patch("app.services.strm_jobs.refresh_emby_library_after_strm", return_value=""):
            result = run_strm_job(job_id, provider="p115", mode="incremental", root_path="/Media", output_root=output, playback_base_url="http://127.0.0.1:8000", include_directories=["/Media/TV"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(1, result["created"])
        listing.assert_called_once_with("tv")
        generated = list(Path(output).rglob("*.strm"))
        self.assertEqual(["TV/Episode.strm"], [path.relative_to(output).as_posix() for path in generated])
        self.assertIn("http://127.0.0.1:8000/", generated[0].read_text())

    def test_115_405_failed_fallback_never_reconciles_or_marks_missing(self):
        output = str(Path(self.tempdir.name) / "strm")
        client = P115Client(Settings(_env_file=None, p115_cookie="UID=1_A1_1; CID=fake; SEID=fake"))
        job_id = create_strm_job(provider="p115", mode="full", root_path="/Media", output_root=output)
        error = urllib.error.HTTPError("https://proapi.115.com", 405, "Method Not Allowed", {}, None)
        with patch("app.services.cloud_inventory.P115Client", return_value=client), patch.object(client, "directory_id", return_value="root"), patch("p115client.P115Client"), patch("p115client.tool.iter_files_with_path_skim", side_effect=error), patch.object(client, "list_directory_complete", side_effect=P115Error("分页不完整")), patch("app.services.cloud_inventory.mark_missing_assets_unavailable") as missing, patch("app.services.strm_jobs.reconcile_strm") as reconcile:
            result = run_strm_job(job_id, provider="p115", mode="full", root_path="/Media", output_root=output)
        self.assertFalse(result["ok"])
        self.assertIn("HTTP 405", result["message"])
        missing.assert_not_called()
        reconcile.assert_not_called()

    def test_failure_records_the_exact_stage_and_missing_path(self):
        job_id = create_strm_job(provider="p115", mode="full", root_path="/测试/MIRC测试", output_root="/strm/MIRC测试")
        with patch("app.services.strm_jobs.scan_p115_inventory", side_effect=FileNotFoundError(2, "missing", "/测试/MIRC测试")):
            run_strm_job(job_id, provider="p115", mode="full", root_path="/测试/MIRC测试", output_root="/strm/MIRC测试")

        with db() as conn:
            row = dict(conn.execute("SELECT status,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual("failed", row["status"])
        self.assertIn("读取115来源目录 /测试/MIRC测试", row["message"])
        self.assertIn("/测试/MIRC测试", row["message"])

    def test_progress_reports_the_current_directory_without_individual_file_noise(self):
        job_id = create_strm_job(provider="p115", mode="full", root_path="/媒体库", output_root="/strm")
        scan = InventoryResult(provider="p115", root_path="/媒体库", directories_scanned=25, files_indexed=10, truncated=False)

        with patch("app.services.strm_jobs.scan_p115_inventory", side_effect=lambda *args, **kwargs: (kwargs["on_progress"](type("Progress", (), {"root_path": "/媒体库", "relative_dir": "电视剧", "directories_scanned": 25, "files_indexed": 10})()), scan)[1]), patch("app.services.strm_jobs.reconcile_strm", return_value=StrmReconcileResult()):
            run_strm_job(job_id, provider="p115", mode="full", root_path="/媒体库", output_root="/strm")

        with db() as conn:
            row = dict(conn.execute("SELECT message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertIn("全量扫描 10 个文件", row["message"])

    def test_empty_full_inventory_forces_non_destructive_reconcile(self):
        job_id = create_strm_job(provider="p115", mode="full", root_path="/媒体库", output_root="/strm")
        scan = InventoryResult(provider="p115", root_path="/媒体库", directories_scanned=1, files_indexed=0, truncated=False)
        with patch("app.services.strm_jobs.scan_p115_inventory", return_value=scan), patch(
            "app.services.strm_jobs.reconcile_strm", return_value=StrmReconcileResult(unchanged=8)
        ) as reconcile:
            run_strm_job(job_id, provider="p115", mode="full", root_path="/媒体库", output_root="/strm")

        self.assertFalse(reconcile.call_args.kwargs["allow_removal"])
        with db() as conn:
            row = dict(conn.execute("SELECT status,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual("done", row["status"])
        self.assertIn("远端返回空清单", row["message"])
        self.assertIn("跳过缺失项清理", row["message"])

    def test_sidecar_only_full_inventory_forces_non_destructive_reconcile(self):
        job_id = create_strm_job(provider="p115", mode="full", root_path="/媒体库", output_root="/strm")
        scan = InventoryResult(
            provider="p115", root_path="/媒体库", directories_scanned=3,
            files_indexed=140, truncated=False, eligible_files_indexed=0,
        )
        with patch("app.services.strm_jobs.scan_p115_inventory", return_value=scan), patch(
            "app.services.strm_jobs.reconcile_strm", return_value=StrmReconcileResult(unchanged=8)
        ) as reconcile:
            run_strm_job(job_id, provider="p115", mode="full", root_path="/媒体库", output_root="/strm")

        self.assertFalse(reconcile.call_args.kwargs["allow_removal"])
        with db() as conn:
            row = dict(conn.execute("SELECT status,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual("done", row["status"])
        self.assertIn("未发现任何视频文件", row["message"])
