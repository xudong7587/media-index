import re
import unittest
from types import SimpleNamespace

from app.domain.media import MediaTarget, SourceFile
from app.services.movie_matcher import build_movie_rename_pair, choose_movie_file
from app.services.movie_resolver import resolve_movie_source


class MovieMatchingTests(unittest.TestCase):
    def target(self):
        return MediaTarget(1, "movie", "超级少女", original_title="Supergirl", series_year="1984")

    def test_wrong_year_is_rejected(self):
        source, *_ = choose_movie_file(
            self.target(),
            [SourceFile("Supergirl.2023.2160p.mkv", 10_000_000_000)],
        )
        self.assertIsNone(source)

    def test_numeric_only_translated_alias_does_not_match_episode_number(self):
        target = MediaTarget(
            1,
            "movie",
            "小黄人与大怪兽",
            original_title="Minions & Monsters",
            aliases=("미니언즈 3",),
            series_year="2026",
        )
        source, score, reasons, _ = choose_movie_file(
            target,
            [SourceFile("Daemons.of.the.Shadow.Realm.S01E03.2026.mkv", 8_000_000_000)],
            "黄泉的使者 (2026)",
        )
        self.assertIsNotNone(source)
        self.assertIn("title_weak", reasons)
        self.assertNotIn("title", reasons)

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

    def test_same_movie_dv_and_hdr_variants_are_not_treated_as_two_movies(self):
        target = MediaTarget(1, "movie", "火遮眼", series_year="2026")
        source, _, reasons, ambiguous = choose_movie_file(
            target,
            [
                SourceFile("2026.2160p.WEB-DL.H265.HDR10.10bit.Dolby Atmos 5.1.mkv", 8_000_000_000),
                SourceFile("2026.2160p.WEB-DL.H265.DV.10bit.Dolby Atmos 5.1.mkv", 8_000_000_000),
            ],
            "火遮眼（2026）4K DV + HDR10",
        )
        self.assertIsNotNone(source)
        self.assertIn(".DV.", source.name)
        self.assertIn("dolby_vision", reasons)
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

    def test_unrelated_generic_collection_is_not_exposed_for_review(self):
        target = MediaTarget(1108427, "movie", "海洋奇缘：启航", original_title="Moana", aliases=("海洋奇缘",), series_year="2026")

        class Pansou:
            def search_detailed(self, *args, **kwargs):
                return SimpleNamespace(
                    items=[{"share_url": "https://pan.quark.cn/s/noise", "title": "2026-04-27合辑"}],
                    error="",
                )

        class Qas:
            def share_detail(self, url):
                return {"success": True, "data": {"files": [{"file_name": "完全无关电影.2026.2160p.mkv", "size": 8_000_000_000}]}}

        result = resolve_movie_source(target, qas=Qas(), pansou=Pansou(), max_queries=1)
        self.assertFalse(result.ok)
        self.assertEqual("no_resource", result.stage)
        self.assertEqual((), result.reviewed_candidates)


if __name__ == "__main__":
    unittest.main()
