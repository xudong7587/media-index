import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.routing import NoMatchFound
from app.clients.p115 import P115DirectLink
from app.clients.quark import QuarkDownloadLink
from app.core.config import get_settings
from app.db.database import init_db
from app.services.media_assets import AssetInput, register_asset
from app.services.playback import PlaybackError, invalidate_asset_cache, issue_asset_token, open_playback_stream, resolve_playback_redirect, verify_asset_token
from app.services.playback import _iter_upstream
from app.services.diagnostics import recent_diagnostic_events
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
            target = resolve_playback_redirect(token, "Emby for Android")

        self.assertEqual("https://cdn.115.com/temporary", target)
        self.assertNotIn("temporary", token)
        self.assertEqual("115-file", verify_asset_token(token)["file_id"])

    def test_playback_route_returns_real_302_without_streaming_through_nas(self):
        token = issue_asset_token(self.asset)
        app = create_playback_app()
        with patch(
            "app.services.playback.P115Client.direct_download_link",
            return_value=P115DirectLink(
                "https://cdn.115.com/temporary",
                ("user-agent",),
                {"User-Agent": "Emby for Android"},
            ),
        ) as direct_link, patch("app.api.playback.open_playback_stream") as proxy:
            response = TestClient(app).get(
                f"/api/play/{token}",
                headers={"User-Agent": "Emby for Android", "Range": "bytes=0-"},
                follow_redirects=False,
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("https://cdn.115.com/temporary", response.headers["location"])
        self.assertEqual("redirect", response.headers["x-mediaindex-playback-mode"])
        direct_link.assert_called_once_with("115-file", user_agent="Emby for Android")
        proxy.assert_not_called()

    def test_playback_route_marks_proxy_fallback_when_non_user_agent_headers_are_required(self):
        token = issue_asset_token(self.asset)

        class Stream:
            status_code = 206
            headers = {"Content-Type": "video/mp4", "Content-Range": "bytes 0-3/100"}
            chunks = iter((b"data",))

        app = create_playback_app()
        with patch(
            "app.services.playback.P115Client.direct_download_link",
            return_value=P115DirectLink("https://cdn.115.com/temporary", ("cookie",), {"Cookie": "provider-cookie"}),
        ), patch("app.api.playback.open_playback_stream", return_value=Stream()):
            response = TestClient(app).get(
                f"/api/play/{token}",
                headers={"User-Agent": "Emby for Android", "Range": "bytes=0-3"},
            )

        self.assertEqual(206, response.status_code)
        self.assertEqual("proxy", response.headers["x-mediaindex-playback-mode"])
        self.assertEqual("provider-headers-required", response.headers["x-mediaindex-playback-reason"])

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

    def test_quark_asset_proxies_authenticated_range_without_exposing_cookie(self):
        asset = register_asset(AssetInput(provider="quark", file_id="quark-file", name="Movie.mkv", size=100, status="ready"))
        invalidate_asset_cache(asset["id"])
        token = issue_asset_token(asset)
        from unittest.mock import Mock
        upstream = Mock(spec=["status", "headers", "read", "close"], status=206, headers={"Content-Range": "bytes 4-7/100", "Content-Length": "4", "Set-Cookie": "secret"})
        upstream.read.side_effect = [b"data", b""]
        link = QuarkDownloadLink("quark-file", "https://cdn.quark.cn/temp", {"Cookie": "secret", "User-Agent": "Quark", "Referer": "https://pan.quark.cn/"})
        with patch("app.services.playback.QuarkClient.download_link", return_value=link), patch(
            "app.services.playback.urllib.request.build_opener"
        ) as build_opener:
            build_opener.return_value.open.return_value = upstream
            response = TestClient(create_playback_app()).get(f"/api/play/{token}", headers={"Range": "bytes=4-7", "User-Agent": "Emby"}, follow_redirects=False)
        self.assertEqual(206, response.status_code)
        self.assertEqual(b"data", response.content)
        self.assertEqual("bytes 4-7/100", response.headers["content-range"])
        self.assertEqual("proxy", response.headers["x-mediaindex-playback-mode"])
        self.assertNotIn("location", response.headers)
        self.assertNotIn("set-cookie", response.headers)
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual("secret", request.get_header("Cookie"))
        self.assertEqual("Quark", request.get_header("User-agent"))
        self.assertEqual("https://pan.quark.cn/", request.get_header("Referer"))
        self.assertEqual("bytes=4-7", request.get_header("Range"))
        from app.clients.http import NoRedirectHandler
        self.assertIsInstance(build_opener.call_args.args[0], NoRedirectHandler)
        upstream.close.assert_called_once()

    def test_quark_412_refreshes_link_and_rotated_cookie_once(self):
        from unittest.mock import Mock
        asset = register_asset(AssetInput(provider="quark", file_id="quark-refresh", name="Movie.mkv", size=100, status="ready"))
        invalidate_asset_cache(asset["id"])
        token = issue_asset_token(asset)
        links = [QuarkDownloadLink("quark-refresh", "https://cdn.quark.cn/" + state, {"Cookie": state}) for state in ("stale", "fresh")]
        upstream = Mock(spec=["status", "headers", "read", "close"], status=206, headers={})
        upstream.read.side_effect = [b"data", b""]
        with patch("app.services.playback.QuarkClient.download_link", side_effect=links) as download, patch("app.services.playback.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = [urllib.error.HTTPError(links[0].url, 412, "Precondition Failed", {}, None), upstream]
            stream = open_playback_stream(token, "bytes=0-3")
            self.assertEqual(b"data", b"".join(stream.chunks))
        self.assertEqual(2, download.call_count)
        self.assertEqual("fresh", opener.return_value.open.call_args.args[0].get_header("Cookie"))

    def test_quark_head_returns_metadata_without_reading_video_or_proxying_to_emby(self):
        from unittest.mock import Mock
        asset = register_asset(AssetInput(provider="quark", file_id="quark-head", name="Movie.mp4", size=100, status="ready"))
        invalidate_asset_cache(asset["id"])
        token = issue_asset_token(asset)
        upstream = Mock(spec=["status", "headers", "read", "close"], status=200, headers={"Content-Type": "video/mp4", "Content-Length": "100", "Accept-Ranges": "bytes"})
        link = QuarkDownloadLink("quark-head", "https://cdn.quark.cn/temp", {"Cookie": "secret"})
        with patch("app.services.playback.QuarkClient.download_link", return_value=link), patch(
            "app.services.playback.urllib.request.build_opener"
        ) as opener, patch("app.playback_main.proxy_emby_http") as emby:
            opener.return_value.open.return_value = upstream
            response = TestClient(create_playback_app()).head(f"/api/play/{token}", follow_redirects=False)
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"", response.content)
        self.assertEqual("100", response.headers["content-length"])
        self.assertEqual("video/mp4", response.headers["content-type"])
        self.assertEqual("bytes", response.headers["accept-ranges"])
        self.assertEqual("HEAD", opener.return_value.open.call_args.args[0].method)
        upstream.read.assert_not_called()
        upstream.close.assert_called_once()
        emby.assert_not_called()

    def test_115_head_keeps_direct_redirect(self):
        token = issue_asset_token(self.asset)
        with patch("app.services.playback.P115Client.direct_download_link", return_value=P115DirectLink("https://cdn.115.com/temp")), patch("app.api.playback.open_playback_stream") as stream:
            response = TestClient(create_playback_app()).head(f"/api/play/{token}", follow_redirects=False)
        self.assertEqual(302, response.status_code)
        self.assertEqual("https://cdn.115.com/temp", response.headers["location"])
        self.assertEqual(b"", response.content)
        stream.assert_not_called()

    def test_stream_yields_available_bytes_without_waiting_for_full_buffer(self):
        from unittest.mock import Mock
        upstream = Mock()
        upstream.read1.side_effect = [b"small first chunk", b""]
        stream = _iter_upstream(upstream)
        self.assertEqual(b"small first chunk", next(stream))
        upstream.read.assert_not_called()
        stream.close()
        upstream.close.assert_called_once()

    def _segment_response(self, start, end, total, body):
        import io
        from unittest.mock import Mock
        response = Mock(spec=["status", "headers", "read1", "close"], status=206,
                        headers={"Content-Range": f"bytes {start}-{end}/{total}", "Content-Length": str(end - start + 1), "Content-Type": "video/mp4"})
        response.read1.side_effect = io.BytesIO(body).read1
        return response

    def _quark_segment_token(self):
        asset = register_asset(AssetInput(provider="quark", file_id="segments", name="Movie.mp4", size=10, status="ready"))
        invalidate_asset_cache(asset["id"])
        return issue_asset_token(asset)

    def test_quark_open_range_is_continuous_across_finite_upstream_ranges(self):
        token = self._quark_segment_token()
        responses = [self._segment_response(0, 3, 10, b"abcd"), self._segment_response(4, 7, 10, b"efgh"), self._segment_response(8, 9, 10, b"ij")]
        link = QuarkDownloadLink("segments", "https://cdn.quark.cn/temp", {"Cookie": "private"})
        with patch("app.services.playback._PLAYBACK_RANGE_BYTES", 4), patch("app.services.playback.QuarkClient.download_link", return_value=link), patch("app.services.playback.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = responses
            response = TestClient(create_playback_app()).get(f"/api/play/{token}", headers={"Range": "bytes=0-"})
        self.assertEqual(206, response.status_code)
        self.assertEqual("bytes 0-9/10", response.headers["content-range"])
        self.assertEqual("10", response.headers["content-length"])
        self.assertEqual(b"abcdefghij", response.content)
        self.assertEqual(["bytes=0-3", "bytes=4-7", "bytes=8-9"], [call.args[0].get_header("Range") for call in opener.return_value.open.call_args_list])
        self.assertNotIn("private", str(response.headers))
        for upstream in responses:
            upstream.close.assert_called_once()

    def test_quark_segmented_get_and_seek_keep_client_status_and_exact_bytes(self):
        for requested, start, expected_status, expected in [("", 0, 200, b"abcdefghij"), ("bytes=6-", 6, 206, b"ghij")]:
            with self.subTest(range=requested):
                token = self._quark_segment_token()
                body = b"abcdefghij"
                responses = [self._segment_response(pos, min(pos + 3, 9), 10, body[pos:pos + 4]) for pos in range(start, 10, 4)]
                link = QuarkDownloadLink("segments", "https://cdn.quark.cn/temp", {})
                with patch("app.services.playback._PLAYBACK_RANGE_BYTES", 4), patch("app.services.playback.QuarkClient.download_link", return_value=link), patch("app.services.playback.urllib.request.build_opener") as opener:
                    opener.return_value.open.side_effect = responses
                    stream = open_playback_stream(token, requested)
                    self.assertEqual(expected, b"".join(stream.chunks))
                self.assertEqual(expected_status, stream.status_code)
                self.assertEqual(str(len(expected)), stream.headers["Content-Length"])
                self.assertEqual(bool(requested), "Content-Range" in stream.headers)

    def test_quark_segment_refresh_does_not_duplicate_already_sent_bytes(self):
        token = self._quark_segment_token()
        stale = QuarkDownloadLink("segments", "https://cdn.quark.cn/stale", {"Cookie": "stale"})
        fresh = QuarkDownloadLink("segments", "https://cdn.quark.cn/fresh", {"Cookie": "fresh"})
        responses = [self._segment_response(0, 3, 10, b"abcd"), urllib.error.HTTPError(stale.url, 412, "expired", {}, None), self._segment_response(4, 7, 10, b"efgh"), self._segment_response(8, 9, 10, b"ij")]
        with patch("app.services.playback._PLAYBACK_RANGE_BYTES", 4), patch("app.services.playback.QuarkClient.download_link", side_effect=[stale, fresh]), patch("app.services.playback.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = responses
            self.assertEqual(b"abcdefghij", b"".join(open_playback_stream(token, "bytes=0-").chunks))
        calls = opener.return_value.open.call_args_list
        self.assertEqual(["bytes=0-3", "bytes=4-7", "bytes=4-7", "bytes=8-9"], [call.args[0].get_header("Range") for call in calls])
        self.assertEqual("fresh", calls[2].args[0].get_header("Cookie"))

    def test_quark_segment_rejects_wrong_offsets_changed_size_and_truncation(self):
        for second in [(5, 8, 10, b"fghi"), (4, 7, 11, b"efgh"), (4, 7, 10, b"ef")]:
            with self.subTest(segment=second):
                token = self._quark_segment_token()
                first = self._segment_response(0, 3, 10, b"abcd")
                invalid = self._segment_response(*second)
                with patch("app.services.playback._PLAYBACK_RANGE_BYTES", 4), patch("app.services.playback.QuarkClient.download_link", return_value=QuarkDownloadLink("segments", "https://cdn.quark.cn/temp", {})), patch("app.services.playback.urllib.request.build_opener") as opener:
                    opener.return_value.open.side_effect = [first, invalid]
                    chunks = open_playback_stream(token, "bytes=0-").chunks
                    self.assertEqual(b"abcd", next(chunks))
                    with self.assertRaises(PlaybackError):
                        b"".join(chunks)
                first.close.assert_called_once()
                invalid.close.assert_called_once()

    def test_quark_segment_cancellation_closes_current_response_without_prefetch(self):
        token = self._quark_segment_token()
        upstream = self._segment_response(0, 3, 10, b"abcd")
        with patch("app.services.playback._PLAYBACK_RANGE_BYTES", 4), patch("app.services.playback.QuarkClient.download_link", return_value=QuarkDownloadLink("segments", "https://cdn.quark.cn/temp", {})), patch("app.services.playback.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = upstream
            chunks = open_playback_stream(token, "bytes=0-").chunks
            self.assertEqual(b"abcd", next(chunks))
            chunks.close()
            opener.return_value.open.assert_called_once()
        upstream.close.assert_called_once()

    def test_quark_invalid_initial_segment_is_closed_before_sending_headers(self):
        token = self._quark_segment_token()
        upstream = self._segment_response(1, 4, 10, b"bcde")
        with patch("app.services.playback._PLAYBACK_RANGE_BYTES", 4), patch("app.services.playback.QuarkClient.download_link", return_value=QuarkDownloadLink("segments", "https://cdn.quark.cn/temp", {})), patch("app.services.playback.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = upstream
            with self.assertRaises(PlaybackError):
                open_playback_stream(token, "bytes=0-")
        upstream.close.assert_called_once()

    def test_playback_diagnostics_do_not_store_signed_token_or_link(self):
        token = issue_asset_token(self.asset)
        with patch("app.services.playback.P115Client.direct_download_link", return_value=P115DirectLink("https://cdn.115.com/private-link")):
            TestClient(create_playback_app()).get(f"/api/play/{token}", follow_redirects=False)
        events = [event for event in recent_diagnostic_events() if event["component"] == "playback"]
        self.assertEqual("302", events[-1]["status"])
        self.assertNotIn(token, str(events))
        self.assertNotIn("private-link", str(events))

    def test_dedicated_playback_app_keeps_playback_routes_ahead_of_emby_proxy(self):
        app = create_playback_app()
        self.assertEqual("/api/play/signed-token", app.url_path_for("play_asset", token="signed-token"))
        self.assertEqual("/health", app.url_path_for("health"))
        self.assertEqual("/web/index.html", app.url_path_for("proxy_emby_http", path="web/index.html"))
        with self.assertRaises(NoMatchFound):
            app.url_path_for("status")


if __name__ == "__main__":
    unittest.main()
