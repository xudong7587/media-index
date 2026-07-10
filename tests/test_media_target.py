import unittest

from app.services.media_target import resolve_media_target


class FakeTmdbClient:
    def details(self, media_type: str, tmdb_id: int):
        return {
            "title": "中文名",
            "original_title": "Original Name",
            "aliases": ["别名", "中文名"],
            "year": "2024",
            "status": "Returning Series",
        }

    def season(self, tmdb_id: int, season_number: int):
        return {
            "air_date": "2026-07-01",
            "episodes": [
                {"episode_number": 1, "air_date": "2026-07-01", "name": "第1期上：开场"},
                {"episode_number": 2, "air_date": "2026-07-08", "name": "第1期中：对谈"},
            ],
        }


class MediaTargetTests(unittest.TestCase):
    def test_backend_resolves_canonical_target(self):
        target = resolve_media_target(123, "variety", 3, client=FakeTmdbClient())
        self.assertEqual(("中文名", "Original Name", "别名"), target.search_titles)
        self.assertEqual("2024", target.series_year)
        self.assertEqual("2026", target.season_year)
        self.assertEqual(2, len(target.episodes))
        self.assertIn("S03E01", target.episodes[0].match_tokens)


if __name__ == "__main__":
    unittest.main()
