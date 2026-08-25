import unittest
from types import SimpleNamespace

from app.clients.tmdb import TmdbClient, discovery_media_type


class FakeTmdbClient(TmdbClient):
    def __init__(self):
        self.settings = SimpleNamespace(tmdb_discover_cache_ttl_seconds=60, tmdb_adult_content_enabled=False)
        self.calls = []

    def _cached_get(self, path, params=None, ttl_seconds=3600, refresh=False):
        self.calls.append((path, params or {}, ttl_seconds, refresh))
        return {"results": [], "page": 1, "total_pages": 1}


class FakeSearchTmdbClient(TmdbClient):
    def __init__(self):
        self.settings = SimpleNamespace(tmdb_api_key="key", tmdb_adult_content_enabled=False)

    def _get(self, path, params=None):
        if path == "/search/movie":
            return {
                "results": [
                    {"id": 1, "title": "蜘蛛侠：英雄无归", "release_date": "2021-12-15"},
                    {"id": 2, "title": "蜘蛛侠：英雄无归的幕后特辑", "release_date": "2022-05-03"},
                    {"id": 3, "title": "蜘蛛侠：英雄无归", "release_date": "2021-12-15", "adult": True},
                ]
            }
        return {"results": []}


class TmdbCategoryTests(unittest.TestCase):
    def test_discovery_category_maps_to_real_tmdb_media_type(self):
        self.assertEqual("movie", discovery_media_type("concert"))
        self.assertEqual("movie", discovery_media_type("documentary"))
        self.assertEqual("tv", discovery_media_type("anime"))

    def test_concert_uses_movie_music_genre(self):
        client = FakeTmdbClient()
        client.discover("concert")
        path, params, *_ = client.calls[-1]
        self.assertEqual("/discover/movie", path)
        self.assertEqual("10402", params["with_genres"])

    def test_anime_uses_tv_animation_and_japanese_language(self):
        client = FakeTmdbClient()
        client.discover("anime")
        path, params, *_ = client.calls[-1]
        self.assertEqual("/discover/tv", path)
        self.assertEqual("16", params["with_genres"])
        self.assertEqual("ja", params["with_original_language"])

    def test_plain_search_filters_derivative_titles(self):
        results = FakeSearchTmdbClient().search("蜘蛛侠：英雄无归", "all")["results"]
        self.assertEqual([1], [item["tmdb_id"] for item in results])

    def test_search_hides_tmdb_adult_results_by_default(self):
        results = FakeSearchTmdbClient().search("蜘蛛侠：英雄无归", "movie")["results"]
        self.assertEqual([1, 2], [item["tmdb_id"] for item in results])


if __name__ == "__main__":
    unittest.main()
