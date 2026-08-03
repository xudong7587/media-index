import unittest

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.standard_resolver import resolve_standard_tv_source


def share(*files):
    return {
        "success": True,
        "data": {"files": [{"file_name": name, "size": size, "dir": False} for name, size in files]},
    }


class FakeQas:
    key = "qas"

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
        return type("Response", (), {"items": self.items, "error": ""})()


class StandardResolverTests(unittest.TestCase):
    def target(self):
        return MediaTarget(
            1,
            "tv",
            "测试剧",
            original_title="Test Show",
            series_year="2026",
            season_number=1,
            episodes=(EpisodeTarget(1, 1), EpisodeTarget(1, 2)),
        )

    def test_pan_sou_first_share_is_verified_by_name_year_and_episode_marker(self):
        link = "https://pan.quark.cn/s/standard"
        qas = FakeQas(
            {
                link: share(
                    ("Test.Show.2026.S01E01.1080p.mkv", 6_000_000_000),
                    ("Test.Show.2026.S01E02.1080p.mkv", 6_000_000_000),
                )
            }
        )
        pansou = FakePansou([])

        result = resolve_standard_tv_source(self.target(), (link,), qas=qas, pansou=pansou)

        self.assertTrue(result.ok)
        self.assertEqual(link, result.share_url)
        self.assertEqual(
            ["测试剧.2026.S01E01.1080p.mkv", "测试剧.2026.S01E02.1080p.mkv"],
            [pair.replacement for pair in result.rename_pairs],
        )
        self.assertEqual([], pansou.calls)

    def test_wrong_year_and_derivative_files_are_not_selected(self):
        link = "https://pan.quark.cn/s/standard"
        qas = FakeQas(
            {
                link: share(
                    ("Test.Show.2025.S01E01.1080p.mkv", 6_000_000_000),
                    ("Test.Show.2026.S01E01.幕后花絮.mkv", 6_000_000_000),
                )
            }
        )
        result = resolve_standard_tv_source(self.target(), (link,), qas=qas, pansou=FakePansou([]))

        self.assertFalse(result.ok)
        self.assertEqual("no_resource", result.stage)


if __name__ == "__main__":
    unittest.main()
