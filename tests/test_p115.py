import json
import os
import ssl
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.clients.p115 import (
    P115Client,
    P115Error,
    P115File,
    P115ShareRef,
    P115ShareSnapshot,
    _prepare_p115_sdk_cache_env,
)
from app.core.config import Settings, get_settings
from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget, RenamePair
from app.providers.base import ProviderCapability, TransferPlan
from app.providers.p115 import P115LocalTransferProvider, P115TransferProvider
from app.services.link_resolver import resolve_episode_source


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def p115_settings(**overrides) -> Settings:
    values = {
        "p115_cookie": "UID=1_A1_1; CID=abc; SEID=secret",
        "p115_root_path": "/MediaIndex",
        "p115_staging_path": "/MediaIndex/.staging",
        "p115_request_timeout_seconds": 1,
        "db_path": "unused.db",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class P115ClientTests(unittest.TestCase):
    def test_owned_directory_listing_fails_closed_on_truncated_page(self):
        client = P115Client(p115_settings())
        responses = [
            {"state": True, "data": {"data": [{"fid": "file-1", "n": "one.mkv"}], "count": 2}},
            {"state": True, "data": {"data": [], "count": 2}},
        ]
        with patch.object(client, "_request_json", side_effect=responses):
            with self.assertRaisesRegex(P115Error, "分页提前结束"):
                client.list_directory("folder")

    def test_owned_directory_listing_rejects_duplicate_ids_within_one_page(self):
        client = P115Client(p115_settings())
        response = {
            "state": True,
            "data": {
                "data": [
                    {"fid": "same", "n": "one.mkv"},
                    {"fid": "same", "n": "two.mkv"},
                ],
                "count": 2,
            },
        }
        with patch.object(client, "_request_json", return_value=response):
            with self.assertRaisesRegex(P115Error, "重复文件"):
                client.list_directory("folder")

    def test_complete_owned_directory_listing_requires_provider_count(self):
        client = P115Client(p115_settings())
        response = {
            "state": True,
            "data": {"data": [{"fid": "file-1", "n": "one.mkv"}]},
        }
        with patch.object(client, "_request_json", return_value=response):
            with self.assertRaisesRegex(P115Error, "未返回有效分页总数"):
                client.list_directory_complete("folder")
        with patch.object(client, "_request_json", return_value=response):
            self.assertEqual(1, len(client.list_directory("folder")))

    def test_initialize_stream_upload_uses_sdk_without_local_file(self):
        client = P115Client(p115_settings())
        read_sign_check = MagicMock(return_value=b"range-proof")

        class FakeUploadClient:
            def __init__(self, **_kwargs):
                pass

            def upload_file_init(self, filename, filesha1, filesize, *, pid, read_range_bytes_or_hash):
                self.args = (filename, filesha1, filesize, pid, read_range_bytes_or_hash)
                return {"status": 2, "reuse": True, "upload_id": "rapid-upload"}

        fake_sdk = FakeUploadClient()
        with patch("p115client.P115Client", return_value=fake_sdk):
            result = client.initialize_stream_upload(
                "episode.mkv",
                "A" * 40,
                123,
                "456",
                read_sign_check,
            )

        self.assertTrue(result.reused)
        self.assertEqual("rapid-upload", result.upload_id)
        self.assertEqual(("episode.mkv", "A" * 40, 123, "456", read_sign_check), fake_sdk.args)
        read_sign_check.assert_not_called()

    def test_initialize_stream_upload_rejects_invalid_sha1_before_sdk_access(self):
        client = P115Client(p115_settings())
        with patch("p115client.P115Client") as sdk:
            with self.assertRaisesRegex(P115Error, "初始化参数无效"):
                client.initialize_stream_upload("episode.mkv", "not-a-hash", 123, "456", lambda _value: b"")
        sdk.assert_not_called()

    def test_upload_stream_forwards_readable_memory_stream_without_path(self):
        client = P115Client(p115_settings())

        class MemoryStream:
            def read(self, _size=-1):
                return b""

        class FakeUploadClient:
            def __init__(self, **_kwargs):
                pass

            def upload_file(self, stream, *, pid, filename, filesha1, filesize, partsize):
                self.args = (stream, pid, filename, filesha1, filesize, partsize)
                return {"state": True, "data": {"file_id": "target-file"}}

        fake_sdk = FakeUploadClient()
        stream = MemoryStream()
        with patch("p115client.P115Client", return_value=fake_sdk):
            result = client.upload_stream(stream, "episode.mkv", "B" * 40, 456, "789")

        self.assertEqual("target-file", result["data"]["file_id"])
        self.assertEqual((stream, "789", "episode.mkv", "B" * 40, 456, 16 * 1024 * 1024), fake_sdk.args)

    def test_direct_download_link_returns_cookie_free_url_and_required_header_names_only(self):
        client = P115Client(p115_settings())

        class FakeDownloadClient:
            def __init__(self, **_kwargs):
                pass

            def download_url(self, file_id, *, user_agent, app):
                self.args = (file_id, user_agent, app)
                return SimpleNamespace(url="https://cdn.115.com/video.mkv?temporary=secret", headers={"User-Agent": "required-value"})

        fake_sdk = FakeDownloadClient()
        with patch("p115client.P115Client", return_value=fake_sdk):
            link = client.direct_download_link("file-1")

        self.assertEqual("https://cdn.115.com/video.mkv?temporary=secret", link.url)
        self.assertEqual(("user-agent",), link.required_headers)
        self.assertEqual(("file-1", P115Client.PLAYBACK_USER_AGENT, "os_windows"), fake_sdk.args)

    def test_fast_inventory_uses_cookie_skim_lists_without_directory_export(self):
        client = P115Client(p115_settings())
        fake_sdk = object()
        skimmed = [
            {"id": "file-1", "parent_id": "folder-1", "name": "Episode.mkv", "relpath": "Season 1/Episode.mkv", "size": 123, "pickcode": "pick-1"},
        ]
        with patch("p115client.P115Client", return_value=fake_sdk), patch("p115client.tool.iter_files_with_path_skim", return_value=iter(skimmed)) as skim:
            files = list(client.iter_fast_inventory_files("root", max_files=None))

        self.assertTrue(client.supports_fast_inventory())
        self.assertEqual([P115File("file-1", "folder-1", "Episode.mkv", "Season 1/Episode.mkv", 123, False, "pick-1")], files)
        self.assertEqual((fake_sdk,), skim.call_args.args)
        self.assertEqual({"cid": "root", "with_ancestors": False, "max_workers": 4, "max_files": 0, "app": "android"}, skim.call_args.kwargs)

    def test_fast_inventory_refuses_open_only_connection(self):
        client = P115Client(p115_settings(p115_cookie="", p115_auth_mode="open", p115_open_access_token="access", p115_open_refresh_token="refresh"))
        self.assertFalse(client.supports_fast_inventory())
        with self.assertRaisesRegex(P115Error, "需要有效 Cookie"):
            list(client.iter_fast_inventory_files("root"))

    def test_direct_download_link_rejects_non_https_response(self):
        client = P115Client(p115_settings())

        class FakeDownloadClient:
            def __init__(self, **_kwargs):
                pass

            def download_url(self, *_args, **_kwargs):
                return SimpleNamespace(url="http://untrusted.example/video.mkv", headers={})

        with patch("p115client.P115Client", FakeDownloadClient):
            with self.assertRaisesRegex(P115Error, "不安全"):
                client.direct_download_link("file-1")

    def test_trash_file_uses_exact_id_and_never_calls_recycle_bin_purge(self):
        client = P115Client(p115_settings())

        class FakeDeleteClient:
            def __init__(self, **_kwargs):
                pass

            def fs_delete(self, file_ids):
                self.file_ids = file_ids
                return {"state": True}

        fake_sdk = FakeDeleteClient()
        with patch("p115client.P115Client", return_value=fake_sdk):
            client.trash_file("only-this-file")
        self.assertEqual(["only-this-file"], fake_sdk.file_ids)

    def test_tls_eof_reports_network_handshake_failure(self):
        client = P115Client(p115_settings())
        failure = urllib.error.URLError(ssl.SSLEOFError(8, "unexpected EOF"))
        with patch.object(client._opener, "open", side_effect=failure):
            with self.assertRaisesRegex(P115Error, "HTTPS 握手被网络中断"):
                client.inspect_share("https://115.com/s/demo?password=pass")

    def test_open_only_credentials_cannot_execute_a_native_rename(self):
        client = P115Client(p115_settings(p115_cookie="", p115_auth_mode="open", p115_open_access_token="access", p115_open_refresh_token="refresh"))
        with patch.object(client, "_with_open_client") as open_request:
            with self.assertRaisesRegex(P115Error, "有效的 115 Cookie"):
                client.rename([("1", "one.mkv")])
        open_request.assert_not_called()

    def test_expired_share_error_has_actionable_message(self):
        client = P115Client(p115_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"state": False, "errno": 4100018})):
            with self.assertRaisesRegex(P115Error, "分享链接已过期.*4100018"):
                client.receive_share_files(P115ShareRef("share", "pass"), ["1"], "99")

    def test_already_received_share_error_has_actionable_message(self):
        client = P115Client(p115_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"state": False, "errno": 4200045})):
            with self.assertRaisesRegex(P115Error, "分享文件已接收过.*4200045"):
                client.receive_share_files(P115ShareRef("share", "pass"), ["1"], "99")

    def test_recursive_share_inspection_keeps_file_identity_and_sends_cookie(self):
        client = P115Client(p115_settings())
        responses = [
            FakeResponse(
                {
                    "state": True,
                    "data": {
                        "list": [
                            {"cid": "10", "pid": "0", "n": "S01", "fc": "0"},
                            {"fid": "1", "pid": "0", "n": "movie.mkv", "s": "100", "fc": "1"},
                        ],
                        "count": 2,
                    },
                }
            ),
            FakeResponse(
                {
                    "state": True,
                    "data": {
                        "list": [{"fid": "2", "pid": "10", "n": "show.S01E01.mkv", "s": "200", "fc": "1"}],
                        "count": 1,
                    },
                }
            ),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request:
            snapshot = client.inspect_share("https://115.com/s/share-code?password=abcd")
        self.assertEqual(["1", "2"], [item.file_id for item in snapshot.files])
        self.assertEqual(["/movie.mkv", "/S01/show.S01E01.mkv"], [item.path for item in snapshot.files])
        self.assertEqual("UID=1_A1_1; CID=abc; SEID=secret", request.call_args_list[0].args[0].get_header("Cookie"))
        first_query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args_list[0].args[0].full_url).query)
        self.assertEqual(["abcd"], first_query["receive_code"])

    def test_valid_cookie_can_inspect_share_when_legacy_open_tokens_remain(self):
        client = P115Client(
            p115_settings(
                p115_auth_mode="open",
                p115_open_access_token="legacy-access",
                p115_open_refresh_token="legacy-refresh",
            )
        )
        response = FakeResponse({"state": True, "data": {"list": [], "count": 0}})

        with patch.object(client._opener, "open", return_value=response) as request:
            snapshot = client.inspect_share("https://115.com/s/share-code")

        self.assertEqual((), snapshot.files)
        self.assertEqual("UID=1_A1_1; CID=abc; SEID=secret", request.call_args.args[0].get_header("Cookie"))

    def test_valid_cookie_reads_directory_when_legacy_open_tokens_remain(self):
        client = P115Client(
            p115_settings(
                p115_auth_mode="open",
                p115_open_access_token="legacy-access",
                p115_open_refresh_token="legacy-refresh",
            )
        )
        response = FakeResponse(
            {
                "state": True,
                "data": {
                    "list": [{"cid": "folder-1", "pid": "0", "n": "媒体库", "fc": "0"}],
                    "count": 1,
                },
            }
        )

        with (
            patch.object(client._opener, "open", return_value=response) as request,
            patch.object(client, "_with_open_client") as open_request,
        ):
            items = client.list_directory("0")

        self.assertEqual(["媒体库"], [item.name for item in items])
        self.assertEqual("UID=1_A1_1; CID=abc; SEID=secret", request.call_args.args[0].get_header("Cookie"))
        self.assertIn("webapi.115.com/files", request.call_args.args[0].full_url)
        open_request.assert_not_called()

    def test_requires_complete_cookie_before_network_access(self):
        client = P115Client(p115_settings(p115_cookie="UID=1; CID=2"))
        with patch.object(client._opener, "open") as request:
            with self.assertRaisesRegex(P115Error, "有效的 115 Cookie"):
                client.inspect_share("https://115.com/s/share-code")
        request.assert_not_called()

    def test_rejects_cookie_with_newline_before_network_access(self):
        client = P115Client(p115_settings(p115_cookie="UID=1; CID=2; SEID=3\nINJECTED=value"))
        with patch.object(client._opener, "open") as request:
            with self.assertRaisesRegex(P115Error, "有效的 115 Cookie"):
                client.list_directory(0)
        request.assert_not_called()

    def test_rejects_non_115_and_non_https_share_urls(self):
        client = P115Client(p115_settings())
        for value in ("http://115.com/s/code", "https://example.com/s/code", "https://115.com/no-code"):
            with self.subTest(value=value), self.assertRaises(P115Error):
                client.parse_share_url(value)

    def test_accepts_115cdn_share_and_preserves_password(self):
        client = P115Client(p115_settings())
        share = client.parse_share_url("https://115cdn.com/s/swsoiie3wjf?password=m287")
        self.assertEqual("swsoiie3wjf", share.share_code)
        self.assertEqual("m287", share.receive_code)

    def test_receive_uses_selective_file_ids_and_target_directory(self):
        client = P115Client(p115_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"state": True, "data": {}})) as request:
            client.receive_share_files(P115ShareRef("share", "pass"), ["1", "2", "1"], "99")
        body = urllib.parse.parse_qs(request.call_args.args[0].data.decode())
        self.assertEqual(["1,2"], body["file_id"])
        self.assertEqual(["99"], body["cid"])
        self.assertNotIn("secret", request.call_args.args[0].full_url)

    def test_move_uses_repeated_fid_array_contract(self):
        client = P115Client(p115_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"state": True, "data": {}})) as request:
            client.move(["1", "2", "1"], "99")
        body = urllib.parse.parse_qs(request.call_args.args[0].data.decode())
        self.assertEqual(["1", "2"], body["fid[]"])
        self.assertEqual(["99"], body["pid"])

    def test_copy_uses_indexed_contract_and_sequential_safe_batches(self):
        client = P115Client(p115_settings())
        file_ids = [str(index) for index in range(1001)] + ["1"]
        responses = [
            FakeResponse({"state": True, "data": {}}),
            FakeResponse({"state": True, "data": {}}),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request:
            client.copy(file_ids, "99")

        self.assertEqual(2, request.call_count)
        first = urllib.parse.parse_qs(request.call_args_list[0].args[0].data.decode())
        second = urllib.parse.parse_qs(request.call_args_list[1].args[0].data.decode())
        self.assertEqual((["0"], ["999"], ["99"]), (first["fid[0]"], first["fid[999]"], first["pid"]))
        self.assertEqual((["1000"], ["99"]), (second["fid[0]"], second["pid"]))
        self.assertNotIn("fid[1]", second)
        self.assertTrue(all(call.args[0].full_url.endswith("/files/copy") for call in request.call_args_list))

    def test_copy_rejects_any_invalid_id_before_network_access(self):
        client = P115Client(p115_settings())
        with patch.object(client._opener, "open") as request:
            with self.assertRaisesRegex(P115Error, "复制文件 ID 无效"):
                client.copy(["valid-id", "bad id"], "99")
        request.assert_not_called()

    def test_sdk_cache_home_uses_mediaindex_cache_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
            settings = p115_settings(cache_dir=str(Path(tempdir) / "cache"))
            with patch.dict(os.environ, {"HOME": "/root", "XDG_CACHE_HOME": "/root/.cache"}):
                cache_dir = _prepare_p115_sdk_cache_env(settings)
                self.assertEqual(Path(settings.cache_dir) / "p115client" / ".p115client.cache.d", cache_dir)
                self.assertTrue(cache_dir.is_dir())
                self.assertEqual(str(Path(settings.cache_dir) / "p115client"), os.environ["HOME"])
                self.assertEqual(str(Path(settings.cache_dir) / "p115client" / ".cache"), os.environ["XDG_CACHE_HOME"])

    def test_sdk_cache_dir_is_refreshed_when_module_is_already_loaded(self):
        class FakeConst:
            _CACHE_DIR = Path("/root/.p115client.cache.d")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
            settings = p115_settings(cache_dir=str(Path(tempdir) / "cache"))
            with patch.dict(sys.modules, {"p115client.const": FakeConst}):
                cache_dir = _prepare_p115_sdk_cache_env(settings)
            self.assertEqual(cache_dir, FakeConst._CACHE_DIR)

    def test_open_client_prepares_writable_sdk_cache_before_import(self):
        settings = p115_settings(
            p115_cookie="",
            p115_auth_mode="open",
            p115_open_access_token="access",
            p115_open_refresh_token="refresh",
        )
        client = P115Client(settings)
        with (
            patch("app.clients.p115._prepare_p115_sdk_cache_env") as prepare_cache,
            patch("p115client.P115OpenClient") as open_client,
        ):
            client._open_client()

        prepare_cache.assert_called_once_with(settings)
        open_client.assert_called_once_with("access", "refresh", console_qrcode=False)

    def test_open_client_restores_process_home_after_sdk_initialization(self):
        settings = p115_settings(
            p115_cookie="",
            p115_auth_mode="open",
            p115_open_access_token="access",
            p115_open_refresh_token="refresh",
        )
        client = P115Client(settings)
        with (
            patch.dict(os.environ, {"HOME": "/original", "XDG_CACHE_HOME": "/original/cache"}),
            patch("p115client.P115OpenClient"),
        ):
            client._open_client()
            self.assertEqual("/original", os.environ["HOME"])
            self.assertEqual("/original/cache", os.environ["XDG_CACHE_HOME"])

    def test_cloud_download_retries_web_api_after_permission_style_sdk_error(self):
        client = P115Client(p115_settings())
        client.ensure_directory = MagicMock(return_value="123")  # type: ignore[method-assign]

        class FakeCloudDownloadClient:
            def __init__(self):
                self.calls = []

            def clouddownload_task_add_url(self, payload, *, type, timeout):
                self.calls.append((payload, type, timeout))
                if type == "ssp":
                    raise PermissionError(13, {"errno": 40100000, "error": "参数错误"})
                return {"state": True, "data": {"task_id": "ok"}}

            def clouddownload_task_list(self, payload, *, type, timeout):
                self.calls.append((payload, "list", timeout))
                return {"state": True, "data": {"tasks": []}}

        sdk = FakeCloudDownloadClient()
        with patch("p115client.P115Client", return_value=sdk):
            result = client.add_cloud_download("magnet:?xt=urn:btih:abcdef", "/MediaIndex/下载链接", wait_seconds=0)

        self.assertEqual({"state": True, "data": {"task_id": "ok"}}, result.payload)
        self.assertEqual("submitted", result.status)
        self.assertEqual(["ssp", "web", "list"], [call[1] for call in sdk.calls])
        self.assertEqual("123", sdk.calls[0][0]["wp_path_id"])

    def test_cloud_download_returns_done_when_task_list_reports_completed(self):
        client = P115Client(p115_settings())
        client.ensure_directory = MagicMock(return_value="123")  # type: ignore[method-assign]

        class FakeCloudDownloadClient:
            def clouddownload_task_add_url(self, payload, *, type, timeout):
                return {"state": True, "data": {"info_hash": "abcdef"}}

            def clouddownload_task(self, payload, *, type, timeout):
                return {"state": True, "data": {"info_hash": "abcdef", "status": 11, "name": "done.mkv"}}

        with patch("p115client.P115Client", return_value=FakeCloudDownloadClient()):
            result = client.add_cloud_download(
                "magnet:?xt=urn:btih:abcdef",
                "/MediaIndex/下载链接",
                wait_seconds=0,
            )

        self.assertEqual("done", result.status)
        self.assertIn("已完成", result.message)

    def test_cloud_download_preserves_sdk_error_detail(self):
        client = P115Client(p115_settings())
        client.ensure_directory = MagicMock(return_value="123")  # type: ignore[method-assign]

        class FakeCloudDownloadClient:
            def clouddownload_task_add_url(self, payload, *, type, timeout):
                raise PermissionError(13, {"errno": 50038, "error": "下载失败，含违规内容"})

        with patch("p115client.P115Client", return_value=FakeCloudDownloadClient()):
            with self.assertRaisesRegex(P115Error, "含违规内容.*50038"):
                client.add_cloud_download("magnet:?xt=urn:btih:abcdef", "/MediaIndex/下载链接")


    def test_cloud_download_capability_falls_back_after_unsupported_probe(self):
        client = P115Client(p115_settings())

        class FakeCloudDownloadClient:
            def clouddownload_quota_info(self, *, type="web", timeout):
                raise PermissionError(61, b"undefined action!")

            def clouddownload_task_count(self, *, type="web", timeout):
                return {"state": True, "data": {"total": 0}}

        with patch("p115client.P115Client", return_value=FakeCloudDownloadClient()):
            result = client.test_cloud_download_capability()
        self.assertEqual({"state": True, "data": {"total": 0}}, result)

    def test_cloud_download_capability_preserves_real_probe_error(self):
        client = P115Client(p115_settings())

        class FakeCloudDownloadClient:
            def clouddownload_quota_info(self, *, type="web", timeout):
                raise PermissionError(13, {"errno": 40100000, "error": "登录失效"})

        with patch("p115client.P115Client", return_value=FakeCloudDownloadClient()):
            with self.assertRaisesRegex(P115Error, "登录失效.*40100000"):
                client.test_cloud_download_capability()


class FakeP115Client:
    def __init__(self):
        self.settings = SimpleNamespace(
            p115_root_path="/MediaIndex",
            p115_staging_path="/MediaIndex/.staging",
            cloud_save_path="/strm",
            p115_request_timeout_seconds=1,
        )
        self.snapshot = P115ShareSnapshot(
            P115ShareRef("share"),
            (
                P115File("source-1", "0", "source.mkv", "/source.mkv", 100),
                P115File("source-2", "0", "other.mkv", "/other.mkv", 200),
            ),
        )
        self.staging_items: list[P115File] = []
        self.final_items: list[P115File] = []
        self.received_ids: list[str] = []

    def configured(self):
        return True

    def inspect_share(self, _share_url):
        return self.snapshot

    def ensure_directory(self, path):
        return "staging" if "/.staging/" in path else "final"

    def directory_id(self, path):
        return "final" if path.startswith("/MediaIndex/movie") else "0"

    def list_directory(self, cid):
        return tuple(self.staging_items if cid == "staging" else self.final_items)

    def receive_share_files(self, _share, file_ids, _target_cid):
        self.received_ids = list(file_ids)
        source = next(item for item in self.snapshot.files if item.file_id == file_ids[0])
        self.staging_items = [P115File("received-1", "staging", source.name, source.path, source.size)]
        return {}

    def rename(self, pairs):
        names = dict(pairs)
        self.staging_items = [
            P115File(item.file_id, item.parent_id, names.get(item.file_id, item.name), item.path, item.size)
            for item in self.staging_items
        ]

    def move(self, file_ids, _target_cid):
        self.final_items.extend(item for item in self.staging_items if item.file_id in file_ids)
        self.staging_items = [item for item in self.staging_items if item.file_id not in file_ids]

    def download_share_file(self, _share, source, destination):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * source.size)
        return source.size


class P115ProviderTests(unittest.TestCase):
    def test_provider_resumes_received_staging_file_without_receiving_again(self):
        client = FakeP115Client()
        client.staging_items = [P115File("received-old", "staging", "source.mkv", "/source.mkv", 100)]
        client.receive_share_files = MagicMock(side_effect=AssertionError("must not receive the share twice"))
        target = MediaTarget(1, "movie", "测试", series_year="2026")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(RenamePair("source.mkv", "source\\.mkv", "测试.2026.mkv", source_id="source-1", source_size=100),),
        )

        result = P115TransferProvider(client).execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))

        self.assertTrue(result.ok, result.message)
        client.receive_share_files.assert_not_called()
        self.assertEqual(["测试.2026.mkv"], [item.name for item in client.final_items])

    def test_provider_resumes_renamed_staging_file_without_receiving_or_renaming_again(self):
        client = FakeP115Client()
        client.staging_items = [P115File("received-old", "staging", "测试.2026.mkv", "/测试.2026.mkv", 100)]
        client.receive_share_files = MagicMock(side_effect=AssertionError("must not receive the share twice"))
        client.rename = MagicMock(wraps=client.rename)
        target = MediaTarget(1, "movie", "测试", series_year="2026")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(RenamePair("source.mkv", "source\\.mkv", "测试.2026.mkv", source_id="source-1", source_size=100),),
        )

        result = P115TransferProvider(client).execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))

        self.assertTrue(result.ok, result.message)
        client.receive_share_files.assert_not_called()
        client.rename.assert_not_called()
        self.assertEqual(["测试.2026.mkv"], [item.name for item in client.final_items])

    def test_provider_keeps_full_selection_staging_identity_during_partial_recovery(self):
        client = FakeP115Client()
        client.directory_id = lambda path: "final" if path.startswith("/MediaIndex/tv") else "0"
        client.final_items = [P115File("final-1", "final", "测试.2026.S01E01.mkv", "/测试.2026.S01E01.mkv", 100)]
        client.staging_items = [P115File("received-2", "staging", "测试.2026.S01E02.mkv", "/测试.2026.S01E02.mkv", 200)]
        client.receive_share_files = MagicMock(side_effect=AssertionError("must not receive the share twice"))
        client.rename = MagicMock(wraps=client.rename)
        client.ensure_directory = MagicMock(wraps=client.ensure_directory)
        target = MediaTarget(1, "tv", "测试", series_year="2026", season_number=1)
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(
                RenamePair("source.mkv", "source\\.mkv", "测试.2026.S01E01.mkv", episode_number=1, source_id="source-1", source_size=100),
                RenamePair("other.mkv", "other\\.mkv", "测试.2026.S01E02.mkv", episode_number=2, source_id="source-2", source_size=200),
            ),
        )

        result = P115TransferProvider(client).execute(TransferPlan(target, resolution, "/strm/tv/测试 (2026)"))

        expected_fingerprint = sha256(b"https://115.com/s/share\nsource-1\nsource-2").hexdigest()[:16]
        self.assertTrue(result.ok, result.message)
        self.assertEqual(f"/MediaIndex/.staging/{expected_fingerprint}", client.ensure_directory.call_args_list[0].args[0])
        client.receive_share_files.assert_not_called()
        client.rename.assert_not_called()
        self.assertEqual(
            ["测试.2026.S01E01.mkv", "测试.2026.S01E02.mkv"],
            [item.name for item in client.final_items],
        )

    def test_provider_recovers_when_move_committed_before_response_failed(self):
        client = FakeP115Client()
        original_move = client.move

        def move_then_fail(file_ids, target_cid):
            original_move(file_ids, target_cid)
            raise P115Error("115 连接失败（URLError）")

        client.move = move_then_fail
        target = MediaTarget(1, "movie", "测试", series_year="2026")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(RenamePair("source.mkv", "source\\.mkv", "测试.2026.mkv", source_id="source-1", source_size=100),),
        )
        provider = P115TransferProvider(client)

        first = provider.execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))
        self.assertFalse(first.ok)
        self.assertEqual(["测试.2026.mkv"], [item.name for item in client.final_items])

        client.receive_share_files = MagicMock(side_effect=AssertionError("must not receive the share twice"))
        recovered = provider.execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))

        self.assertTrue(recovered.ok, recovered.message)
        self.assertTrue(recovered.confirmed)
        client.receive_share_files.assert_not_called()

    def test_provider_retries_staging_directory_and_does_not_create_final_first(self):
        client = FakeP115Client()
        original_ensure = client.ensure_directory
        calls = []
        failures = 1
        final_created = False

        def directory_id(path):
            return "final" if final_created and path.startswith("/MediaIndex/movie") else "0"

        def flaky_ensure(path):
            nonlocal failures, final_created
            calls.append(path)
            if ".staging" in path and failures:
                failures -= 1
                raise P115Error("115 创建目录失败（错误码 990002）")
            if ".staging" not in path:
                final_created = True
            return original_ensure(path)

        client.directory_id = directory_id
        client.ensure_directory = flaky_ensure
        target = MediaTarget(1, "movie", "测试", series_year="2026")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(RenamePair("source.mkv", "source\\.mkv", "测试.2026.mkv", source_id="source-1", source_size=100),),
        )

        with patch("app.providers.p115.time.sleep"):
            result = P115TransferProvider(client).execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))

        self.assertTrue(result.ok, result.message)
        self.assertIn(".staging", calls[0])
        self.assertIn(".staging", calls[1])
        self.assertNotIn(".staging", calls[-1])

    def test_provider_executes_selected_receive_rename_move_and_reconcile(self):
        client = FakeP115Client()
        provider = P115TransferProvider(client)
        target = MediaTarget(1, "movie", "测试", series_year="2026")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(
                RenamePair(
                    "source.mkv",
                    "source\\.mkv",
                    "测试.2026.mkv",
                    source_id="source-1",
                    source_path="/source.mkv",
                    source_size=100,
                ),
            ),
        )
        result = provider.execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))
        self.assertTrue(result.ok)
        self.assertTrue(result.confirmed)
        self.assertEqual("provider_completed", result.stage)
        self.assertEqual(["source-1"], client.received_ids)
        self.assertEqual(["测试.2026.mkv"], [item.name for item in client.final_items])
        self.assertIn(ProviderCapability.SELECTIVE_TRANSFER, provider.capabilities())

    def test_provider_accepts_only_marked_staging_path_outside_formal_root(self):
        client = FakeP115Client()
        client.settings.provider_cloud_download_path = lambda _provider: "/独立云下载"
        staging_path = "/独立云下载/01电影/测试 (2026)"
        client.directory_id = lambda path: "final" if path == staging_path else "0"
        target = MediaTarget(1, "movie", "测试", series_year="2026", category="movie")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(
                RenamePair(
                    "source.mkv",
                    "source\\.mkv",
                    "测试.2026.mkv",
                    source_id="source-1",
                    source_size=100,
                ),
            ),
        )

        accepted = P115TransferProvider(client).execute(
            TransferPlan(
                target,
                resolution,
                staging_path,
                destination_scope="cloud_download",
                cloud_download_child="01电影",
            )
        )
        rejected = P115TransferProvider(FakeP115Client()).execute(
            TransferPlan(target, resolution, staging_path)
        )

        self.assertTrue(accepted.ok, accepted.message)
        self.assertEqual(["测试.2026.mkv"], [item.name for item in client.final_items])
        self.assertFalse(rejected.ok)
        self.assertIn("超出允许", rejected.message)

    def test_local_provider_downloads_selected_file_into_configured_root(self):
        client = FakeP115Client()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
            with patch.dict(
                os.environ,
                {
                    "P115_LOCAL_PATH": tempdir,
                    "P115_CATEGORY_PATHS_JSON": '{"movie":"/电影"}',
                    "DB_PATH": ":memory:",
                },
            ):
                get_settings.cache_clear()
                save_path = f"{tempdir.replace(chr(92), '/')}/电影/测试(2026)"
                target = MediaTarget(1, "movie", "测试", category="movie", series_year="2026")
                resolution = LinkResolution(
                    True,
                    "ready",
                    "ready",
                    share_url="https://115.com/s/share",
                    rename_pairs=(
                        RenamePair(
                            "source.mkv",
                            "source\\.mkv",
                            "测试.2026.mkv",
                            source_id="source-1",
                            source_size=100,
                        ),
                    ),
                )
                with patch("app.providers.p115.is_allowed_save_path", return_value=True):
                    result = P115LocalTransferProvider(client).execute(
                        TransferPlan(target, resolution, save_path)
                    )
                self.assertTrue(result.ok, result.message)
                self.assertTrue((Path(save_path) / "测试.2026.mkv").is_file())
        get_settings.cache_clear()

    def test_provider_fails_closed_when_source_identity_is_ambiguous(self):
        client = FakeP115Client()
        client.snapshot = P115ShareSnapshot(
            P115ShareRef("share"),
            (
                P115File("1", "0", "same.mkv", "/A/same.mkv", 100),
                P115File("2", "0", "same.mkv", "/B/same.mkv", 100),
            ),
        )
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(RenamePair("same.mkv", "same", "renamed.mkv", source_size=100),),
        )
        result = P115TransferProvider(client).execute(
            TransferPlan(MediaTarget(1, "movie", "测试"), resolution, "/strm/movie/测试")
        )
        self.assertFalse(result.ok)
        self.assertEqual("provider_failed", result.stage)
        self.assertEqual([], client.received_ids)

    def test_episode_resolver_uses_native_115_inspection(self):
        client = FakeP115Client()
        client.snapshot = P115ShareSnapshot(
            P115ShareRef("share"),
            (P115File("1", "0", "测试剧.S01E01.mkv", "/测试剧.S01E01.mkv", 100),),
        )
        provider = P115TransferProvider(client)

        class Pansou:
            def search_detailed(self, *_args, **_kwargs):
                return SimpleNamespace(
                    items=[{"share_url": "https://115.com/s/share", "title": "测试剧 S01"}],
                    error="",
                )

        target = MediaTarget(
            1,
            "tv",
            "测试剧",
            series_year="2026",
            season_number=1,
            episodes=(EpisodeTarget(1, 1, match_tokens=("S01E01", "E01")),),
        )
        result = resolve_episode_source(target, qas=provider, pansou=Pansou(), max_queries=1, provider_filter="p115")
        self.assertTrue(result.ok)
        self.assertEqual("1", result.rename_pairs[0].source_id)


if __name__ == "__main__":
    unittest.main()
