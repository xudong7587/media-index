import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from starlette.routing import NoMatchFound
from app.clients.p115 import P115DirectLink
from app.clients.quark import QuarkDownloadLink
from app.core.config import get_settings
from app.db.database import init_db
from app.services.media_assets import AssetInput, register_asset
from app.services.playback import PlaybackError, invalidate_asset_cache, issue_asset_token, open_playback_stream, resolve_playback_redirect, verify_asset_token
from app.playback_main import create_playback_app


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db"), "AUTH_SECRET": "test-secret"})
        self.environment.start()
        get_settings.cache_clear()
        init_db()
        self.asset = register_asset(AssetInput(provider="p115", file_id="115-file", name="Movie.mkv", size=100, sha1="A" * 40, status="ready"))
        invalidate_asset_cache(self.asset["id"])

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_signed_asset_token_resolves_to_direct_302_target_without_exposing_it_in_token(self):
        token = issue_asset_token(self.asset)
        with patch("app.services.playback.P115Client.direct_download_link", return_value=P115DirectLink("https://cdn.115.com/temporary")):
            target = resolve_playback_redirect(token)

        self.assertEqual("https://cdn.115.com/temporary", target)
        self.assertNotIn("temporary", token)
        self.assertEqual("115-file", verify_asset_token(token)["file_id"])

    def test_token_is_revoked_when_asset_version_changes(self):
        token = issue_asset_token(self.asset)
        register_asset(AssetInput(provider="p115", file_id="115-file", name="Movie.mkv", size=101, sha1="B" * 40, status="ready"))
        with self.assertRaisesRegex(PlaybackError, "失效"):
            verify_asset_token(token)

    def test_header_bound_upstream_link_fails_closed_instead_of_redirecting_without_headers(self):
        token = issue_asset_token(self.asset)
        with patch("app.services.playback.P115Client.direct_download_link", return_value=P115DirectLink("https://cdn.115.com/temporary", ("cookie",))):
            with self.assertRaisesRegex(PlaybackError, "请求头"):
                resolve_playback_redirect(token)

    def test_header_bound_115_link_is_streamed_server_side_with_range(self):
        token = issue_asset_token(self.asset)

        class Response:
            status = 206
            headers = {"Content-Type": "video/mp4", "Content-Length": "4", "Content-Range": "bytes 0-3/100"}
            def read(self, _size):
                if getattr(self, "sent", False):
                    return b""
                self.sent = True
                return b"data"
            def close(self):
                self.closed = True

        response = Response()
        with patch("app.services.playback.P115Client.direct_download_link", return_value=P115DirectLink("https://cdn.115.com/temporary", ("user-agent",), {"User-Agent": "115-player"})), patch("app.services.playback.urllib.request.urlopen", return_value=response) as open_upstream:
            stream = open_playback_stream(token, "bytes=0-3")
            self.assertEqual(206, stream.status_code)
            self.assertEqual(b"data", b"".join(stream.chunks))

        request = open_upstream.call_args.args[0]
        self.assertEqual("bytes=0-3", request.get_header("Range"))
        self.assertEqual("115-player", request.get_header("User-agent"))

    def test_expired_cached_115_link_is_refreshed_once_after_403(self):
        token = issue_asset_token(self.asset)

        class Response:
            status = 206
            headers = {"Content-Type": "video/mp4", "Content-Length": "4", "Content-Range": "bytes 4-7/100"}
            def read(self, _size):
                if getattr(self, "sent", False):
                    return b""
                self.sent = True
                return b"data"
            def close(self):
                self.closed = True

        stale_error = urllib.error.HTTPError("https://cdn.115.com/stale", 403, "Forbidden", {}, None)
        links = [
            P115DirectLink("https://cdn.115.com/stale", ("user-agent",), {"User-Agent": "115-player"}),
            P115DirectLink("https://cdn.115.com/fresh", ("user-agent",), {"User-Agent": "115-player"}),
        ]
        with patch("app.services.playback.P115Client.direct_download_link", side_effect=links) as direct_link, patch(
            "app.services.playback.urllib.request.urlopen", side_effect=[stale_error, Response()]
        ) as open_upstream:
            stream = open_playback_stream(token, "bytes=4-7")
            self.assertEqual(206, stream.status_code)
            self.assertEqual(b"data", b"".join(stream.chunks))

        self.assertEqual(2, direct_link.call_count)
        self.assertEqual(2, open_upstream.call_count)
        self.assertEqual("https://cdn.115.com/fresh", open_upstream.call_args.args[0].full_url)

    def test_quark_asset_uses_cookie_free_download_link_for_302(self):
        asset = register_asset(AssetInput(provider="quark", file_id="quark-file", name="Movie.mkv", size=100, status="ready"))
        invalidate_asset_cache(asset["id"])
        token = issue_asset_token(asset)
        with patch("app.services.playback.QuarkClient.download_link", return_value=QuarkDownloadLink("quark-file", "https://cdn.quark.cn/temp")):
            self.assertEqual("https://cdn.quark.cn/temp", resolve_playback_redirect(token))

    def test_dedicated_playback_app_keeps_playback_routes_ahead_of_emby_proxy(self):
        app = create_playback_app()
        self.assertEqual("/api/play/signed-token", app.url_path_for("play_asset", token="signed-token"))
        self.assertEqual("/health", app.url_path_for("health"))
        self.assertEqual("/web/index.html", app.url_path_for("proxy_emby_http", path="web/index.html"))
        with self.assertRaises(NoMatchFound):
            app.url_path_for("status")


if __name__ == "__main__":
    unittest.main()
