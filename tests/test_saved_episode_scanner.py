import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.saved_episode_scanner import _last_episode_from_response, _response_matches_path, refresh_saved_episodes, resolve_save_path_progress


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

    def test_missing_exact_folder_uses_readable_parent_as_empty(self):
        class Qas:
            def savepath_detail(_, path):
                if path.endswith("测试节目(2024)"):
                    return {"success": False, "message": "folder not found"}
                return {
                    "success": True,
                    "data": {
                        "paths": [{"name": "下载_未整理"}, {"name": "tv"}],
                        "list": [{"file_name": "其他节目(2024)", "dir": True}],
                    },
                }

        actual, last_episode = resolve_save_path_progress("/下载_未整理/tv/测试节目(2024)", 3, qas=Qas())

        self.assertEqual("/下载_未整理/tv/测试节目(2024)", actual)
        self.assertEqual(0, last_episode)

    def test_season_path_resolves_legacy_media_folder_before_reading_season(self):
        class Qas:
            def savepath_detail(_, path):
                if path.endswith("Season 3") and "（2024）" in path:
                    return self.response(
                        ["下载_未整理", "tv", "测试节目（2024）", "Season 3"],
                        ["测试节目.2024.S03E08.mp4"],
                    )
                if path.endswith("测试节目（2024）"):
                    return {
                        "success": True,
                        "data": {
                            "paths": [{"name": "下载_未整理"}, {"name": "tv"}, {"name": "测试节目（2024）"}],
                            "list": [{"file_name": "Season 3", "dir": True}],
                        },
                    }
                if path.endswith("测试节目(2024)") or (path.endswith("Season 3") and "（2024）" not in path):
                    return {"success": False, "message": "folder not found"}
                return {
                    "success": True,
                    "data": {
                        "paths": [{"name": "下载_未整理"}, {"name": "tv"}],
                        "list": [{"file_name": "测试节目（2024）", "dir": True}],
                    },
                }

        actual, last_episode = resolve_save_path_progress("/下载_未整理/tv/测试节目(2024)/Season 3", 3, qas=Qas())

        self.assertEqual("/下载_未整理/tv/测试节目（2024）/Season 3", actual)
        self.assertEqual(8, last_episode)

    def test_missing_season_under_legacy_media_folder_returns_real_season_path(self):
        class Qas:
            def savepath_detail(_, path):
                if path.endswith("测试节目（2024）"):
                    return {
                        "success": True,
                        "data": {
                            "paths": [{"name": "下载_未整理"}, {"name": "tv"}, {"name": "测试节目（2024）"}],
                            "list": [],
                        },
                    }
                if path.endswith("测试节目(2024)") or path.endswith("Season 3"):
                    return {"success": False, "message": "folder not found"}
                return {
                    "success": True,
                    "data": {
                        "paths": [{"name": "下载_未整理"}, {"name": "tv"}],
                        "list": [{"file_name": "测试节目（2024）", "dir": True}],
                    },
                }

        actual, last_episode = resolve_save_path_progress("/下载_未整理/tv/测试节目(2024)/Season 3", 3, qas=Qas())

        self.assertEqual("/下载_未整理/tv/测试节目（2024）/Season 3", actual)
        self.assertEqual(0, last_episode)

    def test_resolves_organized_season_folder_and_scans_its_episodes(self):
        class P115:
            def savepath_detail(_, path):
                if path.endswith("Season 1"):
                    return self.response(
                        ["媒体库", "03电视剧", "凡人修仙传 (2020)", "Season 1"],
                        ["凡人修仙传.S01E183.mkv"],
                    )
                return {
                    "success": True,
                    "data": {
                        "paths": [
                            {"name": "媒体库"},
                            {"name": "03电视剧"},
                            {"name": "凡人修仙传 (2020)"},
                        ],
                        "list": [{"file_name": "Season 1", "dir": True}],
                    },
                }

        actual, last_episode = resolve_save_path_progress(
            "/媒体库/03电视剧/凡人修仙传 (2020)", 1, qas=P115()
        )

        self.assertEqual("/媒体库/03电视剧/凡人修仙传 (2020)/Season 1", actual)
        self.assertEqual(183, last_episode)


class RefreshSavedEpisodesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db")})
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_refresh_inserts_actual_saved_episode_rows_before_counting(self):
        class Qas:
            def savepath_detail(_, path):
                return {
                    "success": True,
                    "data": {
                        "paths": [{"name": "strm"}, {"name": "variety"}, {"name": "Show (2024)"}, {"name": "Season 3"}],
                        "list": [
                            {"file_name": "Show.2024.S03E01.mp4", "dir": False},
                            {"file_name": "Show.2024.S03E02.mp4", "dir": False},
                            {"file_name": "Show.2024.S03E03.mp4", "dir": False},
                        ],
                    },
                }

        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path)
                VALUES(1,'variety','Show',3,'qas','/strm/variety/Show (2024)/Season 3')
                """
            ).lastrowid
            conn.execute(
                "INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,provider) VALUES(?,3,1,'pending','qas')",
                (task_id,),
            )

        result = refresh_saved_episodes(task_id, qas=Qas())

        self.assertTrue(result["ok"])
        self.assertEqual([1, 2, 3], result["drive_episodes"])
        with db() as conn:
            rows = conn.execute(
                "SELECT episode_number,status FROM tracking_episodes WHERE task_id=? ORDER BY episode_number",
                (task_id,),
            ).fetchall()
        self.assertEqual([(1, "saved"), (2, "saved"), (3, "saved")], [tuple(row) for row in rows])

    def test_successful_refresh_uses_drive_listing_as_authoritative(self):
        class Qas:
            def savepath_detail(_, path):
                return {
                    "success": True,
                    "data": {
                        "paths": [{"name": "strm"}, {"name": "variety"}, {"name": "Show (2024)"}, {"name": "Season 3"}],
                        "list": [
                            {"file_name": "Show.2024.S03E04.mp4", "dir": False},
                            {"file_name": "Show.2024.S03E05.mp4", "dir": False},
                        ],
                    },
                }

        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,last_saved_episode)
                VALUES(1,'variety','Show',3,'qas','/strm/variety/Show (2024)/Season 3',3)
                """
            ).lastrowid
            conn.executemany(
                "INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,provider) VALUES(?,3,?,'saved','qas')",
                [(task_id, 1), (task_id, 2), (task_id, 3)],
            )

        result = refresh_saved_episodes(task_id, qas=Qas())

        self.assertTrue(result["ok"])
        self.assertEqual(5, result["last_saved_episode"])
        with db() as conn:
            rows = conn.execute(
                "SELECT episode_number,status FROM tracking_episodes WHERE task_id=? ORDER BY episode_number",
                (task_id,),
            ).fetchall()
        self.assertEqual(
            [(1, "pending"), (2, "pending"), (3, "pending"), (4, "saved"), (5, "saved")],
            [tuple(row) for row in rows],
        )


if __name__ == "__main__":
    unittest.main()
