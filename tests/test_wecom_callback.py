import base64
import hashlib
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from Crypto.Cipher import AES
from starlette.requests import Request

from app.api.wecom_callback import _claim_message, _public_base_url, verify_wecom_callback
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.wecom_callback import (
    command_reply,
    decrypt_message,
    handle_resource_request,
    handle_command,
    handle_interaction_choice,
    load_interaction,
    parse_media_name_query,
    parse_resource_request,
    parse_inbound_xml,
    parse_direct_link_choice,
    parse_direct_link_metadata,
    save_interaction,
    send_review_candidate_notifications,
    _send_candidate_options,
    select_media_match,
    select_media_options,
    select_season_number,
    start_direct_link_target_selection,
    _is_ongoing_media,
    _interaction_transfer_snapshot,
    _register_interaction_tracking,
    _start_resource_target_selection,
    _start_resource_transfer,
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
        timestamp = str(int(time.time()))
        response = verify_wecom_callback(signature(encrypted, timestamp), timestamp, "456", encrypted)
        self.assertEqual(b"verified", response.body)

    def test_callback_rejects_stale_timestamp_and_deduplicates_persistently(self):
        encrypted = encrypt_message("verified")
        stale = str(int(time.time()) - 301)
        with self.assertRaises(Exception) as raised:
            verify_wecom_callback(signature(encrypted, stale), stale, "456", encrypted)
        self.assertEqual(403, raised.exception.status_code)
        self.assertTrue(_claim_message("persistent-message"))
        self.assertFalse(_claim_message("persistent-message"))

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

    def test_configured_callback_url_is_used_for_poster_urls(self):
        with patch.dict(os.environ, {"WECOM_CALLBACK_URL": "https://callback.example/wecom/legacy"}):
            get_settings.cache_clear()
            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "scheme": "http",
                    "server": ("media-index", 8000),
                    "path": "/api/notifications/wecom/callback",
                    "query_string": b"",
                    "headers": [(b"host", b"media-index:8000")],
                }
            )
            self.assertEqual("https://callback.example", _public_base_url(request))
        get_settings.cache_clear()

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

    @patch("app.services.wecom_callback.emby_status_reply", return_value="MediaIndex Emby\n\n媒体条目：12")
    def test_emby_command_returns_media_library_status(self, emby_reply):
        self.assertEqual("MediaIndex Emby\n\n媒体条目：12", command_reply("/emby"))
        self.assertEqual("MediaIndex Emby\n\n媒体条目：12", command_reply("Emby"))
        self.assertEqual(2, emby_reply.call_count)

    def test_wishlist_reply_groups_providers_and_includes_historical_states(self):
        with db() as conn:
            conn.executemany(
                """
                INSERT INTO wishlist(tmdb_id,media_type,title,provider,status,enabled)
                VALUES(31,'movie','抓特务',?,?,?)
                """,
                [("quark", "retry_wait", 1), ("p115", "completed", 1)],
            )
            conn.execute(
                """
                INSERT INTO wishlist(tmdb_id,media_type,title,provider,status,enabled)
                VALUES(32,'movie','旧愿望','quark','completed',0)
                """
            )

        reply = command_reply("/wishlist")

        self.assertEqual(1, reply.count("抓特务"))
        self.assertIn("夸克 retry_wait；115 completed", reply)
        self.assertIn("旧愿望 (夸克 已停用)", reply)

    def test_tracking_reply_groups_provider_rows_into_one_logical_task(self):
        with db() as conn:
            conn.executemany(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,season_number,provider,status,decision_state
                ) VALUES(7,'tv','喜剧之王单口季',3,?,'active',?)
                """,
                [("qas", "retry_wait"), ("p115", "pending")],
            )
            conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,season_number,provider,status,decision_state
                ) VALUES(8,'tv','凡人修仙传',1,'qas','active','pending')
                """
            )

        reply = command_reply("/tracking")

        self.assertEqual(1, reply.count("喜剧之王单口季 S03"))
        self.assertIn("喜剧之王单口季 S03 (夸克 retry_wait；115 pending)", reply)
        self.assertIn("凡人修仙传 S01 (pending)", reply)
        self.assertIn("智能追更：2", command_reply("/status"))

    def test_tracking_reply_limits_logical_tasks_without_cutting_off_provider_states(self):
        with db() as conn:
            for index in range(1, 7):
                conn.executemany(
                    """
                    INSERT INTO tracking_tasks(
                        tmdb_id,media_type,title,season_number,provider,status,decision_state,updated_at
                    ) VALUES(?, 'tv', ?, 1, ?, 'active', ?, ?)
                    """,
                    [
                        (index, f"剧集{index}", "qas", "pending", f"2026-08-{index:02d} 10:00:00"),
                        (index, f"剧集{index}", "p115", "retry_wait", f"2026-08-{index:02d} 10:00:00"),
                    ],
                )

        reply = command_reply("/tracking")

        self.assertNotIn("剧集1 S01", reply)
        self.assertEqual(1, reply.count("剧集6 S01"))
        self.assertIn("剧集6 S01 (夸克 pending；115 retry_wait)", reply)

    @patch("app.services.wecom_callback.list_strm_root_directories")
    @patch("app.services.wecom_callback.send_wecom_app")
    def test_strm_directory_command_prompts_for_root_child_number(self, send, list_directories):
        list_directories.return_value = (
            [
                SimpleNamespace(provider="p115", name="电影", path="/媒体库/电影"),
                SimpleNamespace(provider="quark", name="剧集", path="/夸克/剧集"),
            ],
            [],
        )

        handle_command("/strm_directory", "sunny")

        interaction = load_interaction("sunny")
        self.assertEqual("strm_directory", interaction[0])
        self.assertEqual("/媒体库/电影", interaction[1]["options"][0]["path"])
        self.assertIn("1. 115：电影", send.call_args.args[0])
        self.assertIn("2. 夸克：剧集", send.call_args.args[0])
        self.assertTrue(send.call_args.kwargs["buttons"])

    def test_resource_request_defaults_to_cloud_and_supports_local_prefix(self):
        self.assertEqual(("cloud", "沙丘2"), parse_resource_request("沙丘2"))
        self.assertEqual(("local", "沙丘2"), parse_resource_request("本地 沙丘2"))

    @patch("app.services.wecom_callback.send_wecom_app")
    @patch("app.services.wecom_callback.save_interaction")
    @patch("app.services.wecom_callback.prepare_direct_link_request")
    def test_direct_link_reply_shows_folder_names_only(self, prepare_request, save, send):
        prepare_request.return_value = SimpleNamespace(
            link="https://pan.quark.cn/s/demo",
            provider="quark",
            root_path="/夸克/下载链接",
            options=(
                SimpleNamespace(provider="quark", path="/夸克/下载链接/电影", label="电影"),
                SimpleNamespace(provider="quark", path="/夸克/下载链接/剧集", label="剧集"),
            ),
        )

        start_direct_link_target_selection("https://pan.quark.cn/s/demo", "sunny")

        reply = send.call_args.args[0]
        self.assertIn("1. 电影", reply)
        self.assertIn("2. 剧集", reply)
        self.assertIn("云下载路径：/夸克/下载链接", reply)
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

    def test_plain_movie_query_ignores_tmdb_derivative_title(self):
        results = [
            {"tmdb_id": 634649, "title": "蜘蛛侠：英雄无归", "media_type": "movie", "year": "2021"},
            {"tmdb_id": 999999, "title": "蜘蛛侠：英雄无归的幕后特辑", "media_type": "movie", "year": "2022"},
        ]
        options = select_media_options("蜘蛛侠：英雄无归", results)
        self.assertEqual([634649], [item["tmdb_id"] for item in options])

    def test_plain_movie_query_does_not_auto_select_only_derivative_title(self):
        results = [
            {"tmdb_id": 999999, "title": "蜘蛛侠：英雄无归的幕后特辑", "media_type": "movie", "year": "2022"},
        ]
        self.assertEqual([], select_media_options("蜘蛛侠：英雄无归", results))

    def test_explicit_derivative_query_keeps_matching_title(self):
        results = [
            {"tmdb_id": 999999, "title": "蜘蛛侠：英雄无归的幕后特辑", "media_type": "movie", "year": "2022"},
        ]
        options = select_media_options("蜘蛛侠：英雄无归幕后特辑", results)
        self.assertEqual([999999], [item["tmdb_id"] for item in options])

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

    @patch("app.services.wecom_callback._start_resource_target_selection")
    def test_numeric_reply_can_use_broadcast_selection(self, start_target):
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
        start_target.assert_called_once()
        self.assertEqual("sunny", start_target.call_args.args[3])
        self.assertIsNone(load_interaction("*"))

    @patch("app.services.wecom_callback.prepare_direct_link_request")
    @patch("app.services.wecom_callback.send_wecom_app")
    def test_download_link_prompts_for_target_folder_number(self, send, prepare):
        option = unittest.mock.Mock(provider="p115", path="/strm/下载链接/电影", label="电影")
        prepare.return_value = unittest.mock.Mock(
            link="magnet:?xt=urn:btih:abc",
            provider="p115",
            root_path="/strm/下载链接",
            options=(option,),
        )

        handle_command("magnet:?xt=urn:btih:abc", "sunny")

        interaction = load_interaction("sunny")
        self.assertEqual("direct_link", interaction[0])
        self.assertEqual("/strm/下载链接/电影", interaction[1]["options"][0]["path"])
        self.assertIn("回复数字选择目标文件夹", send.call_args.args[0])

    def test_share_link_directly_prompts_for_cloud_download_subfolder(self):
        request = SimpleNamespace(
            link="https://pan.quark.cn/s/demo",
            provider="quark",
            root_path="/夸克/云下载",
            options=(SimpleNamespace(provider="quark", path="/夸克/云下载/01电影", label="01电影"),),
        )
        with (
            patch("app.services.wecom_callback.prepare_direct_link_request", return_value=request),
            patch("app.services.wecom_callback.resolve_direct_link_resource_name", return_value="黑夜告白"),
            patch("app.services.wecom_callback.send_wecom_app") as send,
        ):
            handle_command("https://pan.quark.cn/s/demo", "sunny")

        interaction = load_interaction("sunny")
        self.assertEqual("direct_link", interaction[0])
        self.assertIn("即将把资源“黑夜告白”", send.call_args.args[0])
        self.assertIn("/夸克/云下载", send.call_args.args[0])
        self.assertIn("3 黑夜告白 2026", send.call_args.args[0])
        self.assertEqual(("黑夜告白", "2026"), parse_direct_link_metadata("资源名：黑夜告白 年份：2026"))

    @patch("app.services.wecom_callback.handle_direct_link_transfer")
    @patch("app.services.wecom_callback.send_wecom_app")
    def test_number_title_year_reply_keeps_selected_cloud_download_folder(self, send, transfer):
        transfer.return_value = unittest.mock.Mock(ok=True, job_id=9, message="已提交")
        save_interaction(
            "sunny",
            "direct_link",
            {
                "command": "https://115.com/s/abc",
                "provider": "p115",
                "options": [
                    {"provider": "p115", "path": "/115/云下载/03电视剧", "label": "03电视剧", "category": "tv"}
                ],
            },
        )

        handle_command("1 黑夜告白 2026", "sunny")

        transfer.assert_called_once_with(
            "https://115.com/s/abc",
            "sunny",
            save_path="/115/云下载/03电视剧",
            title="黑夜告白",
            year="2026",
            category="tv",
            preserve_save_path=True,
        )
        self.assertEqual((1, "黑夜告白", "2026"), parse_direct_link_choice("1 黑夜告白 2026"))
        self.assertIsNone(load_interaction("sunny"))

    def test_link_prompt_fails_closed_when_cloud_download_root_has_no_children(self):
        request = SimpleNamespace(
            link="magnet:?xt=urn:btih:abc",
            provider="p115",
            root_path="/115/云下载",
            options=(),
        )
        save_interaction("sunny", "direct_link", {"options": [{"path": "/old"}]})
        with (
            patch("app.services.wecom_callback.prepare_direct_link_request", return_value=request),
            patch("app.services.wecom_callback.resolve_direct_link_resource_name", return_value="待测试资源"),
            patch("app.services.wecom_callback.send_wecom_app") as send,
        ):
            start_direct_link_target_selection(request.link, "sunny")

        self.assertIsNone(load_interaction("sunny"))
        self.assertIn("暂无可选子文件夹", send.call_args.args[0])

    @patch("app.services.wecom_callback.handle_direct_link_transfer")
    @patch("app.services.wecom_callback.send_wecom_app")
    def test_numeric_reply_transfers_download_link_to_selected_folder(self, send, transfer):
        transfer.return_value = unittest.mock.Mock(ok=True, job_id=9, message="已提交")
        save_interaction(
            "sunny",
            "direct_link",
            {
                "command": "https://115.com/s/abc",
                "provider": "p115",
                "options": [{"provider": "p115", "path": "/strm/下载链接/剧集", "label": "剧集"}],
            },
        )

        self.assertTrue(handle_interaction_choice(1, "sunny", "https://media.example"))

        transfer.assert_called_once_with("https://115.com/s/abc", "sunny", save_path="/strm/下载链接/剧集")
        self.assertEqual(
            ["MediaIndex\n\n开始转存", "MediaIndex\n\n已提交"],
            [call.args[0] for call in send.call_args_list],
        )
        self.assertIsNone(load_interaction("sunny"))

    @patch("app.services.wecom_callback.handle_direct_link_transfer")
    @patch("app.services.wecom_callback.send_wecom_app")
    def test_numeric_reply_uses_detected_share_title_only_as_staging_name(self, _send, transfer):
        transfer.return_value = unittest.mock.Mock(ok=True, job_id=9, message="已提交")
        save_interaction(
            "sunny",
            "direct_link",
            {
                "command": "https://pan.quark.cn/s/abc",
                "provider": "quark",
                "resource_name": "秘令 第二季",
                "options": [
                    {"provider": "quark", "path": "/strm/download/03电视剧", "label": "03电视剧", "category": "tv"}
                ],
            },
        )

        self.assertTrue(handle_interaction_choice(1, "sunny", "https://media.example"))

        transfer.assert_called_once_with(
            "https://pan.quark.cn/s/abc",
            "sunny",
            save_path="/strm/download/03电视剧",
            staging_name="秘令 第二季",
        )

    @patch("app.services.scheduler.schedule_interaction_strm_directory_scan")
    @patch("app.services.wecom_callback.send_wecom_app")
    def test_numeric_reply_schedules_only_selected_strm_directory(self, send, schedule):
        schedule.return_value = {"ok": True, "job_id": 31}
        save_interaction(
            "sunny",
            "strm_directory",
            {
                "options": [
                    {"provider": "p115", "path": "/媒体库/剧集", "label": "115：剧集"},
                ]
            },
        )

        self.assertTrue(handle_interaction_choice(1, "sunny", "https://media.example"))

        schedule.assert_called_once_with("p115", "/媒体库/剧集")
        self.assertIn("全量扫描任务 #31", send.call_args.args[0])
        self.assertIsNone(load_interaction("sunny"))

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

    @patch("app.services.wecom_callback.enqueue_transfer")
    @patch("app.services.wecom_callback.send_wecom_app")
    def test_cloud_wecom_transfer_requires_a_selected_download_child(self, send, enqueue):
        _start_resource_transfer(
            {"tmdb_id": 22, "media_type": "movie", "title": "测试电影", "year": "2026"},
            "cloud",
            "测试电影",
            "sunny",
            "https://media.example",
        )
        enqueue.assert_not_called()
        self.assertIn("未确认云下载子目录", send.call_args.args[0])

    @patch("app.services.wecom_callback.probe_resource_availability")
    def test_wecom_reuses_verified_provider_snapshot_for_transfer(self, probe):
        probe.return_value = {
            "ready": True,
            "plan_reusable": True,
            "transfer_share_urls": ["https://pan.quark.cn/s/verified"],
            "episode_numbers": [],
            "coverage": {},
        }

        urls, episodes, preferred_only, plan = _interaction_transfer_snapshot(
            {"tmdb_id": 22, "media_type": "movie", "title": "抓特务", "year": "2026"},
            "quark",
            None,
            ("https://115.com/s/unrelated",),
        )

        self.assertEqual(["https://pan.quark.cn/s/verified"], urls)
        self.assertEqual([], episodes)
        self.assertTrue(preferred_only)
        self.assertEqual("wecom", plan["entrypoint"])
        self.assertEqual("quark", plan["provider"])

    @patch.dict(os.environ, {"QUARK_COOKIE": "__puus=test"})
    @patch("app.services.wecom_callback.list_cloud_download_targets")
    @patch("app.services.wecom_callback.send_wecom_app")
    @patch("app.services.wecom_callback.PansouClient")
    @patch("app.services.wecom_callback.TmdbClient")
    def test_resource_message_prompts_for_cloud_download_child_before_transfer(
        self, tmdb_class, pansou_class, send, list_targets
    ):
        get_settings.cache_clear()
        list_targets.return_value = (
            SimpleNamespace(provider="quark", child_name="01电影", path="/夸克/云下载/01电影"),
        )
        pansou = pansou_class.return_value
        pansou.configured.return_value = True
        pansou.search_detailed.return_value.items = [{"share_url": "https://pan.quark.cn/s/test"}]
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
        handle_resource_request("测试电影 2026", "sunny", "https://media.example")

        tmdb.search.assert_called_once_with("测试电影", "all")
        interaction = load_interaction("sunny")
        self.assertEqual("resource_target", interaction[0])
        self.assertEqual("quark", interaction[1]["options"][0]["provider"])
        self.assertEqual("movie", interaction[1]["options"][0]["category"])
        self.assertEqual("01电影", interaction[1]["options"][0]["cloud_download_child"])
        self.assertEqual("/夸克/云下载/01电影", interaction[1]["options"][0]["path"])
        self.assertEqual(["https://pan.quark.cn/s/test"], interaction[1]["preferred_share_urls"])
        self.assertIn("请选择要转存到的云下载子目录", send.call_args.args[0])
        self.assertEqual(1, send.call_count)
        get_settings.cache_clear()

    @patch("app.services.wecom_callback._start_resource_target_selection")
    @patch("app.services.wecom_callback.TmdbClient")
    @patch("app.services.wecom_callback.PansouClient")
    def test_empty_pansou_preview_still_uses_tmdb_and_existing_transfer_flow(self, pansou_class, tmdb_class, start_target):
        pansou = pansou_class.return_value
        pansou.configured.return_value = True
        pansou.search_detailed.return_value.items = []
        tmdb = tmdb_class.return_value
        tmdb.configured.return_value = True
        tmdb.search.return_value = {
            "results": [
                {"tmdb_id": 634649, "title": "蜘蛛侠：英雄无归", "media_type": "movie", "year": "2021"}
            ]
        }

        handle_resource_request("蜘蛛侠：英雄无归 2021", "sunny", "https://media.example")

        tmdb.search.assert_called_once_with("蜘蛛侠：英雄无归", "all")
        start_target.assert_called_once()
        self.assertEqual(634649, start_target.call_args.args[0]["tmdb_id"])
        self.assertEqual((), start_target.call_args.kwargs["preferred_share_urls"])

    def test_media_name_query_extracts_only_trailing_year(self):
        self.assertEqual(("黑夜告白", "2026"), parse_media_name_query("黑夜告白 2026"))
        self.assertEqual(("黑夜告白", "2026"), parse_media_name_query("黑夜告白（2026）"))
        self.assertEqual(("2046", ""), parse_media_name_query("2046"))

    @patch("app.services.wecom_callback.send_wecom_app")
    @patch("app.services.wecom_callback.PansouClient")
    @patch("app.services.wecom_callback.TmdbClient")
    def test_requested_year_does_not_fall_back_to_wrong_tmdb_release(self, tmdb_class, pansou_class, send):
        pansou_class.return_value.configured.return_value = False
        tmdb = tmdb_class.return_value
        tmdb.configured.return_value = True
        tmdb.search.return_value = {
            "results": [
                {"tmdb_id": 1, "title": "同名电影", "media_type": "movie", "year": "2025"}
            ]
        }

        handle_resource_request("同名电影 2026", "sunny")

        self.assertIsNone(load_interaction("sunny"))
        self.assertIn("没有找到", send.call_args.args[0])

    @patch("app.services.wecom_callback._start_resource_transfer")
    def test_resource_target_choice_passes_only_selected_provider_and_category(self, start):
        save_interaction(
            "sunny",
            "resource_target",
            {
                "target": "cloud",
                "query": "测试剧",
                "item": {"tmdb_id": 7, "title": "测试剧", "media_type": "tv", "year": "2026"},
                "preferred_share_urls": ["https://115.com/s/example"],
                "options": [
                    {
                        "provider": "quark",
                        "category": "tv",
                        "cloud_download_child": "03电视剧",
                        "label": "夸克 · 电视剧",
                    },
                    {
                        "provider": "p115",
                        "category": "anime",
                        "cloud_download_child": "12动漫",
                        "label": "115 · 动漫",
                    },
                ],
            },
        )

        self.assertTrue(handle_interaction_choice(2, "sunny", "https://media.example"))

        item = start.call_args.args[0]
        self.assertEqual("p115", item["provider"])
        self.assertEqual("anime", item["category"])
        self.assertEqual(("https://115.com/s/example",), start.call_args.kwargs["preferred_share_urls"])
        self.assertEqual("12动漫", start.call_args.kwargs["cloud_download_child"])

    def test_only_explicit_tmdb_ongoing_statuses_enable_auto_tracking(self):
        item = {"tmdb_id": 7, "media_type": "tv"}
        for status in ("Returning Series", "In Production", "Planned", "Pilot"):
            self.assertTrue(_is_ongoing_media(item, {"status": status}))
        for status in ("Ended", "Canceled", ""):
            self.assertFalse(_is_ongoing_media(item, {"status": status}))
        self.assertFalse(_is_ongoing_media({"tmdb_id": 7, "media_type": "movie"}, {"status": "In Production"}))

    @patch("app.services.wecom_callback.send_wecom_app")
    @patch("app.services.wecom_callback.register_tracking_task")
    def test_auto_tracking_registers_only_after_successful_transfer(self, register, send):
        payload = SimpleNamespace(
            tmdb_id=7,
            media_type="tv",
            category="tv",
            title="测试剧",
            year="2026",
            poster_url="",
            overview="",
            season_number=2,
            target="cloud",
            provider="p115",
        )
        with db() as conn:
            failed_id = int(
                conn.execute(
                    "INSERT INTO transfer_jobs(target,provider,status) VALUES('cloud','p115','failed')"
                ).lastrowid
            )
            done_id = int(
                conn.execute(
                    "INSERT INTO transfer_jobs(target,provider,status) VALUES('cloud','p115','done')"
                ).lastrowid
            )
            no_resource_id = int(
                conn.execute(
                    """
                    INSERT INTO transfer_jobs(target,provider,status,stage)
                    VALUES('cloud','p115','failed','no_resource')
                    """
                ).lastrowid
            )
        register.return_value = {"ok": True, "id": 3, "provider": "p115", "check_time": "12:00"}

        _register_interaction_tracking({"title": "测试剧"}, payload, failed_id, "sunny")
        register.assert_not_called()
        _register_interaction_tracking({"title": "测试剧"}, payload, done_id, "sunny")

        registration = register.call_args.args[0]
        self.assertEqual((7, "tv", 2, "p115"), (
            registration.tmdb_id,
            registration.media_type,
            registration.season_number,
            registration.provider,
        ))
        self.assertIn("播出日期跟随 TMDB", send.call_args.args[0])
        self.assertIn("12:00", send.call_args.args[0])

        register.reset_mock()
        send.reset_mock()
        _register_interaction_tracking({"title": "测试剧"}, payload, no_resource_id, "sunny")
        register.assert_called_once()
        self.assertIn("已加入智能追更", send.call_args.args[0])

    @patch.dict(os.environ, {"ENABLED_CLOUD_PROVIDERS": "quark", "QUARK_COOKIE": "__puus=test"})
    @patch("app.api.transfers.execute_transfer_v2")
    @patch("app.services.wecom_callback.send_wecom_app")
    def test_no_resource_after_directory_choice_notifies_and_enters_wishlist(self, send, execute):
        get_settings.cache_clear()
        execute.return_value = {
            "ok": False,
            "stage": "no_resource",
            "message": "没有找到可用资源",
            "save_path": "/strm/movie/测试电影 (2026)",
            "target": {"title": "测试电影", "series_year": "2026"},
            "resolution": {},
        }

        _start_resource_transfer(
            {
                "tmdb_id": 22,
                "media_type": "movie",
                "category": "movie",
                "provider": "quark",
                "title": "测试电影",
                "year": "2026",
            },
            "cloud",
            "测试电影 2026",
            "sunny",
            "",
            cloud_download_child="01电影",
        )

        self.assertEqual("01电影", execute.call_args.kwargs["interaction_cloud_download_child"])
        self.assertEqual("wecom", execute.call_args.kwargs["request_source"])

        with db() as conn:
            wishlist = conn.execute(
                "SELECT tmdb_id,media_type,provider,status FROM wishlist WHERE tmdb_id=22"
            ).fetchone()
        self.assertEqual((22, "movie", "quark", "pending"), tuple(wishlist))
        self.assertTrue(any("暂无资源，已加入愿望单" in call.args[0] for call in send.call_args_list))
        get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
