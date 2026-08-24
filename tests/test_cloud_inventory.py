import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.clients.p115 import P115File
from app.clients.quark import QuarkFile
from app.api.cloud import _auto_reconcile
from app.core.config import get_settings
from app.db.database import init_db
from app.services.cloud_inventory import scan_p115_inventory, scan_quark_inventory
from app.services.media_assets import list_assets
from app.services.strm_reconciler import reconcile_strm


class FakeP115:
    def __init__(self):
        self.read_calls = []

    def configured(self):
        return True

    def directory_id(self, path):
        self.read_calls.append(("directory_id", path))
        self.root_path = path
        return "root"

    def list_directory(self, directory_id):
        self.read_calls.append(("list_directory", directory_id))
        if directory_id == "root":
            return (
                P115File("movie", "root", "Movie.mkv", "/Movie.mkv", size=100),
                P115File("season", "root", "Season 1", "/Season 1", is_dir=True),
            )
        if directory_id == "season":
            return (P115File("episode", "season", "Episode.mkv", "/Season 1/Episode.mkv", size=50),)
        raise AssertionError("unexpected directory")


class CloudInventoryTests(unittest.TestCase):
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

    def test_scan_indexes_existing_files_without_creating_or_modifying_cloud_paths(self):
        client = FakeP115()
        result = scan_p115_inventory("/Media", client=client)

        self.assertEqual("/Media", client.root_path)
        self.assertEqual(("p115", "/Media", 2, 2, False), (result.provider, result.root_path, result.directories_scanned, result.files_indexed, result.truncated))
        self.assertEqual([("Episode.mkv", "ready"), ("Movie.mkv", "ready")], sorted((row["name"], row["status"]) for row in list_assets()))
        self.assertEqual([
            ("directory_id", "/Media"),
            ("list_directory", "root"),
            ("list_directory", "season"),
        ], client.read_calls)

    def test_scan_never_creates_a_missing_root(self):
        class MissingP115(FakeP115):
            def directory_id(self, _path):
                return "0"

        with self.assertRaisesRegex(Exception, "不存在"):
            scan_p115_inventory("/Missing", client=MissingP115())

    def test_unbounded_manual_scan_reads_past_the_standard_ten_thousand_file_safety_cap(self):
        class LargeP115:
            def configured(self): return True
            def directory_id(self, path): return "root"
            def list_directory(self, directory_id):
                if directory_id != "root":
                    raise AssertionError("unexpected directory")
                return tuple(P115File(f"file-{index}", "root", f"Episode {index}.mkv", f"/Episode {index}.mkv", size=1) for index in range(10001))

        with patch("app.services.cloud_inventory.register_asset") as register:
            result = scan_p115_inventory("/Large", client=LargeP115(), max_files=None, mark_missing=False)

        self.assertEqual(10001, result.files_indexed)
        self.assertFalse(result.truncated)
        self.assertEqual(10001, register.call_count)

    def test_selected_direct_child_directories_skip_unselected_siblings_and_root_files(self):
        class SelectedOnly(FakeP115):
            def list_directory(self, directory_id):
                self.read_calls.append(("list_directory", directory_id))
                if directory_id == "root":
                    return (
                        P115File("movie", "root", "Loose.mkv", "/Loose.mkv", size=1),
                        P115File("tv", "root", "电视剧", "/电视剧", is_dir=True),
                        P115File("movie-dir", "root", "电影", "/电影", is_dir=True),
                    )
                if directory_id == "tv":
                    return (P115File("episode", "tv", "S01E01.mkv", "/电视剧/S01E01.mkv", size=1),)
                if directory_id == "movie-dir":
                    raise AssertionError("unselected directory must not be read")
                raise AssertionError("unexpected directory")

        client = SelectedOnly()
        result = scan_p115_inventory("/媒体库", client=client, include_directories=["/媒体库/电视剧"])
        self.assertEqual((2, 1, False), (result.directories_scanned, result.files_indexed, result.truncated))
        self.assertEqual([("directory_id", "/媒体库"), ("list_directory", "root"), ("list_directory", "tv")], client.read_calls)

    def test_selected_directories_do_not_remove_or_regenerate_unselected_existing_strm(self):
        class TwoLibraries:
            def configured(self): return True
            def directory_id(self, path): return "root"
            def list_directory(self, directory_id):
                if directory_id == "root":
                    return (
                        P115File("movie-dir", "root", "电影", "/电影", is_dir=True),
                        P115File("tv-dir", "root", "电视剧", "/电视剧", is_dir=True),
                    )
                if directory_id == "movie-dir":
                    return (P115File("movie", "movie-dir", "Movie.mkv", "/电影/Movie.mkv", size=1),)
                if directory_id == "tv-dir":
                    return (P115File("episode", "tv-dir", "S01E01.mkv", "/电视剧/S01E01.mkv", size=1),)
                raise AssertionError("unexpected directory")

        output = Path(self.tempdir.name) / "strm"
        scan_p115_inventory("/媒体库", client=TwoLibraries())
        reconcile_strm(output_root=str(output), playback_base_url="http://127.0.0.1:8000", provider="p115", source_root_path="/媒体库")
        self.assertTrue((output / "电影" / "Movie.strm").is_file())

        result = scan_p115_inventory("/媒体库", client=TwoLibraries(), include_directories=["/媒体库/电视剧"])
        reconcile = reconcile_strm(
            output_root=str(output), playback_base_url="http://127.0.0.1:8000", provider="p115",
            source_root_path=result.root_path, include_directories=["/媒体库/电视剧"],
        )

        self.assertEqual(0, reconcile.removed)
        self.assertTrue((output / "电影" / "Movie.strm").is_file())
        self.assertTrue((output / "电视剧" / "S01E01.strm").is_file())
        statuses = {row["name"]: row["status"] for row in list_assets()}
        self.assertEqual("ready", statuses["Movie.mkv"])

    def test_scanned_video_is_immediately_eligible_for_real_strm_generation(self):
        scan_p115_inventory("/Media", client=FakeP115())
        output = Path(self.tempdir.name) / "strm"

        result = reconcile_strm(output_root=str(output), playback_base_url="http://127.0.0.1:8000", provider="p115")

        self.assertEqual(2, result.created)
        self.assertIn("/api/play/", (output / "Movie.strm").read_text(encoding="utf-8"))
        self.assertTrue((output / "Season 1" / "Episode.strm").is_file())

    def test_narrower_source_root_replaces_old_nested_paths_and_excludes_other_history(self):
        class BroadRoot:
            def configured(self): return True
            def directory_id(self, path): return "test-root"
            def list_directory(self, directory_id):
                if directory_id == "test-root":
                    return (
                        P115File("mirc", "test-root", "MIRC测试", "/MIRC测试", is_dir=True),
                        P115File("old", "test-root", "旧测试", "/旧测试", is_dir=True),
                    )
                if directory_id == "mirc":
                    return (P115File("current-movie", "mirc", "当前影片.mkv", "/MIRC测试/当前影片.mkv", size=100),)
                if directory_id == "old":
                    return (P115File("old-movie", "old", "旧影片.mkv", "/旧测试/旧影片.mkv", size=100),)
                raise AssertionError("unexpected directory")

        class NarrowRoot(BroadRoot):
            def directory_id(self, path): return "mirc"

        output = Path(self.tempdir.name) / "strm" / "MIRC测试"
        scan_p115_inventory("/测试", client=BroadRoot())
        reconcile_strm(output_root=str(output), playback_base_url="http://127.0.0.1:8000", provider="p115")
        self.assertTrue((output / "MIRC测试" / "当前影片.strm").is_file())
        self.assertTrue((output / "旧测试" / "旧影片.strm").is_file())

        scan = scan_p115_inventory("/测试/MIRC测试", client=NarrowRoot())
        result = reconcile_strm(
            output_root=str(output),
            playback_base_url="http://127.0.0.1:8000",
            provider="p115",
            source_root_path=scan.root_path,
        )

        self.assertTrue((output / "当前影片.strm").is_file())
        self.assertFalse((output / "MIRC测试" / "当前影片.strm").exists())
        self.assertFalse((output / "旧测试" / "旧影片.strm").exists())
        self.assertEqual(1, result.replaced)
        self.assertEqual(1, result.removed)
        assets = {row["file_id"]: row for row in list_assets()}
        self.assertEqual("当前影片.mkv", assets["current-movie"]["relative_path"])
        self.assertEqual("/测试/MIRC测试", assets["current-movie"]["inventory_root_path"])

    def test_quark_scan_reads_existing_directory_tree_without_save_or_move_commands(self):
        class FakeQuark:
            def configured(self): return True
            def directory_id(self, path): self.path = path; return "root"
            def list_directory(self, directory_id):
                if directory_id == "root": return (QuarkFile("file", "root", "Movie.mkv", 10),)
                return ()

        client = FakeQuark()
        result = scan_quark_inventory("/Media", client=client)
        self.assertEqual(("quark", 1, 1), (result.provider, result.directories_scanned, result.files_indexed))
        self.assertEqual("/Media", client.path)

    def test_complete_rescan_marks_missing_file_unavailable_without_touching_other_directories(self):
        client = FakeP115()
        scan_p115_inventory("/Media", client=client)

        class MissingEpisode(FakeP115):
            def list_directory(self, directory_id):
                if directory_id == "root":
                    return (P115File("movie", "root", "Movie.mkv", "/Movie.mkv", size=100), P115File("season", "root", "Season 1", "/Season 1", is_dir=True))
                if directory_id == "season":
                    return ()
                raise AssertionError("unexpected directory")

        scan_p115_inventory("/Media", client=MissingEpisode())
        statuses = {row["name"]: row["status"] for row in list_assets()}
        self.assertEqual("ready", statuses["Movie.mkv"])
        self.assertEqual("unavailable", statuses["Episode.mkv"])

    def test_automatic_strm_failure_is_reported_without_raising_after_scan(self):
        settings = type("Settings", (), {"p115_strm_enabled": True})()
        with (
            patch("app.api.cloud.get_settings", return_value=settings),
            patch("app.api.cloud.reconcile_strm", side_effect=OSError("disk full")),
        ):
            result = _auto_reconcile("p115", "/Media")

        self.assertFalse(result["ok"])
        self.assertIn("STRM 自动校正失败", result["message"])
        self.assertNotIn("disk full", result["message"])


if __name__ == "__main__":
    unittest.main()
