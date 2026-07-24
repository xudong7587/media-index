import unittest
from types import SimpleNamespace

from app.clients.tmdb import TmdbClient, discovery_media_type


class FakeTmdbClient(TmdbClient):
    def __init__(self):
        self.settings = SimpleNamespace(tmdb_discover_cache_ttl_seconds=60)
        self.calls = []

    def _cached_get(self, path, params=None, ttl_seconds=3600):
        self.calls.append((path, params or {}, ttl_seconds))
        return {"results": [], "page": 1, "total_pages": 1}


class TmdbCategoryTests(unittest.TestCase):
    def test_discovery_category_maps_to_real_tmdb_media_type(self):
        self.assertEqual("movie", discovery_media_type("concert"))
        self.assertEqual("movie", discovery_media_type("documentary"))
        self.assertEqual("tv", discovery_media_type("anime"))

    def test_concert_uses_movie_music_genre(self):
        client = FakeTmdbClient()
        client.discover("concert")
        path, params, _ = client.calls[-1]
        self.assertEqual("/discover/movie", path)
        self.assertEqual("10402", params["with_genres"])

    def test_anime_uses_tv_animation_and_japanese_language(self):
        client = FakeTmdbClient()
        client.discover("anime")
        path, params, _ = client.calls[-1]
        self.assertEqual("/discover/tv", path)
        self.assertEqual("16", params["with_genres"])
        self.assertEqual("ja", params["with_original_language"])


if __name__ == "__main__":
    unittest.main()
