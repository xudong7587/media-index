import io
import json
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.api.config import (
    ConfigUpdate,
    import_p115_from_moviepilot,
    status,
    test_moviepilot_115 as _test_moviepilot_115_endpoint,
    update_config,
)
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

    def test_submit_share_uses_plugin_contract_and_returns_save_parent(self):
        client = MoviePilot115Client(moviepilot_settings())
        payload = {
            "code": 0,
            "msg": "转存成功",
            "data": {"save_parent": {"path": "/媒体/电影", "id": "123"}},
        }
        with patch.object(client._opener, "open", return_value=FakeResponse(payload)) as request:
            result = client.submit_share("https://115.com/s/share-code", pan_path="/待整理")
        req = request.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        self.assertTrue(result.accepted)
        self.assertEqual("/媒体/电影", result.save_parent_path)
        self.assertEqual(["https://115.com/s/share-code"], query["share_url"])
        self.assertEqual(["/待整理"], query["pan_path"])
        self.assertEqual("super-secret-token", req.get_header("X-api-key"))
        self.assertNotIn("super-secret-token", req.full_url)

    def test_submit_share_redacts_share_url_from_plugin_error(self):
        client = MoviePilot115Client(moviepilot_settings())
        share_url = "https://115.com/s/private-code"
        with patch.object(
            client._opener,
            "open",
            return_value=FakeResponse({"code": -1, "msg": f"无法转存 {share_url}"}),
        ):
            with self.assertRaises(MoviePilot115Error) as raised:
                client.submit_share(share_url)
        self.assertNotIn("private-code", str(raised.exception))

    def test_submit_share_rejects_non_115_url_before_network_call(self):
        client = MoviePilot115Client(moviepilot_settings())
        with patch.object(client._opener, "open") as request:
            with self.assertRaises(MoviePilot115Error):
                client.submit_share("https://example.com/s/not-115")
        request.assert_not_called()

    def test_submit_share_accepts_115cdn_root_url_with_password(self):
        client = MoviePilot115Client(moviepilot_settings())
        share_url = "https://115cdn.com/s/example-code?password=ke27"
        with patch.object(
            client._opener,
            "open",
            return_value=FakeResponse({"code": 0, "msg": "已接受", "data": {}}),
        ) as request:
            result = client.submit_share(share_url)

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args.args[0].full_url).query)
        self.assertTrue(result.accepted)
        self.assertEqual([share_url], query["share_url"])

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

    def test_reads_cookie_from_plugin_config_without_putting_it_in_url(self):
        client = MoviePilot115Client(moviepilot_settings())
        cookie = "UID=1_A1_1; CID=abc; SEID=secret"
        with patch.object(client._opener, "open", return_value=FakeResponse({"cookies": cookie})) as request:
            result = client.read_p115_cookie()
        self.assertEqual(cookie, result)
        self.assertEqual(
            "https://moviepilot.example/api/v1/plugin/P115StrmHelper/get_config",
            request.call_args.args[0].full_url,
        )
        self.assertNotIn(cookie, request.call_args.args[0].full_url)

    def test_rejects_plugin_config_without_complete_cookie(self):
        client = MoviePilot115Client(moviepilot_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"cookies": "UID=1; CID=2"})):
            with self.assertRaisesRegex(MoviePilot115Error, "有效的 115 Cookie"):
                client.read_p115_cookie()

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
            result = _test_moviepilot_115_endpoint()
        self.assertTrue(result["ok"])
        self.assertNotIn("super-secret-token", json.dumps(result))

    def test_import_cookie_from_moviepilot_persists_secret_without_returning_it(self):
        settings = moviepilot_settings()
        cookie = "UID=1_A1_1; CID=abc; SEID=secret"
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with (
                patch.dict("os.environ", {"MEDIA_CONFIG_PATH": str(env_path)}),
                patch("app.api.config.get_settings", return_value=settings),
                patch.object(MoviePilot115Client, "read_p115_cookie", return_value=cookie),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = import_p115_from_moviepilot()
            saved = env_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertTrue(result["has_p115_cookie"])
        self.assertIn(f"P115_COOKIE={cookie}", saved)
        self.assertNotIn(cookie, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
