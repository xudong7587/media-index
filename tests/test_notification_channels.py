import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services import notification_channels
from app.services.notification_channels import (
    ChannelResult,
    send_configured_channels,
    send_telegram,
    send_wecom,
    send_wecom_app,
    send_wecom_app_news,
    sync_interaction_shortcuts,
)
from app.services.notifications import add_notification, sync_transfer_notifications
from app.main import restore_interaction_shortcuts


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self.stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self):
        return self.stream.read()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class NotificationChannelTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "NOTIFICATION_EXTERNAL_ENABLED": "true",
                "NOTIFICATION_ENABLED_AT": "2020-01-01T00:00:00+00:00",
                "TELEGRAM_ENABLED": "true",
                "TELEGRAM_BOT_TOKEN": "bot-token",
                "TELEGRAM_CHAT_ID": "-100123",
                "WECOM_ENABLED": "true",
                "WECOM_KEY": "wecom-key",
                "WECOM_APP_ENABLED": "true",
                "WECOM_CORP_ID": "ww-corp",
                "WECOM_APP_SECRET": "app-secret",
                "WECOM_APP_AGENT_ID": "1000002",
                "WECOM_APP_TO_USER": "sunny|alex",
                "INTERACTION_SHORTCUTS_JSON": '["strm_full","strm_incremental","strm_directory","tracking","wishlist","status","review"]',
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        notification_channels._TOKEN_CACHE.clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        notification_channels._TOKEN_CACHE.clear()
        self.tempdir.cleanup()

    def test_telegram_uses_bot_api_and_chat_id(self):
        captured = {}

        def requester(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = request.data.decode()
            captured["timeout"] = timeout
            return FakeResponse({"ok": True})

        result = send_telegram("hello", requester)

        self.assertTrue(result.ok)
        self.assertEqual("https://api.telegram.org/botbot-token/sendMessage", captured["url"])
        self.assertIn("chat_id=-100123", captured["body"])

    def test_telegram_buttons_are_sent_as_inline_keyboard(self):
        captured = {}

        def requester(request, timeout):
            captured["body"] = request.data.decode()
            return FakeResponse({"ok": True})

        result = send_telegram(
            "choose",
            requester,
            reply_markup=[[{"text": "1. 电影", "callback_data": "mi:choice:1"}]],
        )

        self.assertTrue(result.ok)
        self.assertIn("reply_markup=", captured["body"])
        self.assertIn("mi%3Achoice%3A1", captured["body"])

    def test_wecom_uses_group_robot_key(self):
        captured = {}

        def requester(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            return FakeResponse({"errcode": 0, "errmsg": "ok"})

        result = send_wecom("hello", requester)

        self.assertTrue(result.ok)
        self.assertIn("key=wecom-key", captured["url"])
        self.assertEqual("hello", captured["body"]["text"]["content"])

    def test_wecom_custom_app_gets_token_and_sends_to_members(self):
        requests = []

        def requester(request, timeout):
            requests.append(request)
            if "gettoken" in request.full_url:
                return FakeResponse({"errcode": 0, "errmsg": "ok", "access_token": "token-1", "expires_in": 7200})
            return FakeResponse({"errcode": 0, "errmsg": "ok"})

        result = send_wecom_app("hello", requester)

        self.assertTrue(result.ok)
        self.assertEqual(2, len(requests))
        self.assertIn("corpid=ww-corp", requests[0].full_url)
        self.assertNotIn("app-secret", requests[1].full_url)
        self.assertIn("access_token=token-1", requests[1].full_url)
        payload = json.loads(requests[1].data)
        self.assertEqual("sunny|alex", payload["touser"])
        self.assertEqual(1000002, payload["agentid"])
        self.assertEqual("hello", payload["text"]["content"])

    def test_wecom_custom_app_refreshes_an_expired_token(self):
        responses = iter(
            [
                {"errcode": 0, "errmsg": "ok", "access_token": "token-old", "expires_in": 7200},
                {"errcode": 42001, "errmsg": "access_token expired"},
                {"errcode": 0, "errmsg": "ok", "access_token": "token-new", "expires_in": 7200},
                {"errcode": 0, "errmsg": "ok"},
            ]
        )
        urls = []

        def requester(request, timeout):
            urls.append(request.full_url)
            return FakeResponse(next(responses))

        result = send_wecom_app("hello", requester)

        self.assertTrue(result.ok)
        self.assertEqual(4, len(urls))
        self.assertIn("access_token=token-old", urls[1])
        self.assertIn("access_token=token-new", urls[3])

    def test_wecom_custom_app_can_reply_only_to_command_sender(self):
        requests = []

        def requester(request, timeout):
            requests.append(request)
            if "gettoken" in request.full_url:
                return FakeResponse({"errcode": 0, "errmsg": "ok", "access_token": "token-1", "expires_in": 7200})
            return FakeResponse({"errcode": 0, "errmsg": "ok"})

        result = send_wecom_app("reply", requester, to_user="sunny")

        self.assertTrue(result.ok)
        payload = json.loads(requests[-1].data)
        self.assertEqual("sunny", payload["touser"])
        self.assertNotIn("toparty", payload)

    def test_wecom_custom_app_sends_news_with_cached_poster_url(self):
        requests = []

        def requester(request, timeout):
            requests.append(request)
            if "gettoken" in request.full_url:
                return FakeResponse({"errcode": 0, "errmsg": "ok", "access_token": "token-1", "expires_in": 7200})
            return FakeResponse({"errcode": 0, "errmsg": "ok"})

        result = send_wecom_app_news(
            "测试电影已完成转存",
            "任务 #7",
            "https://media.example/#tracking",
            "https://media.example/api/notifications/wecom/posters/abc",
            requester,
            to_user="sunny",
        )

        self.assertTrue(result.ok)
        payload = json.loads(requests[-1].data)
        self.assertEqual("news", payload["msgtype"])
        self.assertEqual("sunny", payload["touser"])
        article = payload["news"]["articles"][0]
        self.assertEqual("测试电影已完成转存", article["title"])
        self.assertIn("/wecom/posters/abc", article["picurl"])

    def test_channel_error_does_not_expose_access_token(self):
        def requester(request, timeout):
            if "gettoken" in request.full_url:
                return FakeResponse({"errcode": 0, "errmsg": "ok", "access_token": "secret-token", "expires_in": 7200})
            raise RuntimeError(f"request failed: {request.full_url}")

        result = send_wecom_app("hello", requester)

        self.assertFalse(result.ok)
        self.assertNotIn("secret-token", result.message)
        self.assertIn("access_token=***", result.message)

    def test_shortcut_sync_updates_telegram_commands_and_wecom_menu(self):
        requests = []
        responses = iter([
            {"ok": True},
            {"errcode": 0, "access_token": "token-1", "expires_in": 7200},
            {"errcode": 0, "errmsg": "ok"},
        ])
        def requester(request, timeout):
            requests.append(request)
            return FakeResponse(next(responses))
        results = sync_interaction_shortcuts(requester)
        self.assertTrue(all(result.ok for result in results))
        self.assertIn("setMyCommands", requests[0].full_url)
        self.assertIn("/cgi-bin/menu/create", requests[2].full_url)
        menu = json.loads(requests[2].data)
        self.assertEqual(["STRM", "订阅管理", "服务器信息"], [item["name"] for item in menu["button"]])
        self.assertEqual(
            ["/strm_full", "/strm_incremental", "/strm_directory"],
            [item["key"] for item in menu["button"][0]["sub_button"]],
        )
        self.assertEqual(
            ["/tracking", "/wishlist"],
            [item["key"] for item in menu["button"][1]["sub_button"]],
        )
        self.assertEqual(
            ["/status", "/review", "/emby"],
            [item["key"] for item in menu["button"][2]["sub_button"]],
        )
        telegram_commands = json.loads(requests[0].data)["commands"]
        self.assertIn({"command": "strm_directory", "description": "STRM 指定目录扫描"}, telegram_commands)

    def test_legacy_download_shortcut_upgrades_without_rejecting_saved_config(self):
        self.assertEqual(
            ["strm_full", "strm_incremental", "strm_directory", "tracking", "wishlist", "status", "review"],
            notification_channels.normalize_interaction_shortcut_ids(
                ["strm_full", "strm_incremental", "tracking", "download"]
            ),
        )
        self.assertEqual(
            ["status", "review"],
            notification_channels.normalize_interaction_shortcut_ids(["download"]),
        )

    @patch("app.main.Thread")
    def test_container_start_restores_saved_wecom_shortcut_menu(self, thread):
        with patch.dict(os.environ, {"WECOM_CALLBACK_ENABLED": "true"}, clear=False):
            get_settings.cache_clear()
            self.assertTrue(restore_interaction_shortcuts())

        thread.assert_called_once()
        self.assertEqual("media-index-interaction-menu-sync", thread.call_args.kwargs["name"])
        thread.return_value.start.assert_called_once()

    @patch("app.services.notification_channels.send_wecom_app_news")
    @patch("app.services.notification_channels.send_wecom_news")
    @patch("app.services.notification_channels.send_telegram_photo")
    def test_configured_channels_prefer_rich_messages_when_poster_exists(self, telegram, wecom, wecom_app):
        telegram.return_value = ChannelResult("telegram", True, "ok")
        wecom.return_value = ChannelResult("wecom", True, "ok")
        wecom_app.return_value = ChannelResult("wecom_app", True, "ok")
        with patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://media.example"}):
            get_settings.cache_clear()
            results = send_configured_channels(
                "测试电影 转存已完成",
                "任务 #7",
                "tracking",
                "https://media.example/api/notifications/wecom/posters/abc",
            )
        self.assertEqual(3, len(results))
        telegram.assert_called_once()
        wecom.assert_called_once_with(
            "测试电影 转存已完成",
            "任务 #7",
            "https://media.example/#tracking",
            "https://media.example/api/notifications/wecom/posters/abc",
        )
        wecom_app.assert_called_once()

    @patch("app.services.notification_channels.send_wecom_app_news")
    @patch("app.services.notification_channels.send_wecom_news")
    @patch("app.services.notification_channels.send_telegram_photo")
    def test_https_poster_still_uses_rich_cards_without_public_base_url(self, telegram, wecom, wecom_app):
        telegram.return_value = ChannelResult("telegram", True, "ok")
        wecom.return_value = ChannelResult("wecom", True, "ok")
        wecom_app.return_value = ChannelResult("wecom_app", True, "ok")
        with patch.dict(os.environ, {"PUBLIC_BASE_URL": ""}, clear=False):
            get_settings.cache_clear()
            send_configured_channels("开始播放 · 测试剧", "用户：Sunny", "media-server", "https://image.tmdb.org/t/p/w500/test.jpg")
        wecom.assert_called_once_with(
            "开始播放 · 测试剧",
            "用户：Sunny",
            "https://image.tmdb.org/t/p/w500/test.jpg",
            "https://image.tmdb.org/t/p/w500/test.jpg",
        )
        wecom_app.assert_called_once()

    @patch("app.services.notifications.send_configured_channels")
    def test_playback_event_scope_skips_external_delivery(self, send_channels):
        with patch.dict(os.environ, {"NOTIFICATION_EVENT_TYPES": "library,transfer_success"}, clear=False):
            get_settings.cache_clear()
            self.assertTrue(add_notification("emby-playback:event-1", "info", "Emby 开始播放", "Movie", "media-server"))

        send_channels.assert_not_called()
        with db() as conn:
            row = conn.execute("SELECT external_status,external_error FROM notifications WHERE source_key=?", ("emby-playback:event-1",)).fetchone()
        self.assertEqual("skipped", row["external_status"])
        self.assertIn("playback", row["external_error"])

    @patch("app.services.notifications.send_configured_channels")
    def test_new_terminal_job_is_delivered_once(self, send_channels):
        send_channels.return_value = []
        with db() as conn:
            conn.execute(
                """
                INSERT INTO transfer_jobs(target,status,stage,message,finished_at)
                VALUES('cloud','failed','transfer','failed message',CURRENT_TIMESTAMP)
                """
            )

        self.assertEqual(1, sync_transfer_notifications())
        self.assertEqual(0, sync_transfer_notifications())
        send_channels.assert_called_once()

    @patch("app.services.notifications.send_configured_channels")
    def test_deletion_jobs_are_not_backfilled_as_transfer_notifications(self, send_channels):
        with db() as conn:
            conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,finished_at)
                   VALUES('cloud','deletion','done','deletion_completed','已移入回收站',CURRENT_TIMESTAMP)"""
            )

        self.assertEqual(0, sync_transfer_notifications())
        send_channels.assert_not_called()

    @patch("app.services.notifications.send_configured_channels")
    def test_scheduler_log_is_not_sent_as_an_external_failure(self, send_channels):
        with db() as conn:
            conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,request_source,finished_at)
                   VALUES('cloud','scheduler','failed','scheduled_failed','UnboundLocalError','scheduler',CURRENT_TIMESTAMP)"""
            )

        self.assertEqual(0, sync_transfer_notifications())
        send_channels.assert_not_called()

    @patch("app.services.notifications.send_configured_channels")
    def test_same_wishlist_media_operation_sends_one_friendly_notification(self, send_channels):
        send_channels.return_value = []
        with db() as conn:
            wishlist_one = conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(88,'movie','测试电影','qas','retry_wait')").lastrowid
            wishlist_two = conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(88,'movie','测试电影','p115','retry_wait')").lastrowid
            conn.execute("""INSERT INTO transfer_jobs(wishlist_id,tmdb_id,media_type,target,provider,status,stage,message,finished_at)
                            VALUES(?,88,'movie','cloud','qas','failed','no_resource','未找到夸克资源',datetime('now','-2 minutes'))""", (wishlist_one,))
            conn.execute("""INSERT INTO transfer_jobs(wishlist_id,tmdb_id,media_type,target,provider,status,stage,message,finished_at)
                            VALUES(?,88,'movie','cloud','p115','failed','internal_error','provider error',datetime('now','-2 minutes'))""", (wishlist_two,))

        self.assertEqual(1, sync_transfer_notifications())
        self.assertEqual("测试电影 暂无可用资源", send_channels.call_args.args[0])
        self.assertIn("暂未找到", send_channels.call_args.args[1])
        self.assertEqual(0, sync_transfer_notifications())

    @patch("app.services.notifications.send_configured_channels")
    def test_openlist_submission_has_a_specific_notification(self, send_channels):
        send_channels.return_value = []
        with db() as conn:
            conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,display_title,status,stage,message,finished_at)
                VALUES('cloud','openlist','蜘蛛侠：英雄无归','done','openlist_sync_done',
                       '已提交 OpenList 后台复制任务 #42',CURRENT_TIMESTAMP)
                """
            )

        self.assertEqual(1, sync_transfer_notifications())
        title = send_channels.call_args.args[0]
        self.assertIn("OpenList 复制任务已提交", title)


if __name__ == "__main__":
    unittest.main()
