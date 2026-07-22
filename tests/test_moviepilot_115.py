import io
import json
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.api.config import ConfigUpdate, status, test_moviepilot_115, update_config
from app.clients.moviepilot_115 import MoviePilot115Client, MoviePilot115Error
from app.core.config import Settings


class FakeResponse:
    def __init__(self, payload: dict | str):
        self.payload = json.dumps(payload).encode() if isinstance(payload, dict) else payload.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def moviepilot_settings(**overrides) -> Settings:
    values = {
        "moviepilot_base_url": "https://moviepilot.example",
        "moviepilot_api_token": "super-secret-token",
        "moviepilot_115_plugin_id": "P115StrmHelper",
        "db_path": "unused.db",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class MoviePilot115ClientTests(unittest.TestCase):
    def test_token_is_sent_in_header_and_never_in_url(self):
        client = MoviePilot115Client(moviepilot_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"ok": True})) as request:
            client.get_json("/api/v1/test", timeout=3)
        req = request.call_args.args[0]
        self.assertEqual("super-secret-token", req.get_header("X-api-key"))
        self.assertNotIn("super-secret-token", req.full_url)

    def test_probe_detects_plugin_and_external_organize_capability(self):
        client = MoviePilot115Client(moviepilot_settings())
        paths = {
            f"{client.plugin_base_path}/get_status": {"get": {}},
            client.transfer_path: {"get": {}},
        }
        status_payload = {
            "code": 0,
            "msg": "success",
            "data": {"enabled": True, "has_client": True, "running": False},
        }
        with patch.object(
            client._opener,
            "open",
            side_effect=[FakeResponse({"paths": paths}), FakeResponse(status_payload)],
        ):
            result = client.probe()
        self.assertTrue(result.connected)
        self.assertTrue(result.plugin_available)
        self.assertTrue(result.plugin_enabled)
        self.assertTrue(result.client_ready)
        self.assertEqual(("external_organize",), result.capabilities)

    def test_probe_reports_missing_plugin_without_calling_plugin_status(self):
        client = MoviePilot115Client(moviepilot_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"paths": {}})) as request:
            result = client.probe()
        self.assertTrue(result.connected)
        self.assertFalse(result.plugin_available)
        request.assert_called_once()

    def test_auth_error_is_redacted(self):
        client = MoviePilot115Client(moviepilot_settings())
        error = urllib.error.HTTPError(
            client._url("/api/v1/test"),
            401,
            "body contains super-secret-token",
            {},
            io.BytesIO(b"super-secret-token"),
        )
        with patch.object(client._opener, "open", side_effect=error):
            with self.assertRaises(MoviePilot115Error) as raised:
                client.get_json("/api/v1/test")
        self.assertNotIn("super-secret-token", str(raised.exception))
        self.assertIn("Token", str(raised.exception))

    def test_redirect_is_rejected(self):
        client = MoviePilot115Client(moviepilot_settings())
        error = urllib.error.HTTPError(client._url("/docs"), 302, "redirect", {"Location": "http://other"}, None)
        with patch.object(client._opener, "open", side_effect=error):
            with self.assertRaisesRegex(MoviePilot115Error, "拒绝重定向"):
                client.get_json("/docs")

    def test_non_json_response_is_rejected(self):
        client = MoviePilot115Client(moviepilot_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse("<html>frontend</html>")):
            with self.assertRaisesRegex(MoviePilot115Error, "非 JSON"):
                client.get_json("/openapi.json")


class MoviePilot115ConfigTests(unittest.TestCase):
    def test_status_never_returns_token(self):
        settings = moviepilot_settings()
        with patch("app.api.config.get_settings", return_value=settings):
            result = status()
        self.assertTrue(result["has_moviepilot_115"])
        self.assertTrue(result["has_moviepilot_token"])
        self.assertNotIn("moviepilot_api_token", result)
        self.assertNotIn("super-secret-token", json.dumps(result))

    def test_update_persists_moviepilot_configuration(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            payload = ConfigUpdate(
                moviepilot_base_url="https://moviepilot.example/",
                moviepilot_api_token="new-secret",
                moviepilot_115_plugin_id="P115StrmHelper",
            )
            with (
                patch.dict("os.environ", {"MEDIA_CONFIG_PATH": str(env_path)}),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = update_config(payload)
            saved = env_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn("MOVIEPILOT_BASE_URL=https://moviepilot.example", saved)
        self.assertIn("MOVIEPILOT_API_TOKEN=new-secret", saved)

    def test_test_endpoint_returns_probe_without_token(self):
        settings = moviepilot_settings()
        client = MoviePilot115Client(settings)
        paths = {
            f"{client.plugin_base_path}/get_status": {"get": {}},
            client.transfer_path: {"get": {}},
        }
        responses = [
            FakeResponse({"paths": paths}),
            FakeResponse({"code": 0, "msg": "ok", "data": {"enabled": True, "has_client": True, "running": True}}),
        ]
        with (
            patch("app.api.config.get_settings", return_value=settings),
            patch("app.clients.moviepilot_115.urllib.request.build_opener") as build_opener,
        ):
            build_opener.return_value.open.side_effect = responses
            result = test_moviepilot_115()
        self.assertTrue(result["ok"])
        self.assertNotIn("super-secret-token", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
