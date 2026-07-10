import re
import unittest

from app.domain.media import MediaTarget, SourceFile
from app.services.movie_matcher import build_movie_rename_pair, choose_movie_file


class MovieMatchingTests(unittest.TestCase):
    def target(self):
        return MediaTarget(1, "movie", "超级少女", original_title="Supergirl", series_year="1984")

    def test_wrong_year_is_rejected(self):
        source, *_ = choose_movie_file(
            self.target(),
            [SourceFile("Supergirl.2023.2160p.mkv", 10_000_000_000)],
        )
        self.assertIsNone(source)

    def test_same_release_prefers_4k_over_1080p_without_review(self):
        target = MediaTarget(1, "movie", "测试电影", series_year="2026")
        source, _, _, ambiguous = choose_movie_file(
            target,
            [
                SourceFile("测试电影.2026.1080p.WEB-DL.mkv", 4_000_000_000),
                SourceFile("测试电影.2026.2160p.WEB-DL.mkv", 12_000_000_000),
            ],
        )
        self.assertIsNotNone(source)
        self.assertIn("2160p", source.name)
        self.assertFalse(ambiguous)

    def test_main_movie_beats_trailer(self):
        source, score, reasons, ambiguous = choose_movie_file(
            self.target(),
            [
                SourceFile("Supergirl.1984.Trailer.2160p.mkv", 2_000_000_000),
                SourceFile("Supergirl.1984.1080p.mkv", 8_000_000_000),
            ],
        )
        self.assertEqual("Supergirl.1984.1080p.mkv", source.name)
        self.assertFalse(ambiguous)
        pair = build_movie_rename_pair(self.target(), source, reasons)
        self.assertEqual("超级少女.1984.mkv", pair.replacement)
        self.assertIsNotNone(re.fullmatch(pair.pattern, source.name))


if __name__ == "__main__":
    unittest.main()
