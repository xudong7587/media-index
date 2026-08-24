import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.clients.openlist import OpenListClient
from app.clients.p115 import P115Client, P115Error, _persist_open_tokens


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

    def test_maps_original_115_path_to_the_storage_mount(self):
        client = OpenListClient.__new__(OpenListClient)
        client.p115_auth = lambda: {"mount_path": "/115"}

        self.assertEqual("/115/媒体库/下载文件夹", client.p115_storage_path("/媒体库/下载文件夹"))


class P115LegacyOpenCompatibilityTests(unittest.TestCase):
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

    @patch("p115client.P115OpenClient")
    def test_open_only_credentials_are_not_a_native_115_connection(self, open_client):
        client = P115Client(self.settings())

        self.assertFalse(client.configured())
        with self.assertRaisesRegex(P115Error, "有效的 115 Cookie"):
            P115Client(self.settings()).list_directory()
        open_client.assert_not_called()

    @patch("p115client.P115OpenClient")
    def test_open_only_credentials_cannot_reach_offline_download(self, open_client):
        client = P115Client(self.settings())
        with self.assertRaises(P115Error):
            client.add_cloud_download("magnet:?xt=urn:btih:test", "/下载")
        open_client.assert_not_called()

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
