import os
import json
import unittest
from unittest.mock import MagicMock, patch

from app.core.config import get_settings
from app.services.emby_library_refresh import refresh_emby_library_after_strm


class EmbyLibraryRefreshTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def test_refresh_is_disabled_by_default(self):
        with patch.dict(os.environ, {"EMBY_LIBRARY_REFRESH_ENABLED": "false"}, clear=False):
            get_settings.cache_clear()
            self.assertEqual("", refresh_emby_library_after_strm())

    def test_refresh_calls_only_the_configured_library(self):
        response = MagicMock()
        response.__enter__.return_value = response
        with patch.dict(os.environ, {
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "EMBY_BASE_URL": "http://emby.local:8096",
            "EMBY_API_KEY": "secret",
            "EMBY_LIBRARY_ID": "library-1",
        }, clear=False), patch("app.services.emby_library_refresh.open_url", return_value=response) as open_url:
            get_settings.cache_clear()
            message = refresh_emby_library_after_strm("/strm/Movies/New")

        self.assertEqual(1, open_url.call_count)
        request = open_url.call_args.args[0]
        self.assertEqual("POST", request.get_method())
        self.assertIn("/Library/Refresh?LibraryId=library-1", request.full_url)
        self.assertIn("Emby", message)

    def test_refresh_auto_discovers_the_only_library(self):
        discovery = MagicMock()
        discovery.__enter__.return_value = discovery
        discovery.read.return_value = json.dumps([{"ItemId": "only-library", "Name": "STRM"}]).encode()
        refresh = MagicMock()
        refresh.__enter__.return_value = refresh
        with patch.dict(os.environ, {
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "EMBY_BASE_URL": "http://emby.local:8096",
            "EMBY_API_KEY": "secret",
            "EMBY_LIBRARY_ID": "",
        }, clear=False), patch("app.services.emby_library_refresh.open_url", side_effect=[discovery, refresh]) as open_url:
            get_settings.cache_clear()
            message = refresh_emby_library_after_strm()

        self.assertEqual("GET", open_url.call_args_list[0].args[0].get_method())
        self.assertIn("/Library/VirtualFolders", open_url.call_args_list[0].args[0].full_url)
        self.assertIn("LibraryId=only-library", open_url.call_args_list[1].args[0].full_url)
        self.assertIn("Emby", message)

    def test_refresh_requires_selection_when_multiple_libraries_exist(self):
        discovery = MagicMock()
        discovery.__enter__.return_value = discovery
        discovery.read.return_value = json.dumps([{"ItemId": "movies"}, {"ItemId": "shows"}]).encode()
        with patch.dict(os.environ, {
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "EMBY_BASE_URL": "http://emby.local:8096",
            "EMBY_API_KEY": "secret",
            "EMBY_LIBRARY_ID": "",
        }, clear=False), patch("app.services.emby_library_refresh.open_url", return_value=discovery) as open_url:
            get_settings.cache_clear()
            message = refresh_emby_library_after_strm()

        self.assertEqual(1, open_url.call_count)
        self.assertIn("未匹配到", message)

    def test_refresh_selects_library_by_longest_output_path_match(self):
        discovery = MagicMock()
        discovery.__enter__.return_value = discovery
        discovery.read.return_value = json.dumps([
            {"ItemId": "all", "Locations": ["/strm"]},
            {"ItemId": "movies", "Locations": ["/strm/01电影"]},
            {"ItemId": "shows", "Locations": ["/strm/03电视剧"]},
        ]).encode()
        refresh = MagicMock()
        refresh.__enter__.return_value = refresh
        with patch.dict(os.environ, {
            "EMBY_LIBRARY_REFRESH_ENABLED": "true",
            "EMBY_BASE_URL": "http://emby.local:8096",
            "EMBY_API_KEY": "secret",
            "EMBY_LIBRARY_ID": "",
        }, clear=False), patch("app.services.emby_library_refresh.open_url", side_effect=[discovery, refresh]) as open_url:
            get_settings.cache_clear()
            message = refresh_emby_library_after_strm("/strm/01电影/新片")

        self.assertIn("LibraryId=movies", open_url.call_args_list[1].args[0].full_url)
        self.assertIn("对应 Emby 媒体库", message)
