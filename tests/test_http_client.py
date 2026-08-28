import unittest
from unittest.mock import patch

from app.clients.http import open_url


class HttpClientTests(unittest.TestCase):
    @patch("app.clients.http.get_settings")
    @patch("app.clients.http.urllib.request.build_opener")
    def test_direct_connection_when_proxy_is_empty(self, build_opener, get_settings):
        get_settings.return_value.proxy_url = ""
        opener = build_opener.return_value

        open_url("https://example.com", timeout=7)

        opener.open.assert_called_once_with("https://example.com", timeout=7)

    @patch("app.clients.http.get_settings")
    @patch("app.clients.http.urllib.request.build_opener")
    def test_configured_proxy_is_used_for_http_and_https(self, build_opener, get_settings):
        get_settings.return_value.proxy_url = "http://192.168.1.2:7890"

        open_url("https://example.com", timeout=9)

        opener = build_opener.return_value
        opener.open.assert_called_once_with("https://example.com", timeout=9)
        handler = build_opener.call_args.args[1]
        self.assertEqual(handler.proxies["http"], "http://192.168.1.2:7890")
        self.assertEqual(handler.proxies["https"], "http://192.168.1.2:7890")

    @patch("app.clients.http.get_settings")
    @patch("app.clients.http.urllib.request.build_opener")
    def test_api_requests_install_no_redirect_handler(self, build_opener, get_settings):
        get_settings.return_value.proxy_url = ""

        open_url("https://example.com", timeout=7)

        self.assertEqual("NoRedirectHandler", type(build_opener.call_args.args[0]).__name__)

    @patch("app.clients.http.get_settings")
    @patch("app.clients.http.urllib.request.build_opener")
    def test_local_service_names_bypass_the_configured_network_proxy(self, build_opener, get_settings):
        get_settings.return_value.proxy_url = "http://192.168.1.2:7890"

        open_url("http://pansou:8888/api/search", timeout=7)

        proxy_handler = build_opener.call_args.args[1]
        self.assertEqual({}, proxy_handler.proxies)

    @patch("app.clients.http.get_settings")
    @patch("app.clients.http.urllib.request.build_opener")
    def test_draft_proxy_override_is_used_by_connection_test(self, build_opener, get_settings):
        get_settings.return_value.proxy_url = "http://saved:7890"

        open_url("https://api.themoviedb.org/3/configuration", timeout=15, proxy_url_override="http://192.168.31.81:7890")

        proxy_handler = build_opener.call_args.args[1]
        self.assertEqual("http://192.168.31.81:7890", proxy_handler.proxies["https"])


if __name__ == "__main__":
    unittest.main()
