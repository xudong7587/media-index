import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import init_db
from app.domain.media import MediaTarget
from app.services.channel_monitor import search_channel_resources, upsert_channel_subscription
from app.services.channel_source_poller import _TelegramPublicPageParser, pull_public_channel


class TelegramPublicPageParserTests(unittest.TestCase):
    def test_extracts_recent_public_post_text_links_and_timestamp(self):
        parser = _TelegramPublicPageParser("movie_channel")
        parser.feed("""
        <div class="tgme_widget_message_wrap">
          <div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="movie_channel/42">
            <div class="tgme_widget_message_text js-message_text">测试电影 2026 4K
              <a href="https://pan.quark.cn/s/public42">夸克链接</a>
            </div>
            <a class="tgme_widget_message_date" href="https://t.me/movie_channel/42"><time datetime="2026-08-20T08:00:00+00:00">08:00</time></a>
          </div>
        </div>
        """)

        self.assertEqual(1, len(parser.posts))
        self.assertEqual(42, parser.posts[0]["message_id"])
        self.assertIn("https://pan.quark.cn/s/public42", parser.posts[0]["text"])
        self.assertEqual("2026-08-20T08:00:00+00:00", parser.posts[0]["date"])

    def test_public_pull_indexes_candidates_for_global_media_search(self):
        page = b"""
        <div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="movie_channel/43">
          <div class="tgme_widget_message_text js-message_text">Global Movie 2026 4K
            <a href="https://115.com/s/public43?password=abcd">115</a>
          </div>
          <a class="tgme_widget_message_date" href="https://t.me/movie_channel/43"><time datetime="2026-08-20T09:00:00+00:00">09:00</time></a>
        </div>
        """

        class Response(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
            with patch.dict(os.environ, {"DB_PATH": str(Path(tempdir) / "test.db")}):
                get_settings.cache_clear()
                init_db()
                upsert_channel_subscription("https://t.me/movie_channel", display_name="Movie Source")
                with patch("app.services.channel_source_poller.open_url", return_value=Response(page)):
                    result = pull_public_channel("@movie_channel", "Movie Source")
                with patch("app.services.channel_source_poller.sync_public_channels"):
                    candidates = search_channel_resources(MediaTarget(43, "movie", "Global Movie", series_year="2026"))
                get_settings.cache_clear()

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["resources"])
        self.assertEqual("p115", candidates[0]["provider"])
        self.assertEqual("telegram:Movie Source", candidates[0]["source"])

    def test_global_media_search_refreshes_public_channels_on_demand(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
            with patch.dict(os.environ, {"DB_PATH": str(Path(tempdir) / "test.db")}):
                get_settings.cache_clear()
                init_db()
                with patch("app.services.channel_source_poller.sync_public_channels") as sync:
                    search_channel_resources(MediaTarget(44, "movie", "On Demand Movie", series_year="2026"))
                get_settings.cache_clear()

        sync.assert_called_once_with()
