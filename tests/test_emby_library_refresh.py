import os
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
            message = refresh_emby_library_after_strm()

        request = open_url.call_args.args[0]
        self.assertEqual("POST", request.get_method())
        self.assertIn("/Library/Refresh?LibraryId=library-1", request.full_url)
        self.assertIn("已通知 Emby 刷新", message)
