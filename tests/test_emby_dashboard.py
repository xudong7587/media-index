import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image, ImageFont

from app.api.emby import _library_cover_bytes, apply_emby_library_cover, emby_dashboard, emby_item_image, emby_libraries, refresh_emby_library_covers
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.emby_library_covers import _font_paths, list_cover_fonts, normalise_cover_options, refresh_all_library_covers, save_cover_font
from app.services.emby_library_covers import apply_library_cover as service_apply_library_cover


class EmbyDashboardTests(unittest.TestCase):
    @patch("app.api.emby.run_cover_activity", side_effect=lambda _title, operation: operation())
    @patch("app.api.emby.apply_library_cover")
    def test_apply_cover_delegates_to_the_verified_cover_service(self, apply_cover, _activity):
        payload = type("Payload", (), {"title": "电影", "style": "collage", "options": {"resolution": "720p"}})()

        result = apply_emby_library_cover("library-1", payload)

        apply_cover.assert_called_once_with("library-1", title="电影", style="collage", options={"resolution": "720p"})
        self.assertTrue(result["ok"])

    @patch("app.api.emby.apply_library_cover")
    def test_apply_cover_is_recorded_in_the_activity_log(self, apply_cover):
        payload = type("Payload", (), {"title": "电影", "style": "collage", "options": {"resolution": "720p"}})()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            with patch.dict(os.environ, {"DB_PATH": str(Path(temporary) / "cover-activity.db")}, clear=False):
                get_settings.cache_clear()
                init_db()

                result = apply_emby_library_cover("library-1", payload)
                with db() as conn:
                    row = conn.execute(
                        "SELECT provider,status,stage,message,display_title,request_source FROM transfer_jobs ORDER BY id DESC LIMIT 1"
                    ).fetchone()

        get_settings.cache_clear()
        self.assertTrue(result["ok"])
        self.assertEqual(
            ("emby", "done", "cover_completed", "媒体库封面已生成并写入 Emby", "电影 · 封面生成", "web"),
            tuple(row),
        )

    @patch("app.api.emby.refresh_all_library_covers", return_value={"updated": 2, "failed": 1, "results": []})
    def test_batch_cover_partial_failure_is_visible_in_the_activity_log(self, _refresh):
        payload = type("Payload", (), {
            "style": "showcase",
            "options": {"resolution": "1080p"},
            "library_options": {},
            "library_ids": [],
        })()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            with patch.dict(os.environ, {"DB_PATH": str(Path(temporary) / "cover-batch-activity.db")}, clear=False):
                get_settings.cache_clear()
                init_db()

                result = refresh_emby_library_covers(payload)
                with db() as conn:
                    row = conn.execute(
                        "SELECT provider,status,stage,message,display_title,request_source FROM transfer_jobs ORDER BY id DESC LIMIT 1"
                    ).fetchone()

        get_settings.cache_clear()
        self.assertFalse(result["ok"])
        self.assertEqual(
            ("emby", "failed", "cover_failed", "封面生成完成：已更新 2 个媒体库，失败 1 个", "批量生成媒体库封面", "web"),
            tuple(row),
        )

    @patch("app.services.emby_library_covers.open_url")
    @patch("app.services.emby_library_covers._credentials", return_value=("http://emby", "key"))
    @patch("app.services.emby_library_covers.library_cover_bytes", return_value=b"jpeg-body")
    def test_cover_upload_uses_base64_body_expected_by_emby(self, _cover, _credentials, opened):
        opened.return_value.__enter__.return_value.read.return_value = b""

        service_apply_library_cover("library-1", title="电影", style="collage")

        request = opened.call_args.args[0]
        self.assertEqual(base64.b64encode(b"jpeg-body"), request.data)
        self.assertEqual("image/jpeg", request.headers["Content-type"])

    def test_library_selector_returns_names_without_loading_items(self):
        with patch("app.api.emby._read_emby_json", return_value=[
            {"ItemId": "library-1", "Name": "电影", "CollectionType": "movies", "Locations": ["/strm/01电影"]},
            {"ItemId": "", "Name": "无标识"},
        ]) as read:
            result = emby_libraries()

        self.assertEqual([{"id": "library-1", "name": "电影", "collection_type": "movies", "locations": ["/strm/01电影"]}], result["libraries"])
        read.assert_called_once_with("/Library/VirtualFolders")

    def test_dashboard_combines_server_libraries_sessions_and_latest_items(self):
        def read(path, *, query=None):
            if path == "/System/Info":
                return {"ServerName": "Living Room", "Version": "4.9.1", "OperatingSystemDisplayName": "Linux"}
            if path == "/Items/Counts":
                return {"MovieCount": 12, "SeriesCount": 3, "EpisodeCount": 48}
            if path == "/Sessions":
                return [{"Id": "session-1", "UserId": "user-1", "UserName": "Sunny", "DeviceName": "TV", "NowPlayingItem": {"Id": "movie-1", "Name": "测试电影"}}]
            if path == "/Library/VirtualFolders":
                return [{"ItemId": "library-1", "Name": "电影", "CollectionType": "movies"}]
            if path == "/Items" and query and query.get("ParentId") == "library-1":
                return {"Items": [{"Id": "movie-1", "ImageTags": {"Primary": "tag-1"}}]}
            if path == "/Items":
                return {"Items": [{"Id": "movie-1", "Name": "测试电影", "Type": "Movie", "ProductionYear": 2026, "CommunityRating": 8.1, "ImageTags": {"Primary": "tag-1"}}]}
            raise AssertionError(path)

        with patch("app.api.emby._read_emby_json", side_effect=read):
            result = emby_dashboard()

        self.assertEqual("Living Room", result["server"]["name"])
        self.assertEqual(12, result["counts"]["MovieCount"])
        self.assertEqual("library-1", result["libraries"][0]["cover_item_id"])
        self.assertTrue(result["sessions"][0]["is_playing"])
        self.assertEqual("测试电影", result["latest_items"][0]["name"])
        self.assertNotIn("api_key", str(result).lower())

    def test_image_proxy_rejects_path_like_item_id_before_network_access(self):
        with self.assertRaises(HTTPException) as context:
            emby_item_image("../secret")
        self.assertEqual(422, context.exception.status_code)

    @patch("app.api.emby.open_url")
    @patch("app.api.emby._emby_credentials", return_value=("http://emby", "key"))
    def test_image_proxy_revalidates_replaced_library_covers(self, _credentials, opened):
        upstream = opened.return_value.__enter__.return_value
        upstream.headers = {"Content-Type": "image/jpeg"}
        upstream.read.return_value = b"jpeg-body"

        response = emby_item_image("library-1")

        self.assertEqual("private, no-cache, must-revalidate", response.headers["cache-control"])

    def test_library_cover_generator_uses_upstream_static_templates_with_library_posters(self):
        poster = io.BytesIO()
        Image.new("RGB", (240, 360), "#326a53").save(poster, format="JPEG")
        image = Image.open(io.BytesIO(poster.getvalue())).copy()
        with patch("app.services.emby_library_covers._read_json", return_value={"Items": [{"Id": "movie1"}, {"Id": "movie2"}]}), patch("app.services.emby_library_covers._read_item_image", return_value=image) as read_image:
            for style in ("collage", "showcase", "mosaic", "minimal"):
                content = _library_cover_bytes(
                    "library1",
                    title="Movies",
                    style=style,
                    options={
                        "zh_title": "影视",
                        "en_title": "DOCUMENTARY SERIES COLLECTION",
                        "title_x_offset": 120,
                        "zh_font_offset": 30,
                        "en_line_spacing": 64,
                    },
                )
                with Image.open(io.BytesIO(content)) as generated:
                    self.assertEqual((1920, 1080), generated.size)
                    self.assertEqual("JPEG", generated.format)
        # The multi-poster static template uses both images; the other three
        # use one poster each.
        self.assertEqual(5, read_image.call_count)

    def test_cover_generator_rejects_library_without_posters(self):
        with patch("app.services.emby_library_covers._read_json", return_value={"Items": []}):
            with self.assertRaisesRegex(ValueError, "海报"):
                _library_cover_bytes("library1", title="Movies", style="minimal")

    def test_cover_generator_applies_static_resolution_and_title_options(self):
        image = Image.new("RGB", (240, 360), "#326a53")
        with patch("app.services.emby_library_covers._read_json", return_value={"Items": [{"Id": "movie1"}]}), patch("app.services.emby_library_covers._read_item_image", return_value=image):
            content = _library_cover_bytes(
                "library1",
                title="Movies",
                style="minimal",
                options={"resolution": "720p", "zh_title": "电影", "en_title": "MOVIES", "bg_color_mode": "custom", "custom_bg_color": "#2f6f57"},
            )
        with Image.open(io.BytesIO(content)) as generated:
            self.assertEqual((1280, 720), generated.size)

    def test_cover_generator_normalises_static_title_scale_and_showcase_background(self):
        options = normalise_cover_options({"title_scale": 9, "showcase_blur": False, "title_x_offset": 9999})

        self.assertEqual(2.0, options["title_scale"])
        self.assertFalse(options["showcase_blur"])
        self.assertEqual(500, options["title_x_offset"])

    def test_uploaded_cover_font_can_be_selected_independently_for_chinese_and_english(self):
        chinese_font = Path(str(ImageFont.truetype("DejaVuSans-Bold.ttf", 24).path))
        english_font = Path(str(ImageFont.truetype("DejaVuSans.ttf", 24).path))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CACHE_DIR": str(Path(directory) / "cache")}, clear=False):
            get_settings.cache_clear()
            uploaded_chinese = save_cover_font("Custom-Chinese.ttf", chinese_font.read_bytes())
            uploaded_english = save_cover_font("Custom-English.ttf", english_font.read_bytes())
            fonts = list_cover_fonts()
            chinese, english = _font_paths({
                "zh_font_id": uploaded_chinese["id"],
                "en_font_id": uploaded_english["id"],
            })
            selected_chinese_bytes = Path(chinese).read_bytes()
            selected_english_bytes = Path(english).read_bytes()

        get_settings.cache_clear()
        self.assertTrue(any(font["id"] == uploaded_chinese["id"] and font["source"] == "uploaded" for font in fonts))
        self.assertTrue(any(font["id"] == uploaded_english["id"] and font["source"] == "uploaded" for font in fonts))
        self.assertNotEqual(chinese, english)
        self.assertEqual(chinese_font.read_bytes(), selected_chinese_bytes)
        self.assertEqual(english_font.read_bytes(), selected_english_bytes)

    def test_cover_font_upload_rejects_non_font_payload(self):
        with self.assertRaisesRegex(ValueError, "格式无效"):
            save_cover_font("broken.ttf", b"not-a-font")

    @patch("app.services.emby_library_covers.apply_library_cover")
    @patch("app.services.emby_library_covers._read_json")
    def test_batch_cover_respects_selected_libraries_and_per_library_titles(self, read_json, apply_cover):
        read_json.return_value = [
            {"ItemId": "library-1", "Name": "电影"},
            {"ItemId": "library-2", "Name": "剧集"},
        ]

        result = refresh_all_library_covers(
            "minimal",
            {"resolution": "1080p"},
            library_ids=["library-2"],
            library_options={"library-2": {"zh_title": "连续剧", "en_title": "SERIES"}},
        )

        self.assertEqual(1, result["updated"])
        apply_cover.assert_called_once()
        self.assertEqual("library-2", apply_cover.call_args.args[0])
        self.assertEqual("连续剧", apply_cover.call_args.kwargs["options"]["zh_title"])

    @patch("app.services.emby_library_covers.apply_library_cover")
    @patch("app.services.emby_library_covers._read_json")
    def test_batch_cover_uses_shared_typography_with_per_library_titles(self, read_json, apply_cover):
        read_json.return_value = [{"ItemId": "library-1", "Name": "电影"}]

        refresh_all_library_covers(
            "minimal",
            {"zh_font_size": 222, "title_x_offset": 44},
            library_options={"library-1": {"zh_title": "影片", "zh_font_size": 88, "title_x_offset": -90}},
        )

        options = apply_cover.call_args.kwargs["options"]
        self.assertEqual("影片", options["zh_title"])
        self.assertEqual(222, options["zh_font_size"])
        self.assertEqual(44, options["title_x_offset"])

    def test_library_cover_rejects_path_like_library_id(self):
        with self.assertRaisesRegex(ValueError, "标识无效"):
            _library_cover_bytes("../library", title="Movies", style="minimal")


if __name__ == "__main__":
    unittest.main()
