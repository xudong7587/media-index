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


if __name__ == "__main__":
    unittest.main()
