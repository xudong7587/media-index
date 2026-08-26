import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.clients.p115 import P115Error
from app.core.config import get_settings
from app.services.strm_interaction import list_strm_root_directories, validate_strm_direct_child


class StrmInteractionTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    @patch("app.services.strm_interaction.QuarkClient")
    @patch("app.services.strm_interaction.P115Client")
    def test_provider_failure_does_not_hide_other_provider_directories(self, p115_client, quark_client):
        p115_client.return_value.directory_id.side_effect = P115Error("115 暂时不可用")
        quark_client.return_value.directory_id.return_value = "quark-root"
        quark_client.return_value.list_directory.return_value = (
            SimpleNamespace(name="剧集", is_dir=True),
            SimpleNamespace(name="电影", is_dir=True),
            SimpleNamespace(name="readme.txt", is_dir=False),
        )
        with patch.dict(os.environ, {
            "P115_STRM_ENABLED": "true",
            "QUARK_STRM_ENABLED": "true",
            "P115_STRM_SOURCE_ROOT": "/115",
            "QUARK_STRM_SOURCE_ROOT": "/夸克",
            "STRM_OUTPUT_ROOT": "/strm-output",
        }, clear=False):
            get_settings.cache_clear()
            directories, failures = list_strm_root_directories()

        self.assertCountEqual(["/夸克/电影", "/夸克/剧集"], [item.path for item in directories])
        self.assertEqual([("p115", "115 暂时不可用")], [(item.provider, item.message) for item in failures])

    def test_direct_child_validation_rejects_traversal_and_nested_paths(self):
        self.assertEqual(("/媒体库", "/媒体库/剧集"), validate_strm_direct_child("/媒体库/", "/媒体库/剧集"))
        for invalid in ("/媒体库/剧集/Season 1", "/其他/剧集", "/媒体库/../其他"):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                validate_strm_direct_child("/媒体库", invalid)


if __name__ == "__main__":
    unittest.main()
