import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.playback_main import create_playback_app
from app.services.emby_reverse_proxy import emby_upstream_url


class _FakeEmbyHandler(BaseHTTPRequestHandler):
    last_path = ""
    last_range = ""

    def do_GET(self):
        type(self).last_path = self.path
        type(self).last_range = self.headers.get("Range", "")
        payload = b"fake emby"
        self.send_response(206 if type(self).last_range else 200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Emby-Test", "forwarded")
        if type(self).last_range:
            self.send_header("Content-Range", "bytes 0-8/9")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        return


class EmbyReverseProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeEmbyHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {"EMBY_BASE_URL": f"http://127.0.0.1:{self.server.server_port}"},
            clear=False,
        )
        self.environment.start()
        get_settings.cache_clear()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()

    def test_root_and_emby_requests_are_transparently_forwarded(self):
        with TestClient(create_playback_app()) as client:
            response = client.get("/web/index.html?device=tv")

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"fake emby", response.content)
        self.assertEqual("forwarded", response.headers["x-emby-test"])
        self.assertEqual("/web/index.html?device=tv", _FakeEmbyHandler.last_path)

    def test_range_header_and_partial_response_are_preserved(self):
        with TestClient(create_playback_app()) as client:
            response = client.get("/Videos/1/stream", headers={"Range": "bytes=0-8"})

        self.assertEqual(206, response.status_code)
        self.assertEqual("bytes 0-8/9", response.headers["content-range"])
        self.assertEqual("bytes=0-8", _FakeEmbyHandler.last_range)

    def test_websocket_target_uses_same_required_emby_origin(self):
        self.assertEqual(
            f"ws://127.0.0.1:{self.server.server_port}/socket?api_key=test",
            emby_upstream_url("socket", "api_key=test", websocket=True),
        )

    def test_missing_emby_address_fails_with_safe_configuration_error(self):
        with patch.dict(os.environ, {"EMBY_BASE_URL": ""}, clear=False):
            get_settings.cache_clear()
            with TestClient(create_playback_app()) as client:
                response = client.get("/")

        self.assertEqual(503, response.status_code)
        self.assertIn("Emby 内网地址", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
