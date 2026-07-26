import unittest

from app.services.media_target import resolve_media_target
from app.clients.tmdb import collect_title_aliases, normalize_tmdb_details


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
        self.assertEqual(("中文名", "别名", "Original Name"), target.search_titles)
        self.assertEqual("2024", target.series_year)
        self.assertEqual("2026", target.season_year)
        self.assertEqual(2, len(target.episodes))
        self.assertIn("S03E01", target.episodes[0].match_tokens)

    def test_verified_resource_alias_is_added_without_changing_canonical_title(self):
        target = resolve_media_target(94997, "tv", 3, client=FakeTmdbClient())
        self.assertEqual("中文名", target.title)
        self.assertEqual("龙之家族", target.search_titles[1])

    def test_tmdb_aliases_are_returned_after_deduplication(self):
        aliases = collect_title_aliases(
            {
                "name": "航海王",
                "original_name": "ONE PIECE",
                "alternative_titles": {"results": [{"title": "海贼王"}]},
                "translations": {"translations": [{"data": {"name": "海贼王"}}, {"data": {"name": "航海王"}}]},
            }
        )

        self.assertEqual(["海贼王"], aliases)

    def test_verified_resource_title_is_used_for_display(self):
        detail = normalize_tmdb_details(
            {
                "id": 37854,
                "name": "航海王",
                "original_name": "ONE PIECE",
                "first_air_date": "1999-10-20",
                "alternative_titles": {"results": []},
                "translations": {"translations": []},
                "seasons": [],
            },
            "tv",
        )

        self.assertEqual("海贼王", detail["title"])


if __name__ == "__main__":
    unittest.main()
