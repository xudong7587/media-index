import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.playback_main import create_playback_app
from app.services.emby_reverse_proxy import _clear_emby_playback_cache, emby_upstream_url


class _FakeEmbyHandler(BaseHTTPRequestHandler):
    last_path = ""
    last_range = ""
    playback_payload = b""

    def _respond(self):
        type(self).last_path = self.path
        type(self).last_range = self.headers.get("Range", "")
        payload = type(self).playback_payload if "PlaybackInfo" in self.path and type(self).playback_payload else b"fake emby"
        self.send_response(206 if type(self).last_range else 200)
        self.send_header("Content-Type", "application/json" if "PlaybackInfo" in self.path else "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Emby-Test", "forwarded")
        if type(self).last_range:
            self.send_header("Content-Range", "bytes 0-8/9")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._respond()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length:
            self.rfile.read(content_length)
        self._respond()

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
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.strm_root = Path(self.tempdir.name)
        self.environment = patch.dict(
            os.environ,
            {
                "EMBY_BASE_URL": f"http://127.0.0.1:{self.server.server_port}",
                "STRM_OUTPUT_ROOT": str(self.strm_root),
            },
            clear=False,
        )
        self.environment.start()
        get_settings.cache_clear()
        _clear_emby_playback_cache()
        _FakeEmbyHandler.playback_payload = b""

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        _clear_emby_playback_cache()
        self.tempdir.cleanup()

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

    def test_playback_info_is_rewritten_and_external_stream_request_gets_cloud_302(self):
        media_file = self.strm_root / "Movies" / "Movie.strm"
        media_file.parent.mkdir()
        media_file.write_text("http://media-index:8097/api/play/signed-token\n", encoding="utf-8")
        _FakeEmbyHandler.playback_payload = json.dumps(
            {
                "ItemId": "42",
                "MediaSources": [
                    {
                        "Id": "source-42",
                        "ItemId": "42",
                        "Path": "/emby-library/Movies/Movie.strm",
                        "SupportsDirectPlay": False,
                        "SupportsDirectStream": False,
                        "SupportsTranscoding": True,
                        "TranscodingUrl": "/Videos/42/master.m3u8",
                    }
                ],
            }
        ).encode("utf-8")

        with TestClient(create_playback_app()) as client:
            playback = client.post("/Items/42/PlaybackInfo?api_key=emby-key", json={})
            with patch(
                "app.services.emby_reverse_proxy.resolve_playback_redirect",
                return_value="https://cdn.115.com/Movie.mkv",
            ) as resolve:
                stream = client.get(
                    "/Videos/42/stream?MediaSourceId=source-42&api_key=emby-key",
                    headers={"User-Agent": "Emby for Android"},
                    follow_redirects=False,
                )

        source = playback.json()["MediaSources"][0]
        self.assertEqual(200, playback.status_code)
        self.assertEqual("playback-info-rewritten", playback.headers["x-mediaindex-playback-mode"])
        self.assertTrue(source["SupportsDirectPlay"])
        self.assertTrue(source["SupportsDirectStream"])
        self.assertFalse(source["SupportsTranscoding"])
        self.assertNotIn("TranscodingUrl", source)
        self.assertIn("/Videos/42/stream?", source["DirectStreamUrl"])
        self.assertEqual(302, stream.status_code)
        self.assertEqual("https://cdn.115.com/Movie.mkv", stream.headers["location"])
        self.assertEqual("emby-redirect", stream.headers["x-mediaindex-playback-mode"])
        resolve.assert_called_once_with("signed-token", "Emby for Android")
        self.assertIn("PlaybackInfo", _FakeEmbyHandler.last_path)

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
