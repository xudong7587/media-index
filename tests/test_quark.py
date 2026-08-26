import json
import os
import unittest
import urllib.parse
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.api.config import ConfigUpdate, QuarkQrPollRequest, QuarkShareInspectionRequest, inspect_quark_share, poll_quark_qr_login, update_config
from app.clients.quark import QuarkClient, QuarkError, QuarkQrLogin, QuarkQrPoll, QuarkShareFile, QuarkShareRef, QuarkShareSnapshot, normalize_quark_cookie, valid_quark_cookie
from app.services.quark_login import QuarkLoginService


class FakeResponse:
    def __init__(self, payload=None, *, cookies=(), status=200):
        self.payload = payload
        self.status = status
        self.headers = Message()
        for cookie in cookies:
            self.headers.add_header("Set-Cookie", cookie)

    def read(self, _limit=-1):
        if isinstance(self.payload, bytes):
            return self.payload if _limit < 0 else self.payload[:_limit]
        return json.dumps(self.payload).encode("utf-8") if self.payload is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def quark_settings(**overrides):
    values = {
        "quark_cookie": "__puus=abc; __pus=def",
        "quark_request_timeout_seconds": 1,
        "proxy_url": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class QuarkClientTests(unittest.TestCase):
    def test_rejects_newline_cookie_before_network_access(self):
        client = QuarkClient(quark_settings(quark_cookie="__puus=abc\nInjected=value"))
        with patch.object(client._opener, "open") as request:
            with self.assertRaisesRegex(QuarkError, "有效的夸克 Cookie"):
                client.list_root()
        request.assert_not_called()

    def test_cookie_validation_rejects_empty_and_header_injection(self):
        self.assertFalse(valid_quark_cookie(""))
        self.assertFalse(valid_quark_cookie("name=value\r\nInjected=true"))
        self.assertTrue(valid_quark_cookie("name=value"))

    def test_cookie_normalizer_accepts_copied_request_header(self):
        self.assertEqual("__uid=123; __puus=abc", normalize_quark_cookie("Cookie: __uid=123; __puus=abc"))

    def test_read_only_account_and_root_listing_send_cookie_only_to_trusted_origins(self):
        client = QuarkClient(quark_settings())
        responses = [
            FakeResponse({"data": {"uid": "123", "nickname": "Sunny"}}),
            FakeResponse({"data": {"list": [{"fid": "d1", "file_name": "影视", "dir": True}, {"fid": "f1", "file_name": "片源.mkv", "size": "42"}]}}),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request:
            account = client.account()
            root = client.list_root()
        self.assertEqual(("123", "Sunny"), (account.user_id, account.nickname))
        self.assertEqual(["影视", "片源.mkv"], [item.name for item in root])
        self.assertTrue(root[0].is_dir)
        self.assertEqual(42, root[1].size)
        for call in request.call_args_list:
            outbound = call.args[0]
            self.assertTrue(outbound.full_url.startswith((client.PAN_ORIGIN, client.DRIVE_ORIGIN)))
            self.assertEqual("__puus=abc; __pus=def", outbound.get_header("Cookie"))
        self.assertIn("platform=pc", request.call_args_list[0].args[0].full_url)
        self.assertIn("application/json, text/plain, */*", request.call_args_list[0].args[0].get_header("Accept"))

    def test_directory_listing_reads_every_page_before_returning_complete_inventory(self):
        client = QuarkClient(quark_settings())
        first_page = [
            {"fid": f"file-{index}", "file_name": f"Episode {index}.mkv", "size": index}
            for index in range(200)
        ]
        responses = [
            FakeResponse({"status": 200, "code": 0, "metadata": {"_total": 201}, "data": {"list": first_page}}),
            FakeResponse({"status": 200, "code": 0, "metadata": {"_total": 201}, "data": {"list": [
                {"fid": "file-200", "file_name": "Episode 200.mkv", "size": 200},
            ]}}),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request:
            items = client.list_directory_complete("folder")

        self.assertEqual(201, len(items))
        self.assertEqual("file-200", items[-1].file_id)
        pages = [
            urllib.parse.parse_qs(urllib.parse.urlsplit(call.args[0].full_url).query)["_page"]
            for call in request.call_args_list
        ]
        self.assertEqual([["1"], ["2"]], pages)

    def test_directory_listing_fails_closed_when_total_is_truncated(self):
        client = QuarkClient(quark_settings())
        responses = [
            FakeResponse({"status": 200, "code": 0, "metadata": {"_total": 2}, "data": {"list": [
                {"fid": "file-1", "file_name": "Episode 1.mkv"},
            ]}}),
            FakeResponse({"status": 200, "code": 0, "metadata": {"_total": 2}, "data": {"list": []}}),
        ]
        with patch.object(client._opener, "open", side_effect=responses):
            with self.assertRaisesRegex(QuarkError, "分页提前结束"):
                client.list_directory_complete("folder")

    def test_complete_directory_listing_requires_provider_total(self):
        client = QuarkClient(quark_settings())
        response = FakeResponse({
            "status": 200,
            "code": 0,
            "data": {"list": [{"fid": "file-1", "file_name": "Episode 1.mkv"}]},
        })
        with patch.object(client._opener, "open", return_value=response):
            with self.assertRaisesRegex(QuarkError, "未返回分页总数"):
                client.list_directory_complete("folder")

    def test_complete_directory_listing_rejects_duplicate_ids_within_page(self):
        client = QuarkClient(quark_settings())
        response = FakeResponse({
            "status": 200,
            "code": 0,
            "metadata": {"_total": 2},
            "data": {"list": [
                {"fid": "same", "file_name": "Episode 1.mkv"},
                {"fid": "same", "file_name": "Episode 2.mkv"},
            ]},
        })
        with patch.object(client._opener, "open", return_value=response):
            with self.assertRaisesRegex(QuarkError, "重复文件"):
                client.list_directory_complete("folder")

    def test_legacy_directory_listing_keeps_single_page_contract(self):
        client = QuarkClient(quark_settings())
        first_page = [
            {"fid": f"file-{index}", "file_name": f"Episode {index}.mkv", "size": index}
            for index in range(200)
        ]
        response = FakeResponse(
            {"status": 200, "code": 0, "metadata": {"_total": 201}, "data": {"list": first_page}}
        )
        with patch.object(client._opener, "open", return_value=response) as request:
            items = client.list_directory("folder")
        self.assertEqual(200, len(items))
        request.assert_called_once()

    def test_qr_login_does_not_send_cookie_and_never_returns_it_in_url(self):
        client = QuarkClient(quark_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"data": {"members": {"token": "upstream-token"}}}, cookies=("cas=seed; Path=/",))) as request:
            login = client.start_qr_login()
        outbound = request.call_args.args[0]
        self.assertEqual("upstream-token", login.token)
        self.assertIn("su.quark.cn", login.qr_url)
        self.assertIsNone(outbound.get_header("Cookie"))
        self.assertNotIn("__puus=abc", outbound.full_url)
        self.assertEqual("cas=seed", login.cookie)

    def test_scanned_qr_extracts_cookie_without_exposing_it_in_requests(self):
        client = QuarkClient(quark_settings())
        responses = [
            FakeResponse({"status": 2000000, "data": {"members": {"service_ticket": "ticket"}}}, cookies=("cas=next; Path=/",)),
            FakeResponse(None, cookies=("__puus=from-qr; Path=/; HttpOnly", "__pus=from-qr; Path=/")),
            FakeResponse(b"<html></html>", cookies=("__uid=123; Path=/",)),
            FakeResponse({"status": 200, "code": 0, "data": {"list": []}}, cookies=("__puus=rotated; Path=/",)),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request:
            result = client.poll_qr_login("upstream-token", "cas=seed")
        self.assertEqual("success", result.status)
        self.assertTrue(valid_quark_cookie(result.cookie))
        self.assertIn("__uid=123", result.cookie)
        self.assertIn("__puus=rotated", result.cookie)
        serialized = " ".join(call.args[0].full_url for call in request.call_args_list)
        self.assertNotIn(result.cookie, serialized)

    def test_undocumented_qr_status_keeps_session_waiting(self):
        client = QuarkClient(quark_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"status": 400039, "message": "pending"})):
            result = client.poll_qr_login("upstream-token")
        self.assertEqual("waiting", result.status)

    def test_account_accepts_qas_compatible_nickname_only_payload(self):
        client = QuarkClient(quark_settings(quark_cookie="__uid=123; __puus=abc"))
        with patch.object(client._opener, "open", return_value=FakeResponse({"success": True, "data": {"nickname": "Sunny"}})):
            account = client.account()
        self.assertEqual(("123", "Sunny"), (account.user_id, account.nickname))

    def test_share_inspection_reads_tree_without_saving_to_drive(self):
        client = QuarkClient(quark_settings())
        responses = [
            FakeResponse({"status": 200, "code": 0, "data": {"stoken": "share-token"}}),
            FakeResponse({"status": 200, "code": 0, "data": {"list": [
                {"fid": "folder", "file_name": "电影目录", "file_type": 0},
                {"fid": "video", "file_name": "电影.mkv", "file_type": 1, "size": "1024"},
            ]}}),
            FakeResponse({"status": 200, "code": 0, "data": {"list": [
                {"fid": "subtitle", "pdir_fid": "folder", "file_name": "电影.ass", "file_type": 1, "size": "10"},
            ]}}),
        ]
        share_url = "https://pan.quark.cn/s/share-code?pwd=1234#/list/share"
        with patch.object(client._opener, "open", side_effect=responses) as request:
            snapshot = client.inspect_share(share_url)
        self.assertEqual("电影目录", snapshot.title)
        self.assertEqual(["电影目录", "电影.mkv", "电影.ass"], [item.name for item in snapshot.files])
        self.assertTrue(snapshot.files[0].is_dir)
        self.assertEqual(1024, snapshot.files[1].size)
        self.assertEqual(3, request.call_count)
        for call in request.call_args_list:
            self.assertNotIn("1234", call.args[0].full_url)
            self.assertNotIn("__puus=abc", call.args[0].full_url)
        self.assertEqual("POST", request.call_args_list[0].args[0].method)
        self.assertIn(b'"pwd_id":"share-code"', request.call_args_list[0].args[0].data)

    def test_share_url_rejects_untrusted_hosts_before_network_access(self):
        client = QuarkClient(quark_settings())
        with patch.object(client._opener, "open") as request:
            with self.assertRaisesRegex(QuarkError, "只支持夸克分享链接"):
                client.inspect_share("https://example.test/s/share-code")
        request.assert_not_called()

    def test_write_commands_are_explicit_and_keep_share_credentials_out_of_urls(self):
        client = QuarkClient(quark_settings())
        snapshot = QuarkShareSnapshot(
            share=QuarkShareRef("share-code", "1234"),
            share_token="share-token",
            title="电影.mkv",
            files=(QuarkShareFile("file", "0", "电影.mkv", 42, share_fid_token="fid-token"),),
        )
        responses = [
            FakeResponse({"status": 200, "code": 0, "data": {"fid": "target-folder"}}),
            FakeResponse({"status": 200, "code": 0, "data": {"task_id": "save-task"}}),
            FakeResponse({"status": 200, "code": 0, "data": {}}),
            FakeResponse({"status": 200, "code": 0, "data": {"task_id": "move-task"}}),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request:
            folder_id = client.ensure_directory("/strm/movie/测试")
            task_id = client.save_share_files(snapshot, ["file"], folder_id)
            client.rename_file("file", "测试.2026.mkv")
            move_task = client.move_files(["file"], "final-folder")
        self.assertEqual(("target-folder", "save-task", "move-task"), (folder_id, task_id, move_task))
        self.assertEqual(["POST", "POST", "POST", "POST"], [call.args[0].method for call in request.call_args_list])
        self.assertIn("/file/move?", request.call_args_list[3].args[0].full_url)
        save_request = request.call_args_list[1].args[0]
        self.assertIn(b'"fid_token_list":["fid-token"]', save_request.data)
        self.assertNotIn("1234", save_request.full_url)
        self.assertNotIn("share-token", save_request.full_url)

    def test_copy_and_trash_wait_for_remote_tasks_and_keep_exact_ids(self):
        client = QuarkClient(quark_settings())
        responses = [
            FakeResponse({"status": 200, "code": 0, "data": {"task_id": "copy-task"}}),
            FakeResponse({"status": 200, "code": 0, "data": {"status": 1}}),
            FakeResponse({"status": 200, "code": 0, "data": {"status": 2}}),
            FakeResponse({"status": 200, "code": 0, "data": {"task_id": "trash-task"}}),
            FakeResponse({"status": 200, "code": 0, "data": {"status": "completed"}}),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request, patch("app.clients.quark.time.sleep"):
            copy_task = client.copy_files(["one", "two", "one"], "destination")
            trash_task = client.trash_files(["one", "two"])

        self.assertEqual(("copy-task", "trash-task"), (copy_task, trash_task))
        self.assertEqual(["POST", "GET", "GET", "POST", "GET"], [call.args[0].method for call in request.call_args_list])
        copy_body = json.loads(request.call_args_list[0].args[0].data)
        trash_body = json.loads(request.call_args_list[3].args[0].data)
        self.assertEqual({"action_type": 1, "to_pdir_fid": "destination", "filelist": ["one", "two"], "exclude_fids": []}, copy_body)
        self.assertEqual({"action_type": 2, "filelist": ["one", "two"], "exclude_fids": []}, trash_body)
        self.assertIn("/file/copy?", request.call_args_list[0].args[0].full_url)
        self.assertIn("/file/delete?", request.call_args_list[3].args[0].full_url)
        retry_indexes = [
            urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args_list[index].args[0].full_url).query)["retry_index"]
            for index in (1, 2, 4)
        ]
        self.assertEqual([["0"], ["1"], ["0"]], retry_indexes)

    def test_wait_task_accepts_synchronous_completion_and_fails_closed(self):
        client = QuarkClient(quark_settings())
        with patch.object(client._opener, "open") as request:
            self.assertEqual({}, client.wait_task(""))
        request.assert_not_called()

        with patch.object(client._opener, "open", return_value=FakeResponse({"status": 200, "code": 0, "data": {"status": "failed"}})):
            with self.assertRaisesRegex(QuarkError, "远程任务失败"):
                client.wait_task("failed-task")

        with patch.object(client._opener, "open", return_value=FakeResponse({"status": 200, "code": 0, "data": {"status": 1}})):
            with self.assertRaisesRegex(QuarkError, "等待超时"):
                client.wait_task("pending-task", timeout_seconds=0)

    def test_copy_and_trash_reject_mixed_invalid_ids_before_network_access(self):
        client = QuarkClient(quark_settings())
        with patch.object(client._opener, "open") as request:
            with self.assertRaisesRegex(QuarkError, "复制文件 ID 无效"):
                client.copy_files(["valid", "bad id"], "destination")
            with self.assertRaisesRegex(QuarkError, "回收站文件 ID 无效"):
                client.trash_files(["valid", "bad id"])
        request.assert_not_called()

    def test_download_range_sends_cookie_only_to_trusted_quark_cdn(self):
        client = QuarkClient(quark_settings())
        responses = [
            FakeResponse({"status": 200, "code": 0, "data": [{"file_download_url": "https://dl-pc.drive.quark.cn/file?signature=opaque"}]}),
            FakeResponse(b"test", status=206),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request:
            body = client.read_download_range("file", 0, 3)

        self.assertEqual(b"test", body)
        signed_link_request = request.call_args_list[1].args[0]
        self.assertEqual("bytes=0-3", signed_link_request.get_header("Range"))
        self.assertEqual("__puus=abc; __pus=def", signed_link_request.get_header("Cookie"))
        self.assertNotIn("__puus=abc", signed_link_request.full_url)
        self.assertTrue(request.call_args_list[0].args[0].full_url.startswith(client.API_ORIGIN))

    def test_download_range_uses_rotated_cookie_returned_with_signed_link(self):
        settings = quark_settings()
        client = QuarkClient(settings)
        responses = [
            FakeResponse(
                {"status": 200, "code": 0, "data": [{"download_url": "https://dl-pc.drive.quark.cn/file?signature=opaque"}]},
                cookies=("__puus=rotated; Path=/; HttpOnly",),
            ),
            FakeResponse(b"x", status=206),
        ]

        with patch.object(client._opener, "open", side_effect=responses) as request:
            self.assertEqual(b"x", client.read_download_range("file", 0, 0, max_bytes=1))

        signed_link_request = request.call_args_list[1].args[0]
        self.assertIn("__puus=rotated", signed_link_request.get_header("Cookie"))
        self.assertNotIn("__puus=abc", signed_link_request.get_header("Cookie"))
        self.assertIn("__puus=rotated", settings.quark_cookie)

    def test_download_link_rejects_non_quark_cdn_before_byte_request(self):
        client = QuarkClient(quark_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"status": 200, "code": 0, "data": [{"file_download_url": "https://example.test/file"}]})) as request:
            with self.assertRaisesRegex(QuarkError, "受信任的下载链接"):
                client.download_link("file")
        self.assertEqual(1, request.call_count)


class QuarkLoginServiceTests(unittest.TestCase):
    def test_terminal_qr_result_is_consumed_once(self):
        client = Mock()
        client.start_qr_login.return_value = QuarkQrLogin(token="token", qr_url="https://su.quark.cn/qr", cookie="cas=seed")
        client.poll_qr_login.return_value = QuarkQrPoll(status="success", cookie="name=value")
        service = QuarkLoginService(client)
        session = service.start()
        self.assertEqual("success", service.poll(session.session_id).status)
        self.assertEqual("expired", service.poll(session.session_id).status)


class QuarkConfigApiTests(unittest.TestCase):
    def test_manual_cookie_is_persisted_but_never_returned(self):
        cookie = "__puus=manual; __pus=manual"
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = update_config(ConfigUpdate(quark_cookie=cookie))
            saved = env_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn(f"QUARK_COOKIE={cookie}", saved)
        self.assertNotIn(cookie, json.dumps(result))

    def test_scanned_cookie_is_persisted_without_being_returned(self):
        cookie = "__puus=scanned; __pus=scanned"
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False),
                patch("app.api.config._quark_login.poll", return_value=QuarkQrPoll(status="success", cookie=cookie)),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = poll_quark_qr_login(QuarkQrPollRequest(session_id="a" * 32))
            saved = env_path.read_text(encoding="utf-8")
        self.assertEqual((True, "success"), (result["ok"], result["status"]))
        self.assertIn(f"QUARK_COOKIE={cookie}", saved)
        self.assertNotIn(cookie, json.dumps(result))

    def test_share_inspection_never_echoes_share_url_or_credential(self):
        settings = quark_settings()
        snapshot = QuarkShareSnapshot(
            share=QuarkShareRef("share-code", "1234"),
            share_token="share-token",
            title="测试资源",
            files=(
                QuarkShareFile(file_id="video", parent_id="0", name="测试.mkv", size=42),
                QuarkShareFile(file_id="folder", parent_id="0", name="字幕", is_dir=True),
            ),
        )
        share_url = "https://pan.quark.cn/s/share-code?pwd=1234"
        with (
            patch("app.api.config.get_settings", return_value=settings),
            patch.object(QuarkClient, "inspect_share", return_value=snapshot),
        ):
            result = inspect_quark_share(QuarkShareInspectionRequest(share_url=share_url))
        self.assertTrue(result["ok"])
        self.assertEqual((2, 1, 1), (result["file_count"], result["directory_count"], result["video_count"]))
        self.assertNotIn("share-code", json.dumps(result))
        self.assertNotIn("1234", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
