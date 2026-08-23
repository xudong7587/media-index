import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.deletion_workflow import confirm_deletion, request_deletion_for_strm
from app.services.media_assets import AssetInput, get_asset, register_asset
from app.api.emby import _emby_deleted_strm_name


class FakeP115:
    def configured(self):
        return True

    def trash_file(self, file_id):
        self.deleted = file_id


class DeletionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db")})
        self.environment.start()
        get_settings.cache_clear()
        init_db()
        self.asset = register_asset(AssetInput(provider="p115", file_id="exact-file", name="Movie.mkv", size=100, status="ready"))
        with db() as conn:
            conn.execute("INSERT INTO strm_entries(asset_id,library_root_id,relative_path,content_version,status) VALUES(?,?,?,?,?)", (self.asset["id"], "default", "Movie.strm", "v1", "ready"))

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_exact_strm_mapping_creates_intent_then_trashes_only_that_asset(self):
        intent = request_deletion_for_strm("Movie.strm", trigger_source="emby_webhook", trigger_ref="event-1")
        client = FakeP115()

        done = confirm_deletion(intent["id"], p115_client=client)

        self.assertEqual("exact-file", client.deleted)
        self.assertEqual("completed", done["state"])
        self.assertEqual("deleted", get_asset(self.asset["id"])["status"])
        with db() as conn:
            self.assertEqual("removed", conn.execute("SELECT status FROM strm_entries WHERE asset_id=?", (self.asset["id"],)).fetchone()[0])

    def test_unknown_strm_name_never_falls_back_to_filename_matching(self):
        with self.assertRaisesRegex(Exception, "精确"):
            request_deletion_for_strm("Some-Other-Movie.strm", trigger_source="emby_webhook")

    def test_standard_emby_json_extracts_deleted_strm_path(self):
        payload = {"Event": "item.deleted", "Item": {"Path": "/strm/电影/Movie.strm"}}
        self.assertEqual("Movie.strm", _emby_deleted_strm_name(payload))

    def test_emby_json_without_strm_path_is_rejected(self):
        with self.assertRaisesRegex(Exception, "STRM"):
            _emby_deleted_strm_name({"Item": {"Path": "/media/Movie.mkv"}})


if __name__ == "__main__":
    unittest.main()
