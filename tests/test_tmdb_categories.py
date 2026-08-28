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


class FakeContextSearchTmdbClient(TmdbClient):
    def __init__(self):
        self.settings = SimpleNamespace(tmdb_api_key="key", tmdb_adult_content_enabled=False)

    def _get(self, path, params=None):
        query = str((params or {}).get("query") or "")
        if path == "/search/movie" and query == "1942":
            return {"results": [
                {"id": 1, "title": "一九四二", "release_date": "2012-11-29", "popularity": 15},
                {"id": 2, "title": "1942", "release_date": "2005-01-01", "popularity": 20},
            ]}
        if path == "/search/person" and query == "冯小刚":
            return {"results": [{"id": 99, "name": "冯小刚"}]}
        if path == "/person/99/combined_credits":
            return {"cast": [], "crew": [
                {"id": 1, "media_type": "movie", "title": "一九四二", "release_date": "2012-11-29", "job": "Director"},
                {"id": 3, "media_type": "movie", "title": "芳华", "release_date": "2017-12-15", "job": "Director"},
            ]}
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

    def test_contextual_search_intersects_title_with_person_credits(self):
        results = FakeContextSearchTmdbClient().search("1942 冯小刚", "all")["results"]
        self.assertEqual([1], [item["tmdb_id"] for item in results])

    def test_rating_and_latest_require_public_metadata(self):
        client = FakeTmdbClient()
        client._cached_get = lambda *_args, **_kwargs: {"results": [
            {"id": 1, "title": "可信作品", "poster_path": "/poster.jpg", "release_date": "2026-01-01", "vote_count": 201},
            {"id": 2, "title": "无海报", "poster_path": None, "release_date": "2026-01-01", "vote_count": 500},
            {"id": 3, "title": "无日期", "poster_path": "/poster.jpg", "release_date": "", "vote_count": 500},
            {"id": 4, "title": "样本太少", "poster_path": "/poster.jpg", "release_date": "2026-01-01", "vote_count": 199},
        ], "page": 1, "total_pages": 1}
        self.assertEqual([1], [item["id"] for item in client.discover("movie", sort="rating")["results"]])
        self.assertEqual([1, 4], [item["id"] for item in client.discover("movie", sort="latest")["results"]])


if __name__ == "__main__":
    unittest.main()
