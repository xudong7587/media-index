import os
import unittest
from unittest.mock import patch

from app.core.config import get_settings
from app.services.paths import build_save_path, is_allowed_save_path


class SavePathTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "CLOUD_SAVE_PATH": "/strm",
                "LOCAL_SAVE_PATH": "/下载_未整理",
                "CATEGORY_PATHS_JSON": '{"movie":"/movie","tv":"/tv","variety":"/tv"}',
                "DB_PATH": ":memory:",
            },
        )
        self.environment.start()
        get_settings.cache_clear()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()

    def test_variety_path_always_contains_target_root_and_category(self):
        self.assertEqual(
            "/strm/tv/音乐缘计划(2024)",
            build_save_path("cloud", "variety", "音乐缘计划", "2024"),
        )
        self.assertEqual(
            "/下载_未整理/tv/音乐缘计划(2024)",
            build_save_path("local", "variety", "音乐缘计划", "2024"),
        )

    def test_extended_tmdb_category_uses_its_own_folder(self):
        self.assertEqual(
            "/strm/05演唱会/测试演唱会(2026)",
            build_save_path("cloud", "concert", "测试演唱会", "2026"),
        )

    def test_category_path_cannot_be_used_as_final_save_root(self):
        self.assertFalse(is_allowed_save_path("variety", "/tv/音乐缘计划 (2024)"))
        self.assertTrue(is_allowed_save_path("variety", "/strm/tv/音乐缘计划 (2024)"))
        self.assertTrue(is_allowed_save_path("variety", "/下载_未整理/tv/音乐缘计划 (2024)"))
        self.assertFalse(is_allowed_save_path("variety", "/下载_未整理/tv/音乐缘计划 (2024)", target="cloud"))

    def test_unknown_target_is_rejected(self):
        with self.assertRaises(ValueError):
            build_save_path("other", "variety", "音乐缘计划", "2024")

    def test_cloud_provider_roots_and_categories_are_independent(self):
        with patch.dict(
            os.environ,
            {
                "QAS_SAVE_PATH": "/QuarkMedia",
                "QAS_CATEGORY_PATHS_JSON": '{"movie":"/电影"}',
                "P115_ROOT_PATH": "/115Media",
                "P115_LOCAL_PATH": "/mnt/115-downloads",
                "P115_CATEGORY_PATHS_JSON": '{"movie":"/影片"}',
            },
        ):
            get_settings.cache_clear()
            self.assertEqual("/QuarkMedia/电影/群体(2026)", build_save_path("cloud", "movie", "群体", "2026", provider="qas"))
            self.assertEqual("/115Media/影片/群体(2026)", build_save_path("cloud", "movie", "群体", "2026", provider="p115"))
            self.assertEqual("/mnt/115-downloads/影片/群体(2026)", build_save_path("local", "movie", "群体", "2026", provider="p115"))
            self.assertTrue(
                is_allowed_save_path(
                    "movie",
                    "/mnt/115-downloads/影片/群体(2026)",
                    target="local",
                    provider="p115",
                )
            )

    def test_empty_provider_category_removes_default_row(self):
        with patch.dict(os.environ, {"QAS_CATEGORY_PATHS_JSON": '{"concert":""}'}):
            get_settings.cache_clear()
            self.assertNotIn("concert", get_settings().provider_category_paths("qas"))


if __name__ == "__main__":
    unittest.main()
