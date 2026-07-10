import unittest

from app.domain.media import MediaTarget
from app.services.previous_source import recover_previous_share_urls


class FakeQas:
    def tasklist(self):
        return [
            {"taskname": "Other Show S02", "shareurl": "https://pan.quark.cn/s/other"},
            {"taskname": "Target Show S01", "shareurl": "https://pan.quark.cn/s/wrong-season"},
            {"taskname": "Target Show S02", "shareurl": "https://pan.quark.cn/s/older"},
            {"taskname": "Target Show S02", "shareurl": "https://pan.quark.cn/s/newer"},
        ]


class PreviousSourceTests(unittest.TestCase):
    def test_recovers_matching_legacy_qas_links_newest_first(self):
        target = MediaTarget(1, "tv", "Target Show", season_number=2)

        result = recover_previous_share_urls(target, FakeQas())

        self.assertEqual(
            ("https://pan.quark.cn/s/newer", "https://pan.quark.cn/s/older"),
            result,
        )


if __name__ == "__main__":
    unittest.main()
