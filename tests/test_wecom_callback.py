import base64
import hashlib
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Crypto.Cipher import AES
from starlette.requests import Request

from app.api.wecom_callback import _public_base_url, verify_wecom_callback
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.wecom_callback import (
    command_reply,
    decrypt_message,
    handle_resource_request,
    handle_interaction_choice,
    load_interaction,
    parse_resource_request,
    parse_inbound_xml,
    save_interaction,
    send_review_candidate_notifications,
    _send_candidate_options,
    select_media_match,
    select_media_options,
    select_season_number,
    verify_signature,
)
from app.services.notification_channels import ChannelResult


TOKEN = "callback-token"
AES_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode().rstrip("=")
CORP_ID = "ww-test-corp"


def encrypt_message(content: str, receive_id: str = CORP_ID) -> str:
    key = base64.b64decode(AES_KEY + "=")
    message = content.encode("utf-8")
    plaintext = b"0123456789abcdef" + struct.pack("!I", len(message)) + message + receive_id.encode("utf-8")
    pad = 32 - len(plaintext) % 32
    plaintext += bytes([pad]) * pad
    return base64.b64encode(AES.new(key, AES.MODE_CBC, key[:16]).encrypt(plaintext)).decode()


def signature(encrypted: str, timestamp: str = "123", nonce: str = "456") -> str:
    return hashlib.sha1("".join(sorted((TOKEN, timestamp, nonce, encrypted))).encode()).hexdigest()


class WecomCallbackTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "WECOM_CORP_ID": CORP_ID,
                "WECOM_CALLBACK_ENABLED": "true",
                "WECOM_CALLBACK_TOKEN": TOKEN,
                "WECOM_CALLBACK_AES_KEY": AES_KEY,
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_signature_and_decryption_validate_receive_id(self):
        encrypted = encrypt_message("<xml><Content>/status</Content></xml>")
        self.assertTrue(verify_signature(signature(encrypted), "123", "456", encrypted, TOKEN))
        self.assertIn("/status", decrypt_message(encrypted, AES_KEY, CORP_ID))
        with self.assertRaises(ValueError):
            decrypt_message(encrypted, AES_KEY, "another-corp")

    def test_callback_url_verification_returns_decrypted_echo(self):
        encrypted = encrypt_message("verified")
        response = verify_wecom_callback(signature(encrypted), "123", "456", encrypted)
        self.assertEqual(b"verified", response.body)

    def test_forwarded_public_origin_is_used_for_poster_urls(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "server": ("media-index", 8000),
                "path": "/api/notifications/wecom/callback",
                "query_string": b"",
                "headers": [
                    (b"host", b"media-index:8000"),
                    (b"x-forwarded-proto", b"https"),
                    (b"x-forwarded-host", b"media.example:666"),
                ],
            }
        )
        self.assertEqual("https://media.example:666", _public_base_url(request))

    def test_text_and_menu_click_messages_are_parsed(self):
        text = parse_inbound_xml(
            "<xml><FromUserName>sunny</FromUserName><MsgType>text</MsgType>"
            "<Content>/status</Content><MsgId>1</MsgId></xml>"
        )
        click = parse_inbound_xml(
            "<xml><FromUserName>sunny</FromUserName><MsgType>event</MsgType>"
            "<Event>click</Event><EventKey>/help</EventKey><CreateTime>2</CreateTime></xml>"
        )
        self.assertEqual("/status", text.command)
        self.assertEqual("/help", click.command)

    def test_status_command_reads_mediaindex_counts(self):
        with db() as conn:
            conn.execute(
                "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,status) VALUES(1,'tv','Show',1,'active')"
            )
            conn.execute(
                "INSERT INTO notifications(source_key,type,title) VALUES('one','info','Notice')"
            )
        reply = command_reply("/status")
        self.assertIn("智能追更：1", reply)
        self.assertIn("未读通知：1", reply)

    def test_resource_request_defaults_to_cloud_and_supports_local_prefix(self):
        self.assertEqual(("cloud", "沙丘2"), parse_resource_request("沙丘2"))
        self.assertEqual(("local", "沙丘2"), parse_resource_request("本地 沙丘2"))
        self.assertEqual(("local", "沙丘2"), parse_resource_request("本地：沙丘2"))
        self.assertEqual(("cloud", "沙丘2"), parse_resource_request("网盘 沙丘2"))

    def test_media_match_prefers_exact_title(self):
        results = [
            {"tmdb_id": 1, "title": "沙丘", "media_type": "movie"},
            {"tmdb_id": 2, "title": "沙丘2", "media_type": "movie"},
        ]
        self.assertEqual(2, select_media_match("沙丘 2", results)["tmdb_id"])

    def test_search_with_exact_movie_and_related_series_requires_choice(self):
        results = [
            {"tmdb_id": 1, "title": "疯狂动物城大小事", "media_type": "tv", "year": "2022"},
            {"tmdb_id": 2, "title": "疯狂动物城", "media_type": "movie", "year": "2016"},
            {"tmdb_id": 3, "title": "动物世界", "media_type": "movie", "year": "2018"},
        ]
        options = select_media_options("疯狂动物城", results)
        self.assertEqual([2, 1], [item["tmdb_id"] for item in options])

    def test_interaction_is_persisted_per_user(self):
        save_interaction("sunny", "media", {"options": [{"tmdb_id": 2}]})
        interaction = load_interaction("sunny")
        self.assertEqual("media", interaction[0])
        self.assertEqual(2, interaction[1]["options"][0]["tmdb_id"])

    @patch("app.services.wecom_callback._start_resource_transfer")
    def test_numeric_reply_selects_saved_media_option(self, start):
        save_interaction(
            "sunny",
            "media",
            {
                "target": "local",
                "query": "疯狂动物城",
                "options": [
                    {"tmdb_id": 2, "title": "疯狂动物城", "media_type": "movie"},
                    {"tmdb_id": 1, "title": "疯狂动物城大小事", "media_type": "tv"},
                ],
            },
        )
        self.assertTrue(handle_interaction_choice(1, "sunny", "https://media.example"))
        start.assert_called_once()
        self.assertEqual(2, start.call_args.args[0]["tmdb_id"])
        self.assertEqual("local", start.call_args.args[1])
        self.assertIsNone(load_interaction("sunny"))

    @patch("app.services.wecom_callback._start_resource_transfer")
    def test_numeric_reply_can_use_broadcast_selection(self, start):
        save_interaction(
            "*",
            "media",
            {
                "target": "cloud",
                "query": "测试电影",
                "options": [{"tmdb_id": 7, "title": "测试电影", "media_type": "movie"}],
            },
        )
        self.assertTrue(handle_interaction_choice(1, "sunny", "https://media.example"))
        start.assert_called_once()
        self.assertEqual("sunny", start.call_args.args[3])
        self.assertIsNone(load_interaction("*"))

    @patch("app.services.wecom_callback.send_wecom_app")
    def test_review_candidate_options_are_saved_for_numeric_confirmation(self, send):
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(display_title,target,status,stage)
                VALUES('测试剧','cloud','needs_review','needs_review')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,source_title,source,score)
                VALUES(?,?,?,?,?)
                """,
                (job_id, "https://pan.quark.cn/s/one", "测试剧 S01 2160P", "source-a", 88),
            )
        _send_candidate_options(int(job_id), "sunny", "https://media.example")
        interaction = load_interaction("sunny")
        self.assertEqual("candidate", interaction[0])
        self.assertEqual(job_id, interaction[1]["job_id"])
        self.assertIn("回复数字确认资源", send.call_args.args[0])

    @patch("app.services.wecom_callback.cache_tmdb_poster", return_value="poster-key")
    @patch("app.services.wecom_callback.send_wecom_app_news")
    def test_review_notification_sends_poster_candidate_card_and_saves_choice(self, send_news, cache_poster):
        send_news.return_value = ChannelResult("wecom_app", True, "消息已发送")
        with patch.dict(
            os.environ,
            {
                "WECOM_APP_ENABLED": "true",
                "WECOM_APP_SECRET": "secret",
                "WECOM_APP_AGENT_ID": "1000002",
                "WECOM_CALLBACK_ALLOWED_USERS": "sunny",
            },
        ):
            get_settings.cache_clear()
            with db() as conn:
                task_id = conn.execute(
                    """
                    INSERT INTO tracking_tasks(tmdb_id,media_type,title,poster_url,status)
                    VALUES(7,'tv','测试剧','https://image.tmdb.org/t/p/w500/test.jpg','active')
                    """
                ).lastrowid
                job_id = conn.execute(
                    """
                    INSERT INTO transfer_jobs(task_id,display_title,target,status,stage)
                    VALUES(?,'测试剧','cloud','needs_review','needs_review')
                    """,
                    (task_id,),
                ).lastrowid
                conn.execute(
                    """
                    INSERT INTO candidates(job_id,share_url,source_title,source,score,file_count)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (job_id, "https://pan.quark.cn/s/one", "测试剧 S01E01 2160P", "source-a", 88, 1),
                )
            results = send_review_candidate_notifications(int(job_id), "https://media.example")

        self.assertTrue(results[0].ok)
        interaction = load_interaction("sunny")
        self.assertEqual("candidate", interaction[0])
        self.assertEqual(job_id, interaction[1]["job_id"])
        cache_poster.assert_called_once()
        self.assertIn("回复数字确认资源", send_news.call_args.args[1])
        self.assertIn("/wecom/posters/poster-key", send_news.call_args.args[3])

    def test_latest_aired_season_is_selected(self):
        client = unittest.mock.Mock()
        client.details.return_value = {
            "seasons": [
                {"season_number": 1, "air_date": "2020-01-01"},
                {"season_number": 2, "air_date": "2025-01-01"},
                {"season_number": 3, "air_date": "2999-01-01"},
            ]
        }
        item = {"tmdb_id": 8, "media_type": "tv"}
        self.assertEqual(2, select_season_number(client, item))

    @patch("app.services.wecom_callback._send_transfer_result")
    @patch("app.services.wecom_callback.cache_tmdb_poster", return_value="poster-key")
    @patch("app.services.wecom_callback._run_transfer_job")
    @patch("app.services.wecom_callback.enqueue_transfer")
    @patch("app.services.wecom_callback.send_wecom_app")
    @patch("app.services.wecom_callback.TmdbClient")
    def test_resource_message_starts_cloud_transfer(self, tmdb_class, send, enqueue, run, cache, send_result):
        tmdb = tmdb_class.return_value
        tmdb.configured.return_value = True
        tmdb.search.return_value = {
            "results": [
                {
                    "tmdb_id": 22,
                    "media_type": "movie",
                    "title": "测试电影",
                    "year": "2026",
                }
            ]
        }
        enqueue.return_value = {"id": 7, "status": "running"}
        handle_resource_request("测试电影", "sunny", "https://media.example")
        payload = enqueue.call_args.args[0]
        self.assertEqual("cloud", payload.target)
        self.assertEqual(22, payload.tmdb_id)
        run.assert_called_once_with(payload, 7)
        cache.assert_called_once()
        send_result.assert_called_once_with(7, "测试电影", "网盘", "sunny", "https://media.example", "poster-key")
        self.assertEqual(1, send.call_count)


if __name__ == "__main__":
    unittest.main()
