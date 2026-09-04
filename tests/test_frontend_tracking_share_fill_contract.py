import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendTrackingShareFillContractTests(unittest.TestCase):
    def setUp(self):
        self.main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")

    def test_share_fill_defaults_to_all_aired_missing_episodes(self):
        self.assertIn('const selectedEpisodes = selectedMissing[state.id] || [];', self.main)
        self.assertIn('episode.status !== "saved" && episode.aired', self.main)
        self.assertIn('"\u94fe\u63a5\u8865\u9f50\u5168\u90e8\u7f3a\u96c6"', self.main)

    def test_share_fill_button_no_longer_requires_manual_episode_selection(self):
        button = next(
            line for line in self.main.splitlines()
            if 'onClick={() => void fillEpisodesFromShare(state)}' in line
        )
        self.assertNotIn('selectedMissing[state.id]', button)
        self.assertIn('shareLinkDrafts[state.id]', button)


if __name__ == "__main__":
    unittest.main()
