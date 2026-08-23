import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

from app.api.emby import _library_cover_bytes, emby_dashboard, emby_item_image


class EmbyDashboardTests(unittest.TestCase):
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
        self.assertEqual("movie-1", result["libraries"][0]["cover_item_id"])
        self.assertTrue(result["sessions"][0]["is_playing"])
        self.assertEqual("测试电影", result["latest_items"][0]["name"])
        self.assertNotIn("api_key", str(result).lower())

    def test_image_proxy_rejects_path_like_item_id_before_network_access(self):
        with self.assertRaises(HTTPException) as context:
            emby_item_image("../secret")
        self.assertEqual(422, context.exception.status_code)

    def test_library_cover_generator_uses_library_posters_without_writing_emby(self):
        poster = io.BytesIO()
        Image.new("RGB", (240, 360), "#326a53").save(poster, format="JPEG")
        with patch("app.api.emby._read_emby_json", return_value={"Items": [{"Id": "movie1"}, {"Id": "movie2"}]}), patch("app.api.emby._read_emby_bytes", return_value=poster.getvalue()) as read_image:
            content = _library_cover_bytes("library1", title="Movies", style="collage")
        with Image.open(io.BytesIO(content)) as generated:
            self.assertEqual((960, 540), generated.size)
            self.assertEqual("JPEG", generated.format)
        self.assertEqual(2, read_image.call_count)

    def test_library_cover_rejects_path_like_library_id(self):
        with self.assertRaisesRegex(ValueError, "标识无效"):
            _library_cover_bytes("../library", title="Movies", style="minimal")


if __name__ == "__main__":
    unittest.main()
