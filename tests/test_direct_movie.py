import unittest

from app.domain.media import SourceFile
from app.services.direct_movie import parse_standard_movie_identity, resolve_direct_movie_source
from app.services.share_inspector import ShareInspection


class FakeInspector:
    def __init__(self, inspection):
        self.inspection = inspection
        self.urls = []

    def inspect_share(self, url):
        self.urls.append(url)
        return self.inspection


class DirectMovieTests(unittest.TestCase):
    def test_standard_identity_requires_title_and_year(self):
        identity = parse_standard_movie_identity(
            "Spider-Man.No.Way.Home.2021.2160p.WEB-DL",
            "Spider-Man: No Way Home",
        )
        self.assertEqual(("Spider Man No Way Home", "2021"), (identity.title, identity.year))

    def test_derivative_and_episode_results_do_not_bypass_tmdb(self):
        self.assertIsNone(parse_standard_movie_identity("Spider-Man幕后特辑.2022.1080p", "Spider-Man"))
        self.assertIsNone(parse_standard_movie_identity("Test Series.2026.S01E01.1080p", "Test Series"))
        self.assertIsNone(parse_standard_movie_identity("综艺节目.2026.1080p", "综艺节目"))
        self.assertIsNone(parse_standard_movie_identity("节目.2026.1080p", "节目 第1期"))

    def test_verified_pansou_movie_returns_direct_resolution(self):
        inspector = FakeInspector(
            ShareInspection(
                True,
                "https://pan.quark.cn/s/movie",
                (SourceFile("Spider-Man.No.Way.Home.2021.2160p.WEB-DL.mkv", 8_000_000_000),),
            )
        )
        result = resolve_direct_movie_source(
            "Spider-Man: No Way Home",
            [
                {
                    "share_url": "https://pan.quark.cn/s/movie",
                    "title": "Spider-Man No Way Home 2021 2160P",
                    "cloud_type": "quark",
                    "provider": "qas",
                }
            ],
            inspector,
            provider_key="qas",
        )
        self.assertIsNotNone(result)
        self.assertEqual("2021", result.identity.year)
        self.assertEqual("Spider Man No Way Home.2021.mkv", result.resolution.rename_pairs[0].replacement)
        self.assertEqual(["https://pan.quark.cn/s/movie"], inspector.urls)

    def test_year_can_come_from_verified_file_when_share_title_has_no_year(self):
        inspector = FakeInspector(
            ShareInspection(
                True,
                "https://pan.quark.cn/s/movie",
                (SourceFile("Spider-Man.No.Way.Home.2021.2160p.WEB-DL.mkv", 8_000_000_000),),
            )
        )
        result = resolve_direct_movie_source(
            "Spider-Man: No Way Home",
            [{"share_url": "https://pan.quark.cn/s/movie", "title": "Spider-Man No Way Home", "cloud_type": "quark"}],
            inspector,
            provider_key="qas",
        )
        self.assertIsNotNone(result)
        self.assertEqual("2021", result.identity.year)


if __name__ == "__main__":
    unittest.main()
