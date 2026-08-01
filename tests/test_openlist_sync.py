import unittest
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from app.clients.openlist import OpenListError
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.openlist_sync import (
    _ensure_openlist_directory,
    _list_entries_or_empty,
    _openlist_dir_for_task,
    _resolve_or_prepare_openlist_dir,
    sync_openlist_episode_dirs,
    sync_selected_openlist_once,
    start_selected_openlist_sync,
    sync_configured_openlist_library,
    sync_selected_tracking_episodes,
    sync_transfer_outputs,
)


class OpenListSyncTests(unittest.TestCase):
    def test_tracking_paths_map_each_provider_root_to_its_openlist_mount(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_QAS_LIBRARY_PATH": "/夸克",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "P115_ROOT_PATH": "/媒体库",
            },
        ):
            get_settings.cache_clear()
            settings = get_settings()
            self.assertEqual(
                "/夸克/strm/03电视剧/示例剧 (2026)/Season 1",
                _openlist_dir_for_task(
                    {"save_path": "/strm/03电视剧/示例剧 (2026)/Season 1"},
                    "qas",
                    settings,
                ),
            )
            self.assertEqual(
                "/115/媒体库/03电视剧/示例剧 (2026)/Season 1",
                _openlist_dir_for_task(
                    {"save_path": "/媒体库/03电视剧/示例剧 (2026)/Season 1"},
                    "p115",
                    settings,
                ),
            )

    def test_configured_auto_sync_runs_library_sync(self):
        with (
            patch.dict(os.environ, {"OPENLIST_ENABLED": "true", "OPENLIST_AUTO_SYNC": "true"}),
            patch("app.services.openlist_sync.sync_openlist_library_once", return_value={"ok": True, "copied": 2}) as sync,
        ):
            get_settings.cache_clear()
            result = sync_configured_openlist_library()
        sync.assert_called_once_with()
        self.assertEqual({"ok": True, "copied": 2}, result)

    def test_transfer_sync_discovers_source_files_when_rename_pairs_are_empty(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "ENABLED_CLOUD_PROVIDERS": "qas,p115",
            },
        ):
            get_settings.cache_clear()
            with (
                patch("app.services.openlist_sync.OpenListClient") as client_class,
                patch("app.services.openlist_sync.sync_tracking_episode", return_value={"ok": True}) as sync_episode,
            ):
                client_class.return_value.list_entries.return_value = [
                    {"name": "Show.S01E01.mkv", "is_dir": False},
                    {"name": "Season 1", "is_dir": True},
                ]
                result = sync_transfer_outputs("qas", "/strm/tv/Show", [])

        self.assertEqual([{"ok": True}], result)
        sync_episode.assert_called_once_with(
            {"provider": "qas", "save_path": "/strm/tv/Show", "tmdb_id": None, "media_type": "", "season_number": None},
            "p115",
            "Show.S01E01.mkv",
        )

    def test_selected_tracking_sync_copies_only_missing_episode_to_current_provider(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "P115_ROOT_PATH": "/strm",
            },
        ):
            get_settings.cache_clear()
            init_db()
            test_tmdb_id = 900000000 + int(time.time() * 1000) % 90000000
            with db() as conn:
                target_id = conn.execute(
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status) VALUES(?,'tv','OpenList Selected Sync',1,'qas','/strm/tv/OpenList Selected Sync','active')",
                    (test_tmdb_id,),
                ).lastrowid
                conn.execute(
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status) VALUES(?,'tv','OpenList Selected Sync',1,'p115','/strm/tv/OpenList Selected Sync','active')",
                    (test_tmdb_id,),
                )
            with patch("app.services.openlist_sync.OpenListClient") as client_class:
                client = client_class.return_value

                def entries(path):
                    if path == "/quark/strm/tv/OpenList Selected Sync":
                        return []
                    if path == "/115/strm/tv/OpenList Selected Sync":
                        return [{"name": "OpenList Selected Sync.S01E01.mkv", "is_dir": False}]
                    return []

                client.list_entries.side_effect = entries
                result = sync_selected_tracking_episodes(int(target_id), [1])

        self.assertTrue(result["ok"])
        self.assertEqual([1], result["copied"])
        client.copy.assert_called_once_with(
            "/115/strm/tv/OpenList Selected Sync",
            "/quark/strm/tv/OpenList Selected Sync",
            ["OpenList Selected Sync.S01E01.mkv"],
            overwrite=False,
        )

    def test_selected_tracking_sync_falls_back_to_native_source_listing(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "P115_ROOT_PATH": "/strm",
            },
        ):
            get_settings.cache_clear()
            init_db()
            test_tmdb_id = 910000000 + int(time.time() * 1000) % 80000000
            with db() as conn:
                target_id = conn.execute(
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status) VALUES(?,'tv','Native Fallback',1,'p115','/strm/tv/Native Fallback','active')",
                    (test_tmdb_id,),
                ).lastrowid
                conn.execute(
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status) VALUES(?,'tv','Native Fallback',1,'qas','/strm/tv/Native Fallback','active')",
                    (test_tmdb_id,),
                )
            with (
                patch("app.services.openlist_sync.OpenListClient") as client_class,
                patch("app.services.openlist_sync.get_transfer_provider") as provider_factory,
            ):
                client = client_class.return_value
                client.list_entries.return_value = []
                provider_factory.return_value.inspect_save_path.return_value = {
                    "success": True,
                    "data": {"list": [{"file_name": "Native Fallback.S01E185.mkv", "dir": False}]},
                }
                result = sync_selected_tracking_episodes(int(target_id), [185])

        self.assertTrue(result["ok"])
        self.assertEqual([185], result["copied"])
        client.copy.assert_called_once_with(
            "/quark/strm/tv/Native Fallback",
            "/115/strm/tv/Native Fallback",
            ["Native Fallback.S01E185.mkv"],
            overwrite=False,
        )

    def test_missing_directory_lists_as_empty(self):
        class Client:
            def list_entries(self, path):
                raise OpenListError("failed get objs: failed get dir: object not found")

        self.assertEqual([], _list_entries_or_empty(Client(), "/quark/show/Season 3"))

    def test_ensure_directory_creates_missing_parents(self):
        class Client:
            existing = {"/quark", "/quark/strm"}
            created = []

            def list_entries(self, path):
                if path not in self.existing:
                    raise OpenListError("object not found")
                return []

            def mkdir(self, path):
                self.created.append(path)
                self.existing.add(path)

        client = Client()

        _ensure_openlist_directory(client, "/quark/strm/tv/Show/Season 3")

        self.assertEqual(
            ["/quark/strm/tv", "/quark/strm/tv/Show", "/quark/strm/tv/Show/Season 3"],
            client.created,
        )

    def test_resolves_compatible_media_folder_spacing(self):
        class Client:
            def list_entries(self, path):
                if path == "/quark/strm/03电视剧/龙之家族(2022)/Season 3":
                    raise OpenListError("object not found")
                if path == "/quark/strm/03电视剧":
                    return [{"name": "龙之家族 (2022)", "is_dir": True}]
                if path == "/quark/strm/03电视剧/龙之家族 (2022)":
                    return [{"name": "Season 3", "is_dir": True}]
                if path == "/quark/strm/03电视剧/龙之家族 (2022)/Season 3":
                    return []
                raise OpenListError("object not found")

        resolved = _resolve_or_prepare_openlist_dir(Client(), "/quark/strm/03电视剧/龙之家族(2022)/Season 3", create=False)

        self.assertEqual("/quark/strm/03电视剧/龙之家族 (2022)/Season 3", resolved)

    def test_resolves_alias_media_folder_name(self):
        class Client:
            def list_entries(self, path):
                if path == "/quark/strm/03电视剧/龙之家族 (2022)":
                    raise OpenListError("object not found")
                if path == "/quark/strm/03电视剧":
                    return [{"name": "House of the Dragon (2022)", "is_dir": True}]
                if path == "/quark/strm/03电视剧/House of the Dragon (2022)":
                    return []
                raise OpenListError("object not found")

        resolved = _resolve_or_prepare_openlist_dir(
            Client(),
            "/quark/strm/03电视剧/龙之家族 (2022)",
            create=False,
            aliases=("House of the Dragon (2022)",),
        )

        self.assertEqual("/quark/strm/03电视剧/House of the Dragon (2022)", resolved)

    def test_resolves_compatible_season_folder_name(self):
        class Client:
            def list_entries(self, path):
                if path == "/quark/show/Season 3":
                    raise OpenListError("object not found")
                if path == "/quark/show":
                    return [{"name": "S03", "is_dir": True}]
                if path == "/quark/show/S03":
                    return []
                raise OpenListError("object not found")

        resolved = _resolve_or_prepare_openlist_dir(Client(), "/quark/show/Season 3", create=False)

        self.assertEqual("/quark/show/S03", resolved)


class OpenListSyncJobTests(unittest.TestCase):
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

    def test_episode_dir_sync_reuses_running_same_task(self):
        with db() as conn:
            conn.execute(
                """
                INSERT INTO transfer_jobs(
                    tmdb_id,media_type,season_number,target,provider,status,stage,message,execution_key
                ) VALUES(1,'tv',3,'cloud','openlist','running','openlist_sync','running','openlist:tracking:1:tv:3')
                """
            )

        result = sync_openlist_episode_dirs(
            "/夸克/剧集/Show/Season 3",
            "/115/剧集/Show/Season 3",
            3,
            execution_key="openlist:tracking:1:tv:3",
            tmdb_id=1,
            media_type="tv",
            display_title="Show",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["duplicate"])
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE provider='openlist'").fetchone()[0]
        self.assertEqual(1, count)

    def test_selected_sync_reuses_running_same_parameters(self):
        key = "openlist:selected:/left:/right:0:E01.mkv"
        with db() as conn:
            conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage,message,execution_key)
                VALUES('cloud','openlist','running','openlist_sync','running',?)
                """,
                (key,),
            )

        result = sync_selected_openlist_once("/left", "/right", ["E01.mkv"], overwrite=False)

        self.assertTrue(result["ok"])
        self.assertTrue(result["duplicate"])
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE execution_key=?", (key,)).fetchone()[0]
        self.assertEqual(1, count)

    def test_start_selected_sync_creates_a_running_task_before_copying(self):
        result = start_selected_openlist_sync("/left", "/right", ["E01.mkv"], overwrite=False)

        self.assertTrue(result["ok"])
        self.assertTrue(result["running"])
        self.assertEqual("已开始同步 1 项，可在右上角执行任务查看进度", result["message"])
        with db() as conn:
            row = conn.execute("SELECT status,stage,display_title FROM transfer_jobs WHERE id=?", (result["job_id"],)).fetchone()
        self.assertEqual(("running", "openlist_sync", "OpenList 手动同步"), tuple(row))


if __name__ == "__main__":
    unittest.main()
