import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.clients.openlist import OpenListClient
from app.clients.p115 import P115Client, _persist_open_tokens


class OpenListP115AuthTests(unittest.TestCase):
    def test_prefers_cookie_storage_over_open_platform_storage(self):
        client = OpenListClient.__new__(OpenListClient)
        client._get = lambda _path, _params: {
            "code": 200,
            "data": {
                "content": [
                    {
                        "driver": "115 Open",
                        "mount_path": "/115-open",
                        "addition": '{"access_token":"access","refresh_token":"refresh"}',
                    },
                    {
                        "driver": "115",
                        "mount_path": "/115",
                        "addition": '{"cookie":"UID=1; CID=2; SEID=3"}',
                    },
                ]
            },
        }

        self.assertEqual(
            client.p115_auth(),
            {"mode": "cookie", "cookie": "UID=1; CID=2; SEID=3", "mount_path": "/115"},
        )

    def test_returns_open_platform_tokens_when_cookie_storage_is_absent(self):
        client = OpenListClient.__new__(OpenListClient)
        client._get = lambda _path, _params: {
            "code": 200,
            "data": {
                "content": [
                    {
                        "driver": "115_open",
                        "mount_path": "/115",
                        "addition": '{"access_token":"access","refresh_token":"refresh"}',
                    }
                ]
            },
        }

        self.assertEqual(
            client.p115_auth(),
            {"mode": "open", "access_token": "access", "refresh_token": "refresh", "mount_path": "/115"},
        )


class P115OpenClientTests(unittest.TestCase):
    def settings(self):
        return SimpleNamespace(
            p115_cookie="",
            p115_auth_mode="open",
            p115_open_access_token="access",
            p115_open_refresh_token="refresh",
            proxy_url="",
            p115_request_timeout_seconds=30,
            p115_max_share_files=5000,
            cache_dir=".",
        )

    @patch("app.clients.p115._persist_open_tokens")
    @patch("p115client.P115OpenClient")
    def test_open_credentials_use_open_api_for_directory_and_offline_download(self, open_client, _persist):
        sdk = open_client.return_value
        sdk.fs_files.return_value = {
            "state": True,
            "count": 1,
            "data": [{"fid": "100", "pid": "0", "fn": "电影", "fc": "0"}],
        }
        sdk.fs_info.return_value = {"state": True, "data": {"file_id": "42"}}
        sdk.clouddownload_task_add_urls.return_value = {"state": True, "data": {"task_id": "task-1"}}
        client = P115Client(self.settings())

        self.assertEqual(client.list_directory()[0].name, "电影")
        self.assertEqual(client.directory_id("/电影"), "42")
        result = client.add_cloud_download("magnet:?xt=urn:btih:test", "/下载")

        self.assertEqual(result.target_cid, "42")
        sdk.clouddownload_task_add_urls.assert_called_once()

    @patch("app.clients.p115._persist_open_tokens")
    @patch("p115client.P115OpenClient")
    def test_directory_read_retries_transient_tls_failure_once(self, open_client, _persist):
        sdk = open_client.return_value
        sdk.fs_files.side_effect = [
            RuntimeError("SSLEOFError: remote end closed"),
            {"state": True, "count": 1, "data": [{"fid": "100", "pid": "0", "fn": "电影", "fc": "0"}]},
        ]

        entries = P115Client(self.settings()).list_directory()

        self.assertEqual(["电影"], [entry.name for entry in entries])
        self.assertEqual(2, sdk.fs_files.call_count)

    def test_refreshed_open_tokens_clear_settings_cache(self):
        settings = self.settings()
        client = SimpleNamespace(access_token="new-access", refresh_token="new-refresh")
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "runtime.env"
            config_path.write_text("P115_AUTH_MODE=open\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False),
                patch("app.clients.p115.get_settings.cache_clear") as clear_cache,
            ):
                _persist_open_tokens(settings, client)

            saved = config_path.read_text(encoding="utf-8")
        self.assertIn("P115_OPEN_ACCESS_TOKEN=new-access", saved)
        self.assertIn("P115_OPEN_REFRESH_TOKEN=new-refresh", saved)
        clear_cache.assert_called_once()
