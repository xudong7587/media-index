import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.deletion_workflow import confirm_deletion, request_deletion_for_strm, request_deletions_for_strm_path
from app.services.media_assets import AssetInput, get_asset, register_asset
from app.api.emby import _emby_deleted_strm_name, _process_emby_webhook, router as emby_router


class FakeP115:
    def configured(self):
        return True

    def trash_file(self, file_id):
        self.deleted = file_id


class DeletionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db"), "STRM_OUTPUT_ROOT": "/strm"})
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
            log = conn.execute("SELECT provider,status,stage,message FROM transfer_jobs WHERE execution_key=?", (f"deletion:{intent['id']}",)).fetchone()
        self.assertEqual(("deletion", "done", "deletion_completed", "115 已确认移入回收站，STRM 映射已标记移除"), tuple(log))

    def test_unknown_strm_name_never_falls_back_to_filename_matching(self):
        with self.assertRaisesRegex(Exception, "精确"):
            request_deletion_for_strm("Some-Other-Movie.strm", trigger_source="emby_webhook")

    def test_exact_strm_mapping_tolerates_case_and_unicode_normalization(self):
        with db() as conn:
            conn.execute("UPDATE strm_entries SET relative_path=? WHERE asset_id=?", ("电影/Café/MOVIE.strm", self.asset["id"]))

        intent = request_deletion_for_strm("电影/Cafe\u0301/movie.strm", trigger_source="emby_webhook")

        self.assertEqual(self.asset["id"], intent["asset_id"])

    def test_exact_pending_remove_mapping_still_uses_stable_file_id(self):
        with db() as conn:
            conn.execute(
                "UPDATE strm_entries SET status='pending_remove',missing_scan_count=1 WHERE asset_id=?",
                (self.asset["id"],),
            )

        intent = request_deletion_for_strm("Movie.strm", trigger_source="emby_webhook")

        self.assertEqual(self.asset["id"], intent["asset_id"])

    def test_directory_path_creates_one_exact_intent_per_ready_p115_mapping(self):
        with db() as conn:
            conn.execute("UPDATE strm_entries SET relative_path=? WHERE asset_id=?", ("剧集/Season 01/E01.strm", self.asset["id"]))
        second = register_asset(AssetInput(provider="p115", file_id="episode-2", name="E02.mkv", size=100, status="ready"))
        with db() as conn:
            conn.execute("INSERT INTO strm_entries(asset_id,library_root_id,relative_path,content_version,status) VALUES(?,?,?,?,?)", (second["id"], "default", "剧集/Season 01/E02.strm", "v1", "ready"))

        intents = request_deletions_for_strm_path("剧集", trigger_source="emby_webhook", trigger_ref="series-delete")

        self.assertEqual({self.asset["id"], second["id"]}, {intent["asset_id"] for intent in intents})
        self.assertTrue(all(intent["state"] == "requested" for intent in intents))

    def test_directory_path_never_crosses_strm_library_roots(self):
        with db() as conn:
            conn.execute("UPDATE strm_entries SET relative_path=? WHERE asset_id=?", ("剧集/E01.strm", self.asset["id"]))
        second = register_asset(AssetInput(provider="p115", file_id="other-root-file", name="E02.mkv", size=100, status="ready"))
        with db() as conn:
            conn.execute("INSERT INTO strm_entries(asset_id,library_root_id,relative_path,content_version,status) VALUES(?,?,?,?,?)", (second["id"], "other-root", "剧集/E02.strm", "v1", "ready"))

        with self.assertRaisesRegex(Exception, "同一个 STRM 库"):
            request_deletions_for_strm_path("剧集", trigger_source="emby_webhook")

    def test_standard_emby_json_extracts_deleted_strm_path(self):
        payload = {"Event": "item.deleted", "Item": {"Path": "/strm/电影/Movie.strm"}}
        self.assertEqual("电影/Movie.strm", _emby_deleted_strm_name(payload))

    def test_emby_visible_library_root_can_differ_from_mediaindex_output_root(self):
        with patch.dict(os.environ, {"EMBY_STRM_LIBRARY_ROOT": "/media/神医助手/STRM"}, clear=False):
            get_settings.cache_clear()
            payload = {"NotificationType": "ItemRemoved", "ItemPath": "/media/神医助手/STRM/电影/Movie.strm"}

            self.assertEqual("电影/Movie.strm", _emby_deleted_strm_name(payload))

    def test_emby_library_location_accepts_directory_delete(self):
        with patch("app.api.emby._read_emby_json", return_value=[{"ItemId": "library-1", "Locations": ["/emby/strm"]}]):
            self.assertEqual("剧集/Season 01", _emby_deleted_strm_name({"NotificationType": "ItemRemoved", "ItemPath": "/emby/strm/剧集/Season 01"}))

    def test_explicit_common_root_wins_over_more_specific_emby_library_location(self):
        payload = {"NotificationType": "ItemRemoved", "ItemPath": "/strm/02系列电影/电影/Movie.strm"}
        with patch("app.api.emby._read_emby_json", return_value=[{"Locations": ["/strm/02系列电影"]}]):
            relative = _emby_deleted_strm_name(payload)

        self.assertEqual("02系列电影/电影/Movie.strm", relative)

    def test_windows_emby_visible_library_root_is_supported(self):
        with patch.dict(os.environ, {"EMBY_STRM_LIBRARY_ROOT": "D:/媒体库/STRM"}, clear=False):
            get_settings.cache_clear()

            self.assertEqual("电影/Movie.strm", _emby_deleted_strm_name({"FilePath": r"D:\媒体库\STRM\电影\Movie.strm"}))

    def test_absolute_webhook_path_outside_emby_library_root_is_rejected(self):
        with patch.dict(os.environ, {"EMBY_STRM_LIBRARY_ROOT": "/media/strm"}, clear=False):
            get_settings.cache_clear()
            with self.assertRaisesRegex(Exception, "Emby 媒体库根目录"):
                _emby_deleted_strm_name({"ItemPath": "/unrelated/strm/Movie.strm"})

    def test_full_strm_path_selects_same_named_file_in_exact_directory(self):
        with db() as conn:
            conn.execute("UPDATE strm_entries SET relative_path=? WHERE asset_id=?", ("电影/Movie.strm", self.asset["id"]))
        other = register_asset(AssetInput(provider="p115", file_id="other-file", name="Movie.mkv", size=100, status="ready"))
        with db() as conn:
            conn.execute("INSERT INTO strm_entries(asset_id,library_root_id,relative_path,content_version,status) VALUES(?,?,?,?,?)", (other["id"], "default", "电视剧/Movie.strm", "v1", "ready"))

        intent = request_deletion_for_strm(_emby_deleted_strm_name({"Item": {"Path": "/strm/电影/Movie.strm"}}), trigger_source="emby_webhook")

        self.assertEqual(self.asset["id"], intent["asset_id"])

    def test_ambiguous_path_across_library_roots_never_chooses_a_file_id(self):
        other = register_asset(AssetInput(provider="p115", file_id="other-file", name="Movie.mkv", size=100, status="ready"))
        with db() as conn:
            conn.execute("INSERT INTO strm_entries(asset_id,library_root_id,relative_path,content_version,status) VALUES(?,?,?,?,?)", (other["id"], "other-root", "Movie.strm", "v1", "ready"))

        with self.assertRaisesRegex(Exception, "唯一"):
            request_deletion_for_strm("Movie.strm", trigger_source="emby_webhook")

    def test_emby_json_without_strm_path_is_rejected(self):
        with self.assertRaisesRegex(Exception, "STRM"):
            _emby_deleted_strm_name({"Item": {"Path": "/media/Movie.mkv"}})

    def test_delete_event_with_unusable_path_reports_configuration_error(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False), patch(
            "app.api.emby.send_configured_channels",
            return_value=[],
        ):
            get_settings.cache_clear()
            payload = {"NotificationType": "ItemRemoved", "ItemPath": "/wrong-root/Movie.strm"}
            first = _process_emby_webhook(payload, x_mediaindex_webhook="", token="url-secret")
            second = _process_emby_webhook(payload, x_mediaindex_webhook="", token="url-secret")

        self.assertEqual("rejected", first["state"])
        self.assertIn("Emby 媒体库根目录", first["message"])
        self.assertEqual("duplicate", second["state"])
        self.assertIn("已忽略", second["message"])
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE request_source='emby_webhook'").fetchone()[0]
        self.assertEqual(1, count)

    def test_repeated_successful_delete_event_does_not_create_another_intent(self):
        with patch.dict(
            os.environ,
            {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret", "EMBY_DELETION_AUTO_CONFIRM": "false"},
            clear=False,
        ):
            get_settings.cache_clear()
            payload = {
                "NotificationType": "ItemRemoved",
                "NotificationId": "same-delete-event",
                "ItemPath": "/strm/Movie.strm",
            }
            first = _process_emby_webhook(payload, x_mediaindex_webhook="", token="url-secret")
            second = _process_emby_webhook(payload, x_mediaindex_webhook="", token="url-secret")

        self.assertEqual("requested", first["state"])
        self.assertEqual("duplicate", second["state"])
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM deletion_intents WHERE trigger_ref='same-delete-event'").fetchone()[0]
        self.assertEqual(1, count)

    def test_emby_webhook_accepts_token_in_complete_url(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False), patch(
            "app.api.emby.request_deletions_for_strm_path",
            return_value=[{"id": 17, "state": "requested"}],
        ):
            get_settings.cache_clear()
            result = _process_emby_webhook(
                {"Event": "item.deleted", "Item": {"Path": "/strm/电影/Movie.strm"}},
                x_mediaindex_webhook="",
                token="url-secret",
            )

        self.assertEqual({"ok": True, "intent_id": 17, "intent_ids": [17], "count": 1, "state": "requested", "channels": []}, result)

    def test_emby_webhook_rejects_wrong_url_token(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False):
            get_settings.cache_clear()
            with self.assertRaises(HTTPException) as raised:
                _process_emby_webhook(
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
            result = _process_emby_webhook(
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

    def test_emby_library_events_are_aggregated_by_series(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False):
            get_settings.cache_clear()
            first = _process_emby_webhook(
                {"Event": "item.added", "Item": {"Name": "E01", "SeriesId": "series-7", "SeriesName": "测试剧"}},
                x_mediaindex_webhook="",
                token="url-secret",
            )
            second = _process_emby_webhook(
                {"Event": "item.added", "Item": {"Name": "E02", "SeriesId": "series-7", "SeriesName": "测试剧"}},
                x_mediaindex_webhook="",
                token="url-secret",
            )
        self.assertEqual("queued", first["state"])
        self.assertEqual("aggregated", second["state"])
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM notifications WHERE source_key LIKE 'library-ready:emby:%'").fetchone()[0]
        self.assertEqual(1, count)

    def test_emby_non_delete_event_is_relayed_without_strm_path(self):
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False), patch(
            "app.api.emby.add_notification",
            return_value=True,
        ) as add:
            get_settings.cache_clear()
            result = _process_emby_webhook(
                {"Event": "playback.start", "Item": {"Name": "Movie"}, "User": {"Name": "Sunny"}},
                x_mediaindex_webhook="",
                token="url-secret",
            )

        self.assertEqual({"ok": True, "state": "notified", "channels": []}, result)
        add.assert_called_once()
        self.assertTrue(add.call_args.args[0].startswith("emby-playback:"))

    def test_emby_playback_notification_uses_readable_moviepilot_style_fields(self):
        from app.api.emby import _emby_notification_message, _emby_notification_title

        payload = {
            "Event": "playback.stop",
            "UserName": "root",
            "DeviceName": "Emby for Android",
            "RemoteEndPoint": "192.0.2.10",
            "Item": {
                "Name": "探险者来了",
                "SeriesName": "敦煌",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "PlaybackPositionTicks": 360_000,
                "RunTimeTicks": 100_000_000,
                "Overview": "一段用于通知卡片的剧情简介。",
            },
        }

        self.assertEqual("停止播放 · 敦煌 S1E1 探险者来了", _emby_notification_title(payload))
        message = _emby_notification_message(payload)
        self.assertIn("用户：root", message)
        self.assertIn("设备：Emby for Android", message)
        self.assertIn("地址：192.0.2.10", message)
        self.assertIn("进度：0.4%", message)
        self.assertIn("简介：一段用于通知卡片", message)

    def test_emby_notification_prefers_landscape_backdrop_and_item_identity(self):
        from app.api.emby import _cache_emby_notification_poster

        jpeg = b"\xff\xd8\xff" + b"poster"
        with (
            patch("app.api.emby._read_emby_bytes", return_value=jpeg) as read,
            patch("app.api.emby.cache_poster_bytes", return_value="cached-key") as cache,
        ):
            key = _cache_emby_notification_poster({"Id": "event-id", "Item": {"Id": "media-id"}})

        self.assertEqual("cached-key", key)
        self.assertIn("/Items/media-id/Images/Backdrop/0", read.call_args.args[0])
        cache.assert_called_once_with("emby:media-id:backdrop", jpeg)

    def test_emby_multipart_data_field_reaches_notification_relay(self):
        app = FastAPI()
        app.include_router(emby_router)
        with patch.dict(os.environ, {"EMBY_DELETION_WEBHOOK_TOKEN": "url-secret"}, clear=False), patch(
            "app.api.emby.send_configured_channels",
            return_value=[],
        ) as notify:
            get_settings.cache_clear()
            with TestClient(app) as client:
                response = client.post(
                    "/api/integrations/emby/strm-deleted?token=url-secret",
                    files={"data": (None, json.dumps({"Event": "system.notificationtest", "Server": {"Name": "Emby"}}), "application/json")},
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual("notified", response.json()["state"])
        notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
