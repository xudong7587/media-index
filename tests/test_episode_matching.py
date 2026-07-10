import re
import unittest

from app.domain.media import EpisodeTarget, MediaTarget, SourceFile
from app.services.episode_matcher import build_rename_pair, match_episode_files, score_episode_file
from app.services.episode_tokens import build_episode_targets


class EpisodeMatchingTests(unittest.TestCase):
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

    def test_exact_season_episode_is_high_confidence(self):
        target, ep = self.target(4)
        result = score_episode_file(target, ep, SourceFile("测试节目.S03E04.2160p.mkv", 8_000_000_000))
        self.assertIsNotNone(result)
        self.assertEqual("high", result.confidence)
        self.assertGreaterEqual(result.score, 100)

    def test_derivative_content_is_excluded(self):
        target, ep = self.target(4)
        self.assertIsNone(score_episode_file(target, ep, SourceFile("测试节目.S03E04.纯享版.mp4")))

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

    def test_one_file_cannot_map_to_two_episodes(self):
        episodes = (
            EpisodeTarget(1, 1, match_tokens=("E01",)),
            EpisodeTarget(1, 2, match_tokens=("E02",)),
        )
        target = MediaTarget(1, "tv", "测试剧", season_number=1, episodes=episodes)
        files = [SourceFile("测试剧.S01E01E02.mkv")]
        matches, _ = match_episode_files(target, files)
        self.assertLessEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main()
