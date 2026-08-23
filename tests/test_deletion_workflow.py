import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.deletion_workflow import confirm_deletion, request_deletion_for_strm
from app.services.media_assets import AssetInput, get_asset, register_asset
from app.api.emby import _emby_deleted_strm_name, emby_strm_deleted


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

    def test_emby_webhook_accepts_token_in_complete_url(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False), patch(
            "app.api.emby.request_deletion_for_strm",
            return_value={"id": 17, "state": "requested"},
        ):
            get_settings.cache_clear()
            result = emby_strm_deleted(
                {"Event": "item.deleted", "Item": {"Path": "/strm/电影/Movie.strm"}},
                x_mediaindex_webhook="",
                token="url-secret",
            )

        self.assertEqual({"ok": True, "intent_id": 17, "state": "requested", "channels": []}, result)

    def test_emby_webhook_rejects_wrong_url_token(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False):
            get_settings.cache_clear()
            with self.assertRaises(HTTPException) as raised:
                emby_strm_deleted(
                    {"Event": "item.deleted", "Item": {"Path": "/strm/电影/Movie.strm"}},
                    x_mediaindex_webhook="",
                    token="wrong",
                )

        self.assertEqual(401, raised.exception.status_code)

    def test_emby_webhook_test_event_validates_without_strm_path(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False), patch(
            "app.api.emby.send_configured_channels",
            return_value=[],
        ) as notify:
            get_settings.cache_clear()
            result = emby_strm_deleted(
                {"Event": "system.notificationtest", "Server": {"Name": "Emby"}},
                x_mediaindex_webhook="",
                token="url-secret",
            )

        self.assertEqual({"ok": True, "test": True, "state": "notified", "channels": []}, result)
        notify.assert_called_once_with(
            "Emby 通知测试",
            "已收到来自 Emby 的测试 Webhook，MediaIndex 通知中继正常。",
            "settings-notifications",
            force=True,
        )

    def test_emby_non_delete_event_is_relayed_without_strm_path(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False), patch(
            "app.api.emby.send_configured_channels",
            return_value=[],
        ) as notify:
            get_settings.cache_clear()
            result = emby_strm_deleted(
                {"Event": "playback.start", "Item": {"Name": "Movie"}, "User": {"Name": "Sunny"}},
                x_mediaindex_webhook="",
                token="url-secret",
            )

        self.assertEqual({"ok": True, "state": "notified", "channels": []}, result)
        notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
