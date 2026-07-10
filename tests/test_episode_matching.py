import re
import unittest

from app.domain.media import EpisodeTarget, MediaTarget, SourceFile
from app.services.episode_matcher import build_rename_pair, match_episode_files, score_episode_file
from app.services.episode_tokens import build_episode_targets


class EpisodeMatchingTests(unittest.TestCase):
    def test_variety_target_generation_excludes_derivative_tmdb_episodes(self):
        episodes = build_episode_targets(
            2,
            [
                {"episode_number": 1, "name": "第1期（上）", "air_date": "2026-07-01"},
                {"episode_number": 2, "name": "第1期（下）", "air_date": "2026-07-01"},
                {"episode_number": 3, "name": "第1期加更版", "air_date": "2026-07-02"},
                {"episode_number": 4, "name": "纯享舞台", "air_date": "2026-07-02"},
                {"episode_number": 5, "name": "幕后陪看", "air_date": "2026-07-02"},
            ],
            exclude_derivatives=True,
        )
        self.assertEqual([1, 2], [episode.episode_number for episode in episodes])

    def target(self, episode: int = 4) -> tuple[MediaTarget, EpisodeTarget]:
        ep = EpisodeTarget(3, episode, "2026-07-10", f"第{episode}期", (f"S03E{episode:02d}", f"E{episode:02d}"))
        target = MediaTarget(1, "variety", "测试节目", series_year="2026", season_number=3, episodes=(ep,))
        return target, ep

    def test_quality_tokens_are_not_episode_numbers(self):
        for filename, episode in (
            ("测试节目.4K.WEB-DL.mkv", 4),
            ("测试节目.8bit.1080p.mkv", 8),
            ("测试节目.S10.Complete.mkv", 10),
            ("SOME18.mkv", 18),
        ):
            target, ep = self.target(episode)
            self.assertIsNone(score_episode_file(target, ep, SourceFile(filename)))

    def test_wrong_episode_is_hard_rejected(self):
        target, ep = self.target(4)
        self.assertIsNone(score_episode_file(target, ep, SourceFile("测试节目.S03E05.1080p.mkv")))

    def test_variety_upper_and_lower_parts_do_not_cross_match(self):
        episode = EpisodeTarget(2, 1, "2026-07-01", "第1期（上）", ("20260701",))
        target = MediaTarget(1, "variety", "测试节目", season_number=2, episodes=(episode,))
        self.assertIsNotNone(score_episode_file(target, episode, SourceFile("测试节目.20260701.上.mkv")))
        self.assertIsNone(score_episode_file(target, episode, SourceFile("测试节目.20260701.下.mkv")))

    def test_exact_season_episode_is_high_confidence(self):
        target, ep = self.target(4)
        result = score_episode_file(target, ep, SourceFile("测试节目.S03E04.2160p.mkv", 8_000_000_000))
        self.assertIsNotNone(result)
        self.assertEqual("high", result.confidence)
        self.assertGreaterEqual(result.score, 100)

    def test_derivative_content_is_excluded(self):
        target, ep = self.target(4)
        self.assertIsNone(score_episode_file(target, ep, SourceFile("测试节目.S03E04.纯享版.mp4")))
        self.assertIsNone(score_episode_file(target, ep, SourceFile("测试节目.S03E04.陪看版.mp4")))
        self.assertIsNone(score_episode_file(target, ep, SourceFile("测试节目.S03E04.会员版.mp4")))

    def test_pattern_is_anchored_and_escaped(self):
        target, ep = self.target(4)
        source = SourceFile("测试节目.[WEB-DL](4K)+.S03E04.mkv")
        match = score_episode_file(target, ep, source)
        self.assertIsNotNone(match)
        pair = build_rename_pair(target, match)
        self.assertEqual(source.name, re.fullmatch(pair.pattern, source.name).group(0))
        self.assertEqual("测试节目.2026.S03E04.mkv", pair.replacement)

    def test_unique_chinese_issue_tokens(self):
        episodes = build_episode_targets(
            3,
            [
                {"episode_number": 1, "name": "第1期上：开场", "air_date": "2026-07-01"},
                {"episode_number": 2, "name": "第1期中：对谈", "air_date": "2026-07-01"},
                {"episode_number": 3, "name": "序章：甲", "air_date": "2026-07-02"},
                {"episode_number": 4, "name": "序章：乙", "air_date": "2026-07-03"},
            ],
        )
        self.assertIn("第1期上", episodes[0].match_tokens)
        self.assertIn("第1期中", episodes[1].match_tokens)
        self.assertNotIn("序章", episodes[2].match_tokens)
        self.assertNotIn("序章", episodes[3].match_tokens)

    def test_variety_always_has_numeric_issue_token(self):
        episodes = build_episode_targets(
            2,
            [{"episode_number": 28, "name": "音乐人合作舞台", "air_date": "2026-07-10"}],
            include_issue_tokens=True,
        )
        self.assertIn("第28期", episodes[0].match_tokens)
        target = MediaTarget(1, "variety", "音乐缘计划", season_number=2, episodes=episodes)
        result = score_episode_file(target, episodes[0], SourceFile("音乐缘计划.第28期.1080p.mp4"))
        self.assertIsNotNone(result)
        self.assertEqual("high", result.confidence)

    def test_tmdb_issue_part_maps_to_sequential_episode_number(self):
        episodes = build_episode_targets(
            2,
            [
                {"episode_number": 13, "name": "第 6 期（上）：合作舞台", "air_date": "2025-11-28"},
                {"episode_number": 14, "name": "第 6 期（中）：合作舞台", "air_date": "2025-11-28"},
                {"episode_number": 15, "name": "第 6 期（下）：合作舞台", "air_date": "2025-11-28"},
            ],
            include_issue_tokens=True,
        )
        self.assertIn("第6期上", episodes[0].match_tokens)
        self.assertNotIn("第13期", episodes[0].match_tokens)
        target = MediaTarget(1, "variety", "音乐缘计划", season_number=2, episodes=episodes)
        matches, ambiguities = match_episode_files(target, [SourceFile("第6期中.mp4")])
        self.assertFalse(ambiguities)
        self.assertEqual(14, matches[0].episode.episode_number)
        self.assertEqual("音乐缘计划.S02E14.mp4", build_rename_pair(target, matches[0]).replacement)

    def test_one_file_cannot_map_to_two_episodes(self):
        episodes = (
            EpisodeTarget(1, 1, match_tokens=("E01",)),
            EpisodeTarget(1, 2, match_tokens=("E02",)),
        )
        target = MediaTarget(1, "tv", "测试剧", season_number=1, episodes=episodes)
        files = [SourceFile("测试剧.S01E01E02.mkv")]
        matches, _ = match_episode_files(target, files)
        self.assertLessEqual(len(matches), 1)

    def test_constrained_episode_is_assigned_before_flexible_episode(self):
        episodes = (
            EpisodeTarget(1, 1, match_tokens=("20260710", "甲专属")),
            EpisodeTarget(1, 2, match_tokens=("20260710",)),
        )
        target = MediaTarget(1, "variety", "测试节目", season_number=1, episodes=episodes)
        files = [
            SourceFile("测试节目.20260710.mp4"),
            SourceFile("测试节目.甲专属.mp4"),
        ]
        matches, ambiguities = match_episode_files(target, files)
        self.assertEqual([], ambiguities)
        self.assertEqual(2, len(matches))
        self.assertEqual("测试节目.甲专属.mp4", matches[0].source.name)
        self.assertEqual("测试节目.20260710.mp4", matches[1].source.name)

    def test_combined_episode_file_has_one_safe_range_rename(self):
        episodes = (
            EpisodeTarget(1, 1, match_tokens=("E01",)),
            EpisodeTarget(1, 2, match_tokens=("E02",)),
        )
        target = MediaTarget(1, "tv", "测试剧", series_year="2026", season_number=1, episodes=episodes)
        source = SourceFile("测试剧.S01E01-E02.2160p.mkv")
        matches, ambiguities = match_episode_files(target, [source])
        self.assertEqual([], ambiguities)
        self.assertEqual(1, len(matches))
        self.assertEqual((1, 2), matches[0].episode_numbers)
        pair = build_rename_pair(target, matches[0])
        self.assertEqual("测试剧.2026.S01E01-E02.mkv", pair.replacement)
        self.assertEqual((1, 2), pair.episode_numbers)

    def test_large_season_pack_is_not_mistaken_for_combined_episode(self):
        episodes = tuple(EpisodeTarget(1, number) for number in range(1, 13))
        target = MediaTarget(1, "tv", "测试剧", season_number=1, episodes=episodes)
        matches, _ = match_episode_files(target, [SourceFile("测试剧.S01E01-E12.mkv")])
        self.assertNotEqual(set(range(1, 13)), {number for match in matches for number in match.episode_numbers})


if __name__ == "__main__":
    unittest.main()
