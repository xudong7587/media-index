import unittest

from app.services.saved_episode_scanner import _last_episode_from_response, _response_matches_path, resolve_save_path_progress


class SavedEpisodeScannerTests(unittest.TestCase):
    def response(self, path_names, files):
        return {
            "success": True,
            "data": {
                "paths": [{"name": name} for name in path_names],
                "list": [{"file_name": name, "dir": False} for name in files],
            },
        }

    def test_reads_latest_episode_from_exact_qas_folder(self):
        response = self.response(
            ["下载_未整理", "tv", "测试节目 (2024)"],
            ["测试节目.2024.S03E05.mp4", "测试节目.2024.S03E06.mp4", "海报.jpg"],
        )
        self.assertTrue(_response_matches_path(response, "/下载_未整理/tv/测试节目 (2024)"))
        self.assertEqual(6, _last_episode_from_response(response, 3))

    def test_parent_folder_fallback_is_not_treated_as_target_folder(self):
        response = self.response(
            ["下载_未整理", "tv"],
            ["别的节目.S03E99.mp4"],
        )
        self.assertFalse(_response_matches_path(response, "/下载_未整理/tv/测试节目 (2024)"))

    def test_other_season_is_ignored(self):
        response = self.response(
            ["strm", "tv", "测试节目 (2024)"],
            ["测试节目.2024.S02E20.mp4", "测试节目.2024.S03E07.mp4"],
        )
        self.assertEqual(7, _last_episode_from_response(response, 3))

    def test_multiple_legacy_folders_are_rejected_as_conflict(self):
        class Qas:
            def savepath_detail(_, path):
                if path.endswith("测试节目(2024)"):
                    return self.response(["下载_未整理", "tv"], [])
                return {
                    "success": True,
                    "data": {
                        "paths": [{"name": "下载_未整理"}, {"name": "tv"}],
                        "list": [
                            {"file_name": "测试节目.2024", "dir": True},
                            {"file_name": "测试节目 (2024)", "dir": True},
                        ],
                    },
                }

        with self.assertRaisesRegex(RuntimeError, "multiple compatible"):
            resolve_save_path_progress("/下载_未整理/tv/测试节目(2024)", 3, qas=Qas())


if __name__ == "__main__":
    unittest.main()
