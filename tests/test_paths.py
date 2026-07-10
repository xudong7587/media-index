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
            "/strm/tv/音乐缘计划 (2024)",
            build_save_path("cloud", "variety", "音乐缘计划", "2024"),
        )
        self.assertEqual(
            "/下载_未整理/tv/音乐缘计划 (2024)",
            build_save_path("local", "variety", "音乐缘计划", "2024"),
        )

    def test_category_path_cannot_be_used_as_final_save_root(self):
        self.assertFalse(is_allowed_save_path("variety", "/tv/音乐缘计划 (2024)"))
        self.assertTrue(is_allowed_save_path("variety", "/strm/tv/音乐缘计划 (2024)"))
        self.assertTrue(is_allowed_save_path("variety", "/下载_未整理/tv/音乐缘计划 (2024)"))
        self.assertFalse(is_allowed_save_path("variety", "/下载_未整理/tv/音乐缘计划 (2024)", target="cloud"))

    def test_unknown_target_is_rejected(self):
        with self.assertRaises(ValueError):
            build_save_path("other", "variety", "音乐缘计划", "2024")


if __name__ == "__main__":
    unittest.main()
