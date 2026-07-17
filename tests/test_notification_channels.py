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
)
from app.services.notifications import sync_transfer_notifications


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


if __name__ == "__main__":
    unittest.main()
