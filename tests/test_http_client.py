import unittest
from unittest.mock import patch

from app.clients.http import open_url


class HttpClientTests(unittest.TestCase):
    @patch("app.clients.http.get_settings")
    @patch("app.clients.http.urllib.request.urlopen")
    def test_direct_connection_when_proxy_is_empty(self, urlopen, get_settings):
        get_settings.return_value.proxy_url = ""

        open_url("https://example.com", timeout=7)

        urlopen.assert_called_once_with("https://example.com", timeout=7)

    @patch("app.clients.http.get_settings")
    @patch("app.clients.http.urllib.request.build_opener")
    def test_configured_proxy_is_used_for_http_and_https(self, build_opener, get_settings):
        get_settings.return_value.proxy_url = "http://192.168.1.2:7890"

        open_url("https://example.com", timeout=9)

        opener = build_opener.return_value
        opener.open.assert_called_once_with("https://example.com", timeout=9)
        handler = build_opener.call_args.args[0]
        self.assertEqual(handler.proxies["http"], "http://192.168.1.2:7890")
        self.assertEqual(handler.proxies["https"], "http://192.168.1.2:7890")


if __name__ == "__main__":
    unittest.main()
