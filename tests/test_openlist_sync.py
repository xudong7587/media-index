import unittest
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import ANY, patch

from fastapi import BackgroundTasks, HTTPException

from app.api.openlist import (
    OpenListSelectedSyncRequest,
    OpenListSyncRequest,
    sync_openlist,
    sync_selected_openlist,
)
from app.clients.openlist import OpenListError
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.openlist_sync import (
    _ensure_openlist_directory,
    _list_entries_or_empty,
    _openlist_dir_for_task,
    _openlist_dir_for_save_path,
    _provider_save_path_from_openlist_dir,
    _resolve_or_prepare_openlist_dir,
    run_selected_openlist_sync,
    sync_openlist_episode_dirs,
    sync_selected_openlist_once,
    start_selected_openlist_sync,
    sync_configured_openlist_library,
    sync_selected_tracking_episodes,
    sync_tracking_storage_between_providers,
    sync_tracking_files,
    sync_tracking_fallback_to_p115,
    sync_transfer_outputs,
)


class OpenListSyncTests(unittest.TestCase):
    def test_all_manual_openlist_endpoints_reject_p115_to_quark(self):
        environment = {
            "OPENLIST_QAS_LIBRARY_PATH": "/quark",
            "OPENLIST_P115_LIBRARY_PATH": "/115",
        }
        with patch.dict(os.environ, environment), patch("app.api.openlist.OpenListClient") as client:
            get_settings.cache_clear()
            with self.assertRaises(HTTPException) as legacy_error:
                sync_openlist(OpenListSyncRequest(
                    source_dir="/115/Show",
                    target_dir="/quark/Show",
                    names=["Show.S01E01.mkv"],
                ))
            with self.assertRaises(HTTPException) as selected_error:
                sync_selected_openlist(
                    OpenListSelectedSyncRequest(
                        source_dir="/115/Show",
                        target_dir="/quark/Show",
                        names=["Show.S01E01.mkv"],
                    ),
                    BackgroundTasks(),
                )

        self.assertEqual(422, legacy_error.exception.status_code)
        self.assertEqual(422, selected_error.exception.status_code)
        client.assert_not_called()

    def test_manual_openlist_copy_rejects_paths_outside_configured_mounts(self):
        environment = {
            "OPENLIST_QAS_LIBRARY_PATH": "/quark",
            "OPENLIST_P115_LIBRARY_PATH": "/115",
        }
        with patch.dict(os.environ, environment):
            get_settings.cache_clear()
            with self.assertRaises(HTTPException) as raised:
                sync_selected_openlist(
                    OpenListSelectedSyncRequest(
                        source_dir="/other/Show",
                        target_dir="/115/Show",
                        names=["Show.S01E01.mkv"],
                    ),
                    BackgroundTasks(),
                )

        self.assertEqual(422, raised.exception.status_code)
        self.assertIn("已配置的夸克挂载目录", str(raised.exception.detail))

    def test_season_fallback_does_not_depend_on_global_auto_sync(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
            with patch.dict(
                os.environ,
                {
                    "DB_PATH": str(Path(tempdir) / "fallback.db"),
                    "OPENLIST_ENABLED": "true",
                    "OPENLIST_AUTO_SYNC": "false",
                    "OPENLIST_URL": "http://openlist.test",
                    "OPENLIST_TOKEN": "token",
                    "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                    "OPENLIST_P115_LIBRARY_PATH": "/115",
                    "QUARK_ROOT_PATH": "/strm",
                    "P115_ROOT_PATH": "/媒体库",
                },
            ):
                get_settings.cache_clear()
                init_db()
                with db() as conn:
                    quark_task_id = int(conn.execute(
                        """
                        INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status)
                        VALUES(9,'tv','Show',1,'quark','/strm/tv/Show/Season 1','active')
                        """
                    ).lastrowid)
                    target_task_id = int(conn.execute(
                        """
                        INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status)
                        VALUES(9,'tv','Show',1,'p115','/媒体库/tv/Show/Season 1','active')
                        """
                    ).lastrowid)

                with (
                    patch("app.services.openlist_sync._start_openlist_sync_job", return_value=(44, None)) as start,
                    patch("app.services.openlist_sync._finish_openlist_sync_job"),
                    patch("app.services.openlist_sync._folder_aliases_for_media", return_value=()),
                    patch("app.services.openlist_sync.OpenListClient") as client_class,
                ):
                    client = client_class.return_value

                    def entries(path):
                        if path == "/quark/strm/tv/Show/Season 1":
                            return [
                                {"name": "Show.S01E01.mkv", "is_dir": False},
                                {"name": "Show.S01E02.mkv", "is_dir": False},
                            ]
                        if path == "/115/媒体库/tv/Show/Season 1":
                            return [{"name": "Show.S01E02.mkv", "is_dir": False}]
                        return []

                    client.list_entries.side_effect = entries
                    result = sync_tracking_fallback_to_p115(
                        target_task_id=target_task_id,
                        episode_numbers=[1, 2, 3],
                    )
                    reverse = sync_tracking_fallback_to_p115(
                        target_task_id=quark_task_id,
                        episode_numbers=[1],
                    )

        get_settings.cache_clear()
        self.assertTrue(result["ok"])
        self.assertEqual([1], result["copied"])
        self.assertEqual([2], result["skipped"])
        self.assertEqual([3], result["missing"])
        self.assertEqual(
            [
                {"episode_number": 1, "file_name": "Show.S01E01.mkv"},
                {"episode_number": 2, "file_name": "Show.S01E02.mkv"},
            ],
            result["files"],
        )
        self.assertEqual(target_task_id, result["target_task_id"])
        self.assertFalse(reverse["ok"])
        self.assertIn("115", reverse["message"])
        self.assertEqual(f"openlist:tracking-fallback:{target_task_id}:1,2,3", start.call_args.args[0])
        client.copy.assert_called_once_with(
            "/quark/strm/tv/Show/Season 1",
            "/115/媒体库/tv/Show/Season 1",
            ["Show.S01E01.mkv"],
            overwrite=False,
        )

    def test_manual_tracking_sync_is_one_way_to_p115(self):
        with patch.dict(os.environ, {"OPENLIST_ENABLED": "true"}):
            get_settings.cache_clear()
            init_db()
            test_tmdb_id = 930000000 + int(time.time() * 1000) % 60000000
            with db() as conn:
                quark_id = int(conn.execute(
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,status) VALUES(?,'tv','One Way',1,'quark','active')",
                    (test_tmdb_id,),
                ).lastrowid)
                p115_id = int(conn.execute(
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,status) VALUES(?,'tv','One Way',1,'p115','active')",
                    (test_tmdb_id,),
                ).lastrowid)
                conn.executemany(
                    """
                    INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,provider,air_date)
                    VALUES(?,1,?,?, 'p115',?)
                    """,
                    [
                        (p115_id, 1, "pending", ""),
                        (p115_id, 2, "pending", "2999-01-01"),
                        (p115_id, 3, "saved", ""),
                    ],
                )
            with patch(
                "app.services.openlist_sync.sync_selected_tracking_episodes",
                return_value={"ok": True, "copied": [1]},
            ) as selected:
                result = sync_tracking_storage_between_providers(quark_id)

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["copied"])
        self.assertEqual(1, result["scanned"])
        self.assertEqual([1], result["copied_episodes"])
        selected.assert_called_once_with(p115_id, [1])

    def test_cross_provider_transfer_maps_relative_path_to_target_root(self):
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
            save_path = "/strm/01电影/蜘蛛侠：英雄无归 (2021)"
            self.assertEqual(
                "/115/媒体库/01电影/蜘蛛侠：英雄无归 (2021)",
                _openlist_dir_for_save_path(save_path, "p115", settings, source_provider="qas"),
            )
            self.assertEqual(
                "/夸克/strm/01电影/蜘蛛侠：英雄无归 (2021)",
                _openlist_dir_for_save_path("/媒体库/01电影/蜘蛛侠：英雄无归 (2021)", "qas", settings, source_provider="p115"),
            )

    def test_openlist_p115_mount_maps_back_to_native_save_path(self):
        try:
            with patch.dict(
                os.environ,
                {
                    "OPENLIST_P115_LIBRARY_PATH": "/115/媒体库",
                    "P115_ROOT_PATH": "/媒体库",
                },
            ):
                get_settings.cache_clear()
                settings = get_settings()
                self.assertEqual(
                    "/媒体库/03电视剧/示例剧/Season 1",
                    _provider_save_path_from_openlist_dir(
                        "/115/媒体库/03电视剧/示例剧/Season 1",
                        "p115",
                        settings,
                    ),
                )
        finally:
            get_settings.cache_clear()
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
                patch("app.services.openlist_sync.sync_tracking_files", return_value={"ok": True, "copied": 1, "skipped": 0}) as sync_files,
            ):
                client_class.return_value.list_entries.return_value = [
                    {"name": "Show.S01E01.mkv", "is_dir": False},
                    {"name": "Season 1", "is_dir": True},
                ]
                result = sync_transfer_outputs("qas", "/strm/tv/Show", [])

        self.assertEqual([{"ok": True, "job_id": ANY, "message": ANY, "copied": 1, "skipped": 0}], result)
        sync_files.assert_called_once_with(
            {"provider": "qas", "save_path": "/strm/tv/Show", "tmdb_id": None, "media_type": "", "season_number": None},
            "p115",
            ["Show.S01E01.mkv"],
        )
        with db() as conn:
            job = conn.execute(
                "SELECT provider,status,stage,save_path FROM transfer_jobs WHERE id=?",
                (result[0]["job_id"],),
            ).fetchone()
        self.assertEqual(("openlist", "done", "openlist_sync_done", "/strm/tv/Show"), tuple(job))

    def test_auto_transfer_sync_waits_for_native_115_before_post_processing(self):
        landed = [{"file_id": "115-1", "parent_id": "dir-1", "file_name": "Movie.mkv", "path": "/media/Movie.mkv", "size": 10}]
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "P115_ROOT_PATH": "/media",
                "ENABLED_CLOUD_PROVIDERS": "qas,p115",
            },
        ):
            get_settings.cache_clear()
            with (
                patch("app.services.openlist_sync.sync_tracking_files", return_value={"ok": True, "copied": 1, "skipped": 0, "target_dir": "/115/Movie"}),
                patch("app.services.openlist_sync.organizer_provider") as organizer,
                patch("app.services.openlist_sync._wait_for_openlist_p115_landing", return_value=("/media/Movie", landed)) as wait_for_landing,
                patch("app.services.openlist_sync.run_post_transfer_pipeline", return_value=True) as pipeline,
                patch("app.services.openlist_sync._openlist_post_processing_summary", return_value="STRM 已生成"),
            ):
                organizer.return_value.configured.return_value = True
                result = sync_transfer_outputs("qas", "/strm/Movie", ["Movie.mkv"], display_title="Movie")

        self.assertTrue(result[0]["ok"])
        self.assertEqual(1, result[0]["landed"])
        wait_for_landing.assert_called_once()
        pipeline.assert_called_once_with(
            result[0]["job_id"], provider="p115", title="Movie", openlist_message="115 已精确确认 1 个媒体文件落盘",
            target_path="/media/Movie", target_files=landed,
        )

    def test_auto_sync_uses_configured_opposite_mount_without_native_provider_enablement(self):
        init_db()
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "ENABLED_CLOUD_PROVIDERS": "qas",
            },
        ):
            get_settings.cache_clear()
            with (
                patch("app.services.openlist_sync.sync_tracking_files", return_value={"ok": True, "copied": 1, "skipped": 0, "target_dir": "/115/tv/Show"}) as sync_files,
                patch("app.services.openlist_sync._wait_for_openlist_p115_landing") as wait_for_landing,
                patch("app.services.openlist_sync.run_post_transfer_pipeline") as pipeline,
            ):
                result = sync_transfer_outputs("qas", "/strm/tv/Show", ["Show.S01E01.mkv"])

        self.assertEqual(1, len(result))
        self.assertTrue(result[0]["ok"])
        wait_for_landing.assert_not_called()
        pipeline.assert_not_called()
        sync_files.assert_called_once_with(
            {"provider": "qas", "save_path": "/strm/tv/Show", "tmdb_id": None, "media_type": "", "season_number": None},
            "p115",
            ["Show.S01E01.mkv"],
        )

    def test_native_quark_fallback_uses_the_existing_quark_openlist_mount(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_AUTO_SYNC_DIRECTION": "qas_to_p115",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QUARK_ROOT_PATH": "/quark-media",
                "ENABLED_CLOUD_PROVIDERS": "quark,p115",
            },
        ):
            get_settings.cache_clear()
            with patch("app.services.openlist_sync.sync_tracking_files", return_value={"ok": True, "copied": 1, "skipped": 0}) as sync_files:
                result = sync_transfer_outputs("quark", "/quark-media/tv/Show", ["Show.S01E01.mkv"], target_providers=("p115",))

        self.assertEqual(1, len(result))
        sync_files.assert_called_once_with(
            {"provider": "quark", "save_path": "/quark-media/tv/Show", "tmdb_id": None, "media_type": "", "season_number": None},
            "p115",
            ["Show.S01E01.mkv"],
        )

    def test_one_way_auto_sync_skips_the_reverse_provider(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_AUTO_SYNC_DIRECTION": "qas_to_p115",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
            },
        ):
            get_settings.cache_clear()
            with patch("app.services.openlist_sync.OpenListClient") as client_class:
                result = sync_transfer_outputs("p115", "/media/tv/Show", ["Show.S01E01.mkv"])

        self.assertEqual([], result)
        client_class.assert_not_called()

    def test_transfer_output_batches_all_files_into_one_copy_request(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "P115_ROOT_PATH": "/媒体库",
            },
        ):
            get_settings.cache_clear()
            with patch("app.services.openlist_sync.OpenListClient") as client_class:
                client = client_class.return_value
                client.list_entries.return_value = []
                result = sync_tracking_files(
                    {"provider": "qas", "save_path": "/strm/tv/Show", "tmdb_id": None, "media_type": "", "season_number": 1},
                    "p115",
                    ["Show.S01E01.mkv", "Show.S01E02.mkv"],
                )

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["submitted"])
        client.copy.assert_called_once_with(
            "/quark/strm/tv/Show",
            "/115/媒体库/tv/Show",
            ["Show.S01E01.mkv", "Show.S01E02.mkv"],
            overwrite=False,
        )

    def test_transfer_output_discovers_renamed_files_before_batch_copy(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "P115_ROOT_PATH": "/濯掍綋搴?",
            },
        ):
            get_settings.cache_clear()
            with patch("app.services.openlist_sync.OpenListClient") as client_class:
                client = client_class.return_value
                source_entries = [
                    {"name": "Show.2026.S01E01.mkv", "is_dir": False},
                    {"name": "Show.2026.S01E02.mkv", "is_dir": False},
                ]

                def list_entries(path):
                    if path == "/quark/strm/tv/Show":
                        return source_entries
                    if path == "/115/濯掍綋搴?tv/Show":
                        raise OpenListError("object not found")
                    return []

                client.list_entries.side_effect = list_entries
                result = sync_tracking_files(
                    {"provider": "qas", "save_path": "/strm/tv/Show", "media_type": "tv"},
                    "p115",
                    [],
                )

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["submitted"])
        client.copy.assert_called_once_with(
            "/quark/strm/tv/Show",
            result["target_dir"],
            ["Show.2026.S01E01.mkv", "Show.2026.S01E02.mkv"],
            overwrite=False,
        )

    def test_transfer_output_creates_missing_season_and_copies_only_requested_files(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "P115_ROOT_PATH": "/媒体库",
            },
        ):
            get_settings.cache_clear()
            with patch("app.services.openlist_sync.OpenListClient") as client_class:
                client = client_class.return_value

                def entries(path):
                    if path == "/quark/strm/tv/Show/Season 1":
                        return [{"name": "Show.S01E01.mkv", "is_dir": False}]
                    if path == "/115/媒体库/tv/Show/Season 1":
                        raise OpenListError("object not found")
                    return []

                client.list_entries.side_effect = entries
                result = sync_tracking_files(
                    {"provider": "qas", "save_path": "/strm/tv/Show/Season 1", "tmdb_id": None, "media_type": "", "season_number": 1},
                    "p115",
                    ["Show.S01E01.mkv"],
                )

        self.assertTrue(result["ok"])
        self.assertNotIn("directory_copy", result)
        client.mkdir.assert_called_once_with("/115/媒体库/tv/Show/Season 1")
        client.copy.assert_called_once_with(
            "/quark/strm/tv/Show/Season 1",
            "/115/媒体库/tv/Show/Season 1",
            ["Show.S01E01.mkv"],
            overwrite=False,
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
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status) VALUES(?,'tv','OpenList Selected Sync',1,'p115','/strm/tv/OpenList Selected Sync','active')",
                    (test_tmdb_id,),
                ).lastrowid
                conn.execute(
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status) VALUES(?,'tv','OpenList Selected Sync',1,'qas','/strm/tv/OpenList Selected Sync','active')",
                    (test_tmdb_id,),
                )
            with patch("app.services.openlist_sync.OpenListClient") as client_class:
                client = client_class.return_value

                def entries(path):
                    if path == "/quark/strm/tv/OpenList Selected Sync":
                        return [{"name": "OpenList Selected Sync.S01E01.mkv", "is_dir": False}]
                    if path == "/115/strm/tv/OpenList Selected Sync":
                        return []
                    return []

                client.list_entries.side_effect = entries
                result = sync_selected_tracking_episodes(int(target_id), [1])

        self.assertTrue(result["ok"])
        self.assertEqual([1], result["copied"])
        client.copy.assert_called_once_with(
            "/quark/strm/tv/OpenList Selected Sync",
            "/115/strm/tv/OpenList Selected Sync",
            ["OpenList Selected Sync.S01E01.mkv"],
            overwrite=False,
        )

    def test_selected_tracking_sync_does_not_require_a_quark_tracking_task(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QUARK_ROOT_PATH": "/strm",
                "P115_ROOT_PATH": "/媒体库",
            },
        ):
            get_settings.cache_clear()
            init_db()
            test_tmdb_id = 920000000 + int(time.time() * 1000) % 70000000
            with db() as conn:
                target_id = conn.execute(
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status) VALUES(?,'tv','No Sibling',1,'p115','/媒体库/tv/No Sibling/Season 1','active')",
                    (test_tmdb_id,),
                ).lastrowid
            with patch("app.services.openlist_sync.OpenListClient") as client_class:
                client = client_class.return_value

                def entries(path):
                    if path == "/quark/strm/tv/No Sibling/Season 1":
                        return [{"name": "No Sibling.S01E01.mkv", "is_dir": False}]
                    if path == "/115/媒体库/tv/No Sibling/Season 1":
                        return []
                    return []

                client.list_entries.side_effect = entries
                result = sync_selected_tracking_episodes(int(target_id), [1])

        self.assertTrue(result["ok"])
        self.assertEqual([1], result["copied"])
        client.copy.assert_called_once_with(
            "/quark/strm/tv/No Sibling/Season 1",
            "/115/媒体库/tv/No Sibling/Season 1",
            ["No Sibling.S01E01.mkv"],
            overwrite=False,
        )

    def test_selected_tracking_sync_falls_back_to_native_quark_source_listing(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_QAS_LIBRARY_PATH": "/quark",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
                "QAS_SAVE_PATH": "/strm",
                "QUARK_ROOT_PATH": "/strm",
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
                    "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path,status) VALUES(?,'tv','Native Fallback',1,'quark','/strm/tv/Native Fallback','active')",
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
        provider_factory.assert_called_once_with("quark")
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

    def test_selected_copy_waits_for_115_landing_then_runs_strm_and_emby_pipeline(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_P115_LIBRARY_PATH": "/115/媒体库",
                "P115_ROOT_PATH": "/媒体库",
            },
        ):
            get_settings.cache_clear()
            started = start_selected_openlist_sync(
                "/夸克/媒体库/电影",
                "/115/媒体库/电影",
                ["Movie.mkv"],
            )
            landed = [{
                "file_id": "115-file",
                "parent_id": "115-parent",
                "file_name": "Movie.mkv",
                "path": "/媒体库/电影/Movie.mkv",
                "size": 1024,
            }]
            with (
                patch("app.services.openlist_sync.OpenListClient") as client_class,
                patch(
                    "app.services.openlist_sync._wait_for_openlist_p115_landing",
                    return_value=("/媒体库/电影", landed),
                ) as wait_for_landing,
                patch("app.services.openlist_sync.run_post_transfer_pipeline", return_value=True) as pipeline,
                patch("app.services.openlist_sync._openlist_post_processing_summary", return_value="STRM 已生成并等待 Emby Webhook"),
            ):
                result = run_selected_openlist_sync(
                    int(started["job_id"]),
                    "/夸克/媒体库/电影",
                    "/115/媒体库/电影",
                    ["Movie.mkv"],
                )

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["landed"])
        wait_for_landing.assert_called_once()
        pipeline.assert_called_once_with(
            int(started["job_id"]),
            provider="p115",
            title="OpenList 手动同步",
            openlist_message="115 已精确确认 1 个媒体文件落盘",
            target_path="/媒体库/电影",
            target_files=landed,
        )
        client_class.return_value.copy.assert_called_once_with(
            "/夸克/媒体库/电影",
            "/115/媒体库/电影",
            ["Movie.mkv"],
            overwrite=False,
        )
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (started["job_id"],)).fetchone()
        self.assertEqual("done", row["status"])
        self.assertEqual("openlist_post_processing_done", row["stage"])
        self.assertIn("STRM 已生成", row["message"])

    def test_manual_selected_sync_ignores_auto_sync_direction(self):
        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_AUTO_SYNC_DIRECTION": "qas_to_p115",
            },
        ):
            get_settings.cache_clear()
            with patch("app.services.openlist_sync.OpenListClient") as client_class:
                result = sync_selected_openlist_once("/115/Show", "/quark/Show", ["Show.S01E01.mkv"])

        self.assertTrue(result["ok"])
        client_class.return_value.copy.assert_called_once_with(
            "/115/Show",
            "/quark/Show",
            ["Show.S01E01.mkv"],
            overwrite=False,
        )


if __name__ == "__main__":
    unittest.main()
