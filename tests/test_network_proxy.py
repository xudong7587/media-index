import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.config import ProxyTestRequest, test_network_proxy as run_proxy_test, validate_proxy_url
from app.core.config import get_settings


class NetworkProxyTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def test_saved_ui_proxy_overrides_compose_startup_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / ".env"
            config_path.write_text("PROXY_URL=http://192.168.31.81:7890\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "MEDIA_CONFIG_PATH": str(config_path),
                "PROXY_URL": "http://compose-proxy:7890",
                "DB_PATH": str(root / "db.sqlite"),
                "CACHE_DIR": str(root / "cache"),
            }, clear=False):
                get_settings.cache_clear()
                self.assertEqual("http://192.168.31.81:7890", get_settings().proxy_url)

    def test_saved_blank_proxy_can_disable_compose_proxy_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / ".env"
            config_path.write_text("PROXY_URL=\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "MEDIA_CONFIG_PATH": str(config_path),
                "PROXY_URL": "http://compose-proxy:7890",
                "DB_PATH": str(root / "db.sqlite"),
                "CACHE_DIR": str(root / "cache"),
            }, clear=False):
                get_settings.cache_clear()
                self.assertEqual("", get_settings().proxy_url)

    @patch("app.api.config.open_url")
    @patch("app.api.config.get_settings")
    def test_proxy_test_uses_unsaved_frontend_address_from_inside_backend(self, settings, opened):
        settings.return_value = SimpleNamespace(tmdb_api_key="tmdb-key", proxy_url="")
        response = MagicMock()
        response.read.return_value = b"{}"
        opened.return_value.__enter__.return_value = response

        result = run_proxy_test(ProxyTestRequest(proxy_url="http://192.168.31.81:7890"))

        self.assertTrue(result["ok"])
        self.assertEqual("http://192.168.31.81:7890", opened.call_args.kwargs["proxy_url_override"])
        self.assertIn("api.themoviedb.org", opened.call_args.args[0].full_url)

    def test_proxy_requires_a_complete_http_url_with_port(self):
        with self.assertRaisesRegex(Exception, "包含端口"):
            validate_proxy_url("http://192.168.31.81")


if __name__ == "__main__":
    unittest.main()
