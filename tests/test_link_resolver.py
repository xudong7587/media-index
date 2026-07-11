import unittest
from types import SimpleNamespace

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.link_resolver import resolve_episode_source


class FakeQas:
    def __init__(self, shares):
        self.shares = shares
        self.calls = []

    def share_detail(self, url):
        self.calls.append(url)
        return self.shares[url]


class FakePansou:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def search_detailed(self, keyword, *args, **kwargs):
        self.calls.append(keyword)
        return SimpleNamespace(items=self.items, error="")


def share(*files):
    return {
        "success": True,
        "data": {
            "files": [
                {"file_name": name, "size": size, "dir": False}
                for name, size in files
            ]
        },
    }


class LinkResolverTests(unittest.TestCase):
    def target(self):
        episode = EpisodeTarget(3, 2, "2026-07-10", match_tokens=("S03E02", "E02", "20260710"))
        return MediaTarget(
            1,
            "variety",
            "测试节目",
            original_title="Test Show",
            series_year="2024",
            season_number=3,
            season_year="2026",
            episodes=(episode,),
        )

    def test_reuses_previous_link_when_target_episode_exists(self):
        old = "https://pan.quark.cn/s/old"
        qas = FakeQas({old: share(("测试节目.S03E02.2160p.mkv", 8_000_000_000))})
        pansou = FakePansou([])
        result = resolve_episode_source(self.target(), old, qas=qas, pansou=pansou)
        self.assertTrue(result.ok)
        self.assertEqual("previous_link", result.source)
        self.assertEqual([], pansou.calls)

    def test_exact_available_episode_does_not_wait_for_every_pending_episode(self):
        episodes = (
            EpisodeTarget(3, 2, match_tokens=("E02",)),
            EpisodeTarget(3, 3, match_tokens=("E03",)),
        )
        target = MediaTarget(1, "variety", "测试节目", season_number=3, episodes=episodes)
        link = "https://pan.quark.cn/s/partial"
        qas = FakeQas({link: share(("测试节目.S03E03.第3期上.mp4", 6_000_000_000))})

        result = resolve_episode_source(target, link, qas=qas, pansou=FakePansou([]))

        self.assertTrue(result.ok)
        self.assertEqual((3,), result.matches[0].episode_numbers)
        self.assertEqual(1, len(result.rename_pairs))

    def test_clear_three_digit_episode_can_proceed_beside_ambiguous_older_episode(self):
        episodes = (EpisodeTarget(1, 177), EpisodeTarget(1, 179))
        target = MediaTarget(106449, "tv", "凡人修仙传", series_year="2020", season_number=1, episodes=episodes)
        link = "https://pan.quark.cn/s/current"
        qas = FakeQas(
            {link: share(("177 4K.mp4", 1), ("177重制版 4K.mp4", 2), ("179 4K.mp4", 3))}
        )
        result = resolve_episode_source(target, link, qas=qas, pansou=FakePansou([]))
        self.assertTrue(result.ok)
        self.assertEqual(1, len(result.rename_pairs))
        self.assertEqual((179,), result.rename_pairs[0].episode_numbers)

    def test_reuses_combined_episode_file_as_one_transfer(self):
        episodes = (
            EpisodeTarget(1, 1, match_tokens=("E01",)),
            EpisodeTarget(1, 2, match_tokens=("E02",)),
        )
        target = MediaTarget(1, "tv", "测试剧", series_year="2026", season_number=1, episodes=episodes)
        old = "https://pan.quark.cn/s/combined"
        qas = FakeQas({old: share(("测试剧.S01E01-E02.2160p.mkv", 12_000_000_000))})
        result = resolve_episode_source(target, old, qas=qas, pansou=FakePansou([]))
        self.assertTrue(result.ok)
        self.assertEqual(1, len(result.rename_pairs))
        self.assertEqual((1, 2), result.rename_pairs[0].episode_numbers)
        self.assertEqual("测试剧.2026.S01E01-E02.mkv", result.rename_pairs[0].replacement)

    def test_searches_new_link_when_previous_has_not_updated(self):
        old = "https://pan.quark.cn/s/old"
        new = "https://pan.quark.cn/s/new"
        qas = FakeQas(
            {
                old: share(("测试节目.S03E01.mkv", 5_000_000_000)),
                new: share(("测试节目.S03E02.mkv", 6_000_000_000)),
            }
        )
        pansou = FakePansou([{"share_url": new, "title": "测试节目 第3季 2026"}])
        result = resolve_episode_source(self.target(), old, qas=qas, pansou=pansou)
        self.assertTrue(result.ok)
        self.assertEqual(new, result.share_url)
        self.assertEqual("pansou", result.source)
        self.assertGreater(len(pansou.calls), 0)

    def test_invalid_old_and_ambiguous_new_requires_review(self):
        old = "https://pan.quark.cn/s/old"
        new = "https://pan.quark.cn/s/new"
        qas = FakeQas(
            {
                old: {"success": False, "message": "expired"},
                new: share(("测试节目.20260710.版本A.mkv", 6_000_000_000), ("测试节目.20260710.版本B.mkv", 6_100_000_000)),
            }
        )
        pansou = FakePansou([{"share_url": new, "title": "测试节目 第3季 2026"}])
        result = resolve_episode_source(self.target(), old, qas=qas, pansou=pansou)
        self.assertFalse(result.ok)
        self.assertEqual("needs_review", result.stage)
        self.assertEqual(
            ("测试节目.20260710.版本A.mkv", "测试节目.20260710.版本B.mkv"),
            result.reviewed_candidates[0].files,
        )

    def test_user_selected_file_resolves_ambiguous_share(self):
        selected = "https://pan.quark.cn/s/selected-file"
        qas = FakeQas(
            {
                selected: share(
                    ("测试节目.20260710.版本A.mkv", 6_000_000_000),
                    ("测试节目.20260710.版本B.mkv", 6_100_000_000),
                )
            }
        )
        stages = []
        result = resolve_episode_source(
            self.target(),
            selected,
            qas=qas,
            pansou=FakePansou([]),
            preferred_source_names=("测试节目.20260710.版本B.mkv",),
            on_progress=lambda stage, message: stages.append(stage),
        )
        self.assertTrue(result.ok)
        self.assertEqual("测试节目.20260710.版本B.mkv", result.rename_pairs[0].source_name)
        self.assertIn("validating_link", stages)

    def test_user_confirmed_medium_match_can_become_ready(self):
        episode = EpisodeTarget(3, 18, "", match_tokens=("S03E18", "E18"))
        target = MediaTarget(1, "variety", "测试节目", season_number=3, episodes=(episode,))
        selected = "https://pan.quark.cn/s/selected"
        qas = FakeQas({selected: share(("测试节目.18.mkv", 6_000_000_000))})

        normal = resolve_episode_source(target, selected, qas=qas, pansou=FakePansou([]))
        confirmed = resolve_episode_source(
            target,
            selected,
            qas=qas,
            pansou=FakePansou([]),
            allow_review_confidence=True,
        )

        self.assertFalse(normal.ok)
        self.assertTrue(confirmed.ok)
        self.assertEqual("medium", confirmed.rename_pairs[0].confidence)

    def test_numeric_sequence_requires_strong_candidate_title_for_auto_run(self):
        target = MediaTarget(1, "tv", "测试动画", season_number=1, episodes=(EpisodeTarget(1, 1),))
        link = "https://pan.quark.cn/s/numeric"
        files = share(("01 1080p.mp4", 1), ("02 1080p.mp4", 1), ("03 1080p.mp4", 1))
        weak = resolve_episode_source(
            target,
            qas=FakeQas({link: files}),
            pansou=FakePansou([{"share_url": link, "title": "每日更新合辑"}]),
            max_queries=1,
        )
        strong = resolve_episode_source(
            target,
            qas=FakeQas({link: files}),
            pansou=FakePansou([{"share_url": link, "title": "测试动画 第一季"}]),
            max_queries=1,
        )
        self.assertFalse(weak.ok)
        self.assertEqual("needs_review", weak.stage)
        self.assertTrue(strong.ok)
        self.assertEqual("01 1080p.mp4", strong.rename_pairs[0].source_name)


if __name__ == "__main__":
    unittest.main()
