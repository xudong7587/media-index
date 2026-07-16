import io
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.services.poster_cache import cache_tmdb_poster, find_cached_poster


class FakePosterResponse:
    def __init__(self, body: bytes, content_type: str = "image/jpeg"):
        self.body = io.BytesIO(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, size=-1):
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class PosterCacheTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {"CACHE_DIR": str(Path(self.tempdir.name) / "cache")},
        )
        self.environment.start()
        get_settings.cache_clear()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    @patch("app.services.poster_cache.open_url")
    def test_tmdb_poster_is_downloaded_once_and_reused(self, open_url):
        open_url.return_value = FakePosterResponse(b"\xff\xd8\xffposter")
        source = "https://image.tmdb.org/t/p/w342/test.jpg"

        first = cache_tmdb_poster(source)
        second = cache_tmdb_poster(source)

        self.assertEqual(first, second)
        self.assertTrue(find_cached_poster(first).is_file())
        open_url.assert_called_once()

    @patch("app.services.poster_cache.open_url")
    def test_non_tmdb_url_is_never_downloaded(self, open_url):
        self.assertEqual("", cache_tmdb_poster("https://example.com/poster.jpg"))
        open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
