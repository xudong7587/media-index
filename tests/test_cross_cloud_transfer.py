import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.cloud import list_p115_directory
from app.clients.p115 import P115Error, P115File, P115UploadInitialization
from app.clients.quark import QuarkFile
from app.core.config import get_settings
from app.db.database import init_db
from app.services.cross_cloud_transfer import (
    CrossCloudTransferRequest,
    create_cross_cloud_transfer,
    delete_cross_cloud_transfer,
    get_cross_cloud_transfer,
    recover_interrupted_cross_cloud_transfers,
    run_cross_cloud_transfer,
    transfer_events,
)
from app.services.media_assets import list_assets


class FakeQuark:
    def __init__(self, content=b"quark-video-bytes", source_sha1=""):
        self.content = content
        self.source_sha1 = source_sha1
        self.range_calls = []

    def configured(self):
        return True

    def file_in_directory(self, parent_id, file_id):
        if (parent_id, file_id) != ("source-folder", "source-file"):
            raise AssertionError("unexpected source lookup")
        return QuarkFile("source-file", "source-folder", "Episode.mkv", len(self.content), False, self.source_sha1)

    def read_download_range(self, file_id, start, end, *, max_bytes):
        self.range_calls.append((file_id, start, end, max_bytes))
        if end - start + 1 > max_bytes:
            raise AssertionError("read exceeded memory bound")
        return self.content[start : end + 1]


class FakeP115:
    def __init__(self, *, rapid_hit):
        self.rapid_hit = rapid_hit
        self.ensure_calls = []
        self.uploaded = b""

    def configured(self):
        return True

    def ensure_directory(self, path):
        self.ensure_calls.append(path)
        return "target-folder"

    def initialize_stream_upload(self, filename, filesha1, filesize, parent_id, read_sign_check):
        self.initialization = (filename, filesha1, filesize, parent_id, read_sign_check)
        return P115UploadInitialization(reused=self.rapid_hit, upload_id="remote-session", status=2 if self.rapid_hit else 1)

    def upload_stream(self, stream, filename, filesha1, filesize, parent_id, *, part_size):
        self.uploaded = stream.read() + stream.read()
        self.upload_args = (filename, filesha1, filesize, parent_id, part_size)
        return {"state": True, "data": {"file_id": "target-file"}}

    def list_directory(self, parent_id):
        self.listed_parent = parent_id
        return (P115File("target-file", parent_id, "Renamed.mkv", "/Renamed.mkv", size=17),)


class CrossCloudTransferTests(unittest.TestCase):
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

    def _create(self, quark, name="Renamed.mkv"):
        return create_cross_cloud_transfer(
            CrossCloudTransferRequest("source-folder", "source-file", "/Media/TV", name), quark_client=quark
        )

    def test_hash_reuse_after_full_source_read_is_not_reported_as_true_rapid_upload(self):
        quark = FakeQuark()
        p115 = FakeP115(rapid_hit=True)
        created = self._create(quark)

        result = run_cross_cloud_transfer(created["id"], quark_client=quark, p115_client=p115)

        self.assertEqual("completed", result["state"])
        self.assertEqual("hit", result["rapid_probe_result"])
        self.assertEqual("stream_hash_then_probe", result["strategy"])
        self.assertIn("不计为真正秒传", result["stage_message"])
        self.assertEqual("target-file", result["target_file_id"])
        self.assertEqual([( "p115", "target-file", "ready")], [(item["provider"], item["file_id"], item["status"]) for item in list_assets()])
        self.assertEqual(b"", p115.uploaded)
        self.assertEqual(["/Media/TV"], p115.ensure_calls)
        self.assertTrue(quark.range_calls)
        self.assertTrue(all(end - start + 1 <= limit for _, start, end, limit in quark.range_calls))
        self.assertEqual(["created", "fingerprinting", "fingerprinting", "upload_initializing", "rapid_probe", "target_confirming", "completed"], [event["state"] for event in transfer_events(created["id"])])

    def test_provider_sha1_skips_full_source_scan_before_rapid_probe(self):
        source_sha1 = "A" * 40
        quark = FakeQuark(source_sha1=source_sha1)
        p115 = FakeP115(rapid_hit=True)
        created = self._create(quark)

        result = run_cross_cloud_transfer(created["id"], quark_client=quark, p115_client=p115)

        self.assertEqual("completed", result["state"])
        self.assertEqual(source_sha1, result["source_sha1"])
        self.assertEqual("provider_sha1_rapid_then_stream", result["strategy"])
        self.assertIn("真正 SHA1 秒传已命中", result["stage_message"])
        self.assertEqual([], quark.range_calls)

    def test_terminal_task_without_remote_residue_can_be_deleted(self):
        created = self._create(FakeQuark())

        delete_cross_cloud_transfer(created["id"])

        self.assertIsNone(get_cross_cloud_transfer(created["id"]))
        self.assertEqual([], transfer_events(created["id"]))

    def test_task_with_pending_remote_cleanup_cannot_be_deleted(self):
        created = self._create(FakeQuark())
        with __import__("app.db.database", fromlist=["db"]).db() as conn:
            conn.execute("UPDATE cross_cloud_transfers SET state='failed_recoverable',cleanup_state='remote_cleanup_pending' WHERE id=?", (created["id"],))

        with self.assertRaisesRegex(Exception, "远端状态"):
            delete_cross_cloud_transfer(created["id"])

    def test_rapid_miss_uses_seekable_bounded_stream_and_records_progress(self):
        content = b"1234567890abcdef!"
        quark = FakeQuark(content)
        p115 = FakeP115(rapid_hit=False)
        created = self._create(quark)

        result = run_cross_cloud_transfer(created["id"], quark_client=quark, p115_client=p115)

        self.assertEqual("completed", result["state"])
        self.assertEqual("miss", result["rapid_probe_result"])
        self.assertEqual(content, p115.uploaded)
        self.assertEqual(len(content), result["fingerprinted_bytes"])
        self.assertEqual(len(content), result["uploaded_bytes"])
        self.assertEqual(16 * 1024 * 1024, p115.upload_args[-1])

    def test_stream_failure_after_115_initialization_requires_remote_review(self):
        quark = FakeQuark()
        p115 = FakeP115(rapid_hit=False)
        p115.upload_stream = lambda *_args, **_kwargs: (_ for _ in ()).throw(P115Error("115 流式上传失败"))
        created = self._create(quark)

        result = run_cross_cloud_transfer(created["id"], quark_client=quark, p115_client=p115)

        self.assertEqual("failed_recoverable", result["state"])
        self.assertEqual("remote_cleanup_pending", result["cleanup_state"])

    def test_live_p115_directory_endpoint_returns_native_entries(self):
        client = FakeP115(rapid_hit=False)
        client.list_directory = lambda parent_id: (
            P115File("folder", parent_id, "TV", "/TV", is_dir=True),
            P115File("file", parent_id, "Episode.mkv", "/Episode.mkv", size=42),
        )

        with patch("app.api.cloud.P115Client", return_value=client):
            result = list_p115_directory("0")

        self.assertEqual("0", result["parent_id"])
        self.assertEqual([("TV", True), ("Episode.mkv", False)], [(item["name"], item["is_dir"]) for item in result["entries"]])

    def test_live_p115_directory_endpoint_preserves_rescan_requirement(self):
        client = FakeP115(rapid_hit=False)
        client.list_directory = lambda _parent_id: (_ for _ in ()).throw(
            P115Error("115 Open 授权已失效，请重新扫码授权文件接口（错误码 40140125）")
        )

        with patch("app.api.cloud.P115Client", return_value=client):
            with self.assertRaises(HTTPException) as raised:
                list_p115_directory("0")

        self.assertEqual(409, raised.exception.status_code)
        self.assertIn("重新扫码", raised.exception.detail)

    def test_completed_transfer_stays_completed_when_automatic_strm_write_fails(self):
        quark = FakeQuark()
        p115 = FakeP115(rapid_hit=True)
        created = self._create(quark)

        with patch.dict(os.environ, {"P115_STRM_ENABLED": "true"}):
            get_settings.cache_clear()
            with patch("app.services.strm_reconciler.reconcile_strm", side_effect=OSError("disk full")):
                result = run_cross_cloud_transfer(created["id"], quark_client=quark, p115_client=p115)

        self.assertEqual("completed", result["state"])
        self.assertIn("STRM 待处理", result["stage_message"])
        self.assertNotIn("disk full", result["stage_message"])

    def test_completed_transfer_registers_path_relative_to_the_configured_115_root(self):
        quark = FakeQuark()
        p115 = FakeP115(rapid_hit=True)
        created = self._create(quark)

        with patch.dict(os.environ, {"P115_ROOT_PATH": "/Media"}):
            get_settings.cache_clear()
            result = run_cross_cloud_transfer(created["id"], quark_client=quark, p115_client=p115)

        asset = next(item for item in list_assets() if item["file_id"] == result["target_file_id"])
        self.assertEqual("TV/Renamed.mkv", asset["relative_path"])

    def test_restart_marks_active_streaming_attempt_recoverable_instead_of_replaying_it(self):
        quark = FakeQuark()
        created = self._create(quark)
        with __import__("app.db.database", fromlist=["db"]).db() as conn:
            conn.execute("UPDATE cross_cloud_transfers SET state='streaming',remote_upload_id='session' WHERE id=?", (created["id"],))

        self.assertEqual(1, recover_interrupted_cross_cloud_transfers())
        record = get_cross_cloud_transfer(created["id"])
        self.assertEqual("failed_recoverable", record["state"])
        self.assertEqual("remote_cleanup_pending", record["cleanup_state"])


if __name__ == "__main__":
    unittest.main()
