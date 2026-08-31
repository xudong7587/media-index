import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import MediaTarget
from app.services.channel_monitor import (
    ChannelMonitorError,
    classify_pansou_channel_sources,
    delete_channel_subscriptions,
    import_pansou_channels,
    list_channel_messages,
    list_channel_subscriptions,
    normalize_telegram_channel_id,
    process_channel_post,
    search_channel_resources,
    upsert_channel_subscription,
)


class ChannelMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db")})
        self.environment.start()
        get_settings.cache_clear()
        init_db()
        with db() as conn:
            conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,year,provider,status) VALUES(?,?,?,?,?,?)", (100, "movie", "测试电影", "2026", "quark", "pending"))

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def _post(self, message_id=1, text="测试电影 https://pan.quark.cn/s/abc123"):
        return {"message_id": message_id, "chat": {"id": "-100123"}, "text": text}

    def test_pansou_channel_normalization_supports_public_links_usernames_and_numeric_ids(self):
        self.assertEqual("@public_movies", normalize_telegram_channel_id("https://t.me/s/Public_Movies?before=5", allow_plain_username=True))
        self.assertEqual("@public_movies", normalize_telegram_channel_id("@Public_Movies", allow_plain_username=True))
        self.assertEqual("@public_movies", normalize_telegram_channel_id("Public_Movies", allow_plain_username=True))
        self.assertEqual("-100123456789", normalize_telegram_channel_id("-100123456789", allow_plain_username=True))
        self.assertEqual("", normalize_telegram_channel_id("普通结果标题", allow_plain_username=True))

    def test_pansou_channel_classification_deduplicates_and_marks_existing(self):
        upsert_channel_subscription("@existing_channel", display_name="保留规则", auto_transfer=True)
        candidates = classify_pansou_channel_sources([
            {"raw_value": "Existing_Channel", "evidence_field": "results.channel"},
            {"raw_value": "https://t.me/existing_channel", "evidence_field": "merged_by_type.source"},
            {"raw_value": "New_Channel", "evidence_field": "results.channel"},
            {"raw_value": "不是频道", "evidence_field": "results.channel"},
        ])

        self.assertEqual(["existing", "importable", "unrecognized"], [item["status"] for item in candidates])
        self.assertEqual("@new_channel", candidates[1]["channel_id"])

    def test_pansou_import_skips_existing_without_overwriting_and_uses_safe_defaults(self):
        upsert_channel_subscription(
            "@existing_channel",
            display_name="已有名称",
            enabled=False,
            auto_transfer=True,
            require_douban_match=True,
            douban_titles=["已有规则"],
        )

        result = import_pansou_channels(["@Existing_Channel", "@new_channel", "https://t.me/New_Channel", "普通标题"])
        subscriptions = {item["channel_id"].casefold(): item for item in list_channel_subscriptions()}

        self.assertEqual(1, len(result["imported"]))
        self.assertEqual(["@existing_channel"], result["existing"])
        self.assertEqual(["普通标题"], result["unrecognized"])
        self.assertFalse(subscriptions["@existing_channel"]["enabled"])
        self.assertTrue(subscriptions["@existing_channel"]["auto_transfer"])
        self.assertEqual(["已有规则"], subscriptions["@existing_channel"]["douban_titles"])
        self.assertTrue(subscriptions["@new_channel"]["enabled"])
        self.assertFalse(subscriptions["@new_channel"]["auto_transfer"])
        self.assertFalse(subscriptions["@new_channel"]["require_douban_match"])

    def test_delete_channels_removes_only_mediaindex_rows(self):
        first = upsert_channel_subscription("@delete_me", display_name="待删频道")
        keep = upsert_channel_subscription("@keep_me", display_name="保留频道")
        process_channel_post({
            "message_id": 9,
            "chat": {"id": "-100999", "username": "delete_me"},
            "text": "测试电影 https://pan.quark.cn/s/delete-me",
        })

        result = delete_channel_subscriptions([first["id"], 999999])

        self.assertEqual([first["id"]], result["deleted_ids"])
        self.assertEqual([999999], result["missing_ids"])
        self.assertEqual([keep["id"]], [item["id"] for item in list_channel_subscriptions()])
        with db() as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM channel_messages WHERE subscription_id=?", (first["id"],)).fetchone()[0])
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM channel_resources WHERE subscription_id=?", (first["id"],)).fetchone()[0])

    def test_bot_channel_post_matches_an_imported_public_username(self):
        imported = import_pansou_channels(["@public_movies"])["imported"][0]
        result = process_channel_post({
            "message_id": 10,
            "chat": {"id": "-100456", "username": "Public_Movies"},
            "text": "测试电影 https://pan.quark.cn/s/from-bot",
        })

        self.assertEqual(imported["channel_id"], result["channel_id"])
        self.assertEqual("matched", result["state"])

    def test_subscribed_channel_requires_exact_wishlist_match_before_auto_transfer(self):
        upsert_channel_subscription("-100123", auto_transfer=False)
        result = process_channel_post(self._post())

        self.assertEqual("matched", result["state"])
        self.assertEqual(1, result["link_count"])
        self.assertEqual(1, len(list_channel_messages()))

    def test_channel_post_is_deduplicated_by_channel_and_message_id(self):
        upsert_channel_subscription("-100123", auto_transfer=False)
        first = process_channel_post(self._post())
        second = process_channel_post(self._post())

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(1, len(list_channel_messages()))

    def test_douban_filter_blocks_wishlist_match_when_title_not_in_imported_list(self):
        upsert_channel_subscription("-100123", auto_transfer=True, require_douban_match=True, douban_titles=["另一个标题"])
        with patch("app.services.channel_monitor._enqueue_transfer") as enqueue:
            result = process_channel_post(self._post())

        self.assertEqual("ignored", result["state"])
        enqueue.assert_not_called()

    def test_auto_transfer_reuses_native_quark_unified_transfer_pipeline(self):
        upsert_channel_subscription("-100123", auto_transfer=True)
        with patch("app.services.channel_monitor._enqueue_transfer", return_value=88) as enqueue:
            result = process_channel_post(self._post())

        self.assertEqual("transfer_started", result["state"])
        self.assertEqual(88, result["transfer_job_id"])
        self.assertEqual("https://pan.quark.cn/s/abc123", enqueue.call_args.args[1])
        self.assertEqual("quark", enqueue.call_args.args[3])

    def test_115_share_uses_the_same_wishlist_gate_and_selects_p115_provider(self):
        upsert_channel_subscription("-100123", auto_transfer=True)
        with patch("app.services.channel_monitor._enqueue_transfer", return_value=99) as enqueue:
            result = process_channel_post(self._post(text="测试电影 https://115.com/s/share123?password=abcd"))

        self.assertEqual("transfer_started", result["state"])
        self.assertEqual("p115", enqueue.call_args.args[3])

    def test_unmatched_post_still_becomes_a_global_search_candidate(self):
        upsert_channel_subscription("https://t.me/public_movies", display_name="公开影视源", auto_transfer=False)
        result = process_channel_post({
            "message_id": 31,
            "chat": {"id": "@public_movies"},
            "date": "2026-08-20T10:00:00+00:00",
            "text": "新片发布 测试新电影 2026 4K https://pan.quark.cn/s/newmovie",
        })

        with patch("app.services.channel_source_poller.sync_public_channels") as sync:
            candidates = search_channel_resources(MediaTarget(200, "movie", "测试新电影", series_year="2026"))

        self.assertEqual("needs_review", result["state"])
        self.assertEqual(1, result["indexed_resource_count"])
        self.assertEqual("https://pan.quark.cn/s/newmovie", candidates[0]["share_url"])
        self.assertEqual("telegram:公开影视源", candidates[0]["source"])
        sync.assert_not_called()

    def test_auto_save_applies_independent_positive_and_negative_keywords(self):
        upsert_channel_subscription(
            "-100123",
            auto_save_resources=True,
            positive_keywords=["4K"],
            negative_keywords=["广告"],
            cloud_download_child="电影暂存",
        )
        with patch("app.services.channel_monitor._resource_transfer_starter") as starter:
            accepted = process_channel_post(self._post(
                message_id=41,
                text="测试电影 4K https://pan.quark.cn/s/accepted",
            ))
            blocked = process_channel_post(self._post(
                message_id=42,
                text="测试电影 4K 广告 https://pan.quark.cn/s/blocked",
            ))

        self.assertEqual("transfer_queued", accepted["state"])
        self.assertEqual("ignored", blocked["state"])
        starter.assert_called_once()
        self.assertEqual("电影暂存", starter.call_args.args[5])
        self.assertEqual("quark", starter.call_args.args[3])

    def test_auto_classification_is_fail_closed_when_post_is_ambiguous(self):
        upsert_channel_subscription(
            "-100123",
            auto_save_resources=True,
            auto_classify=True,
        )
        with patch("app.services.channel_monitor._resource_transfer_starter") as starter:
            result = process_channel_post(self._post(
                message_id=51,
                text="测试电影 电视剧合集 https://115.com/s/ambiguous",
            ))

        starter.assert_not_called()
        self.assertEqual("transfer_failed", result["state"])
        with db() as conn:
            resource = conn.execute(
                "SELECT transfer_message FROM channel_resources WHERE channel_message_id=?",
                (result["id"],),
            ).fetchone()
        self.assertIn("分类", resource["transfer_message"])

    def test_auto_save_requires_a_direct_cloud_download_child_when_not_classifying(self):
        with self.assertRaisesRegex(ChannelMonitorError, "直属子目录"):
            upsert_channel_subscription("-100123", auto_save_resources=True)

    def test_channel_previews_do_not_persist_resource_links(self):
        upsert_channel_subscription("-100123")
        raw_link = "https://pan.quark.cn/s/private-token"
        result = process_channel_post(self._post(message_id=61, text=f"测试电影 {raw_link}"))
        with db() as conn:
            resource = conn.execute(
                "SELECT source_title,content_preview FROM channel_resources WHERE channel_message_id=?",
                (result["id"],),
            ).fetchone()

        self.assertNotIn(raw_link, result["text_preview"])
        self.assertNotIn(raw_link, resource["source_title"])
        self.assertNotIn(raw_link, resource["content_preview"])
        self.assertIn("[资源链接]", result["text_preview"])


if __name__ == "__main__":
    unittest.main()
