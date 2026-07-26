import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.clients.openlist import OpenListError
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.openlist_sync import (
    _ensure_openlist_directory,
    _list_entries_or_empty,
    _resolve_or_prepare_openlist_dir,
    sync_openlist_episode_dirs,
    sync_selected_openlist_once,
)


class OpenListSyncTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
