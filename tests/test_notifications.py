import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.notifications import MarkReadRequest, clear_notifications, list_notifications, mark_notifications_read
from app.api.tracking import run_now
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.notifications import (
    add_notification,
    deliver_notification,
    deliver_pending_library_notifications,
)
from app.services.post_transfer_pipeline import _notify_if_enabled


class NotificationTests(unittest.TestCase):
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

    @patch("app.services.notifications.cache_tmdb_poster", return_value="cached-poster")
    def test_terminal_transfer_is_synced_once_and_uses_linked_media_title(self, cache_poster):
        with db() as conn:
            wishlist_id = conn.execute(
                """
                INSERT INTO wishlist(tmdb_id,media_type,title,poster_url,status)
                VALUES(1,'movie','测试电影','https://image.tmdb.org/t/p/w500/test.jpg','pending')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO transfer_jobs(wishlist_id,target,status,stage,message,finished_at)
                VALUES(?,'cloud','needs_review','needs_review','请选择候选资源',CURRENT_TIMESTAMP)
                """,
                (wishlist_id,),
            )

        first = list_notifications(limit=20, unread_only=False)
        second = list_notifications(limit=20, unread_only=False)

        self.assertEqual(1, first["unread_count"])
        self.assertEqual(1, len(second["items"]))
        self.assertEqual("测试电影 需要确认", first["items"][0]["title"])
        self.assertEqual("review", first["items"][0]["action_page"])
        self.assertEqual(
            "/api/notifications/wecom/posters/cached-poster",
            first["items"][0]["poster_url"],
        )
        cache_poster.assert_called_once()

    def test_read_filter_and_soft_clear(self):
        with db() as conn:
            conn.execute(
                """
                INSERT INTO notifications(source_key,type,title,message)
                VALUES('test:1','info','测试通知','通知内容')
                """
            )

        feed = list_notifications(limit=20, unread_only=True)
        notification_id = feed["items"][0]["id"]
        mark_notifications_read(MarkReadRequest(id=notification_id))

        self.assertEqual([], list_notifications(limit=20, unread_only=True)["items"])
        self.assertEqual(0, list_notifications(limit=20, unread_only=False)["unread_count"])

        clear_notifications()
        self.assertEqual([], list_notifications(limit=20, unread_only=False)["items"])

    @patch("app.services.notifications.deliver_notification")
    def test_direct_notification_is_immediately_delivered_to_external_channels(self, deliver):
        created = add_notification(
            "tracking:1:manual:test",
            "info",
            "手动追更检查完成",
            "当前没有已播出且尚未保存的新内容",
            "tracking",
        )

        self.assertTrue(created)
        deliver.assert_called_once()

    def test_library_notifications_are_aggregated_by_media_folder(self):
        with db() as conn:
            first = conn.execute("INSERT INTO transfer_jobs(provider,target,status,stage,display_title,save_path) VALUES('p115','cloud','done','provider_completed','测试剧 E01','/媒体库/测试剧/Season 1')").lastrowid
            second = conn.execute("INSERT INTO transfer_jobs(provider,target,status,stage,display_title,save_path) VALUES('p115','cloud','done','provider_completed','测试剧 E02','/媒体库/测试剧/Season 1')").lastrowid
        with patch.dict(os.environ, {"NOTIFICATION_EXTERNAL_ENABLED": "true"}, clear=False), patch("app.services.post_transfer_pipeline.update_media_workflow_step"):
            get_settings.cache_clear()
            _notify_if_enabled(int(first), title="测试剧", poster_url="", message="E01 已入库")
            _notify_if_enabled(int(second), title="测试剧", poster_url="", message="E02 已入库")
        with db() as conn:
            rows = conn.execute("SELECT source_key,external_status FROM notifications WHERE source_key LIKE 'library-ready:%'").fetchall()
        self.assertEqual(1, len(rows))
        self.assertEqual("", rows[0]["external_status"])

    @patch("app.services.notifications.deliver_notification")
    def test_delayed_library_delivery_skips_upgrade_backlog_but_keeps_recent_events(self, deliver):
        with db() as conn:
            old_id = int(conn.execute(
                """
                INSERT INTO notifications(source_key,type,title,created_at)
                VALUES('library-ready:old','success','历史入库',datetime('now','-2 days'))
                """
            ).lastrowid)
            recent_id = int(conn.execute(
                """
                INSERT INTO notifications(source_key,type,title,created_at)
                VALUES('library-ready:recent','success','新入库',datetime('now','-3 minutes'))
                """
            ).lastrowid)

        delivered = deliver_pending_library_notifications()

        self.assertEqual(1, delivered)
        deliver.assert_called_once_with(recent_id)
        with db() as conn:
            old = conn.execute(
                "SELECT external_status,external_error FROM notifications WHERE id=?",
                (old_id,),
            ).fetchone()
        self.assertEqual("skipped", old["external_status"])
        self.assertIn("24 小时", old["external_error"])

    @patch("app.services.notifications.send_configured_channels")
    @patch("app.services.notifications.cache_emby_item_poster", return_value="emby-cached-poster")
    def test_delayed_emby_notification_retries_private_poster_before_delivery(self, cache_emby, send_channels):
        send_channels.return_value = []
        with db() as conn:
            notification_id = conn.execute(
                """
                INSERT INTO notifications(source_key,type,title,message,action_page,poster_url,created_at)
                VALUES('library-ready:emby:test','success','测试剧 已入库','已入库','media-server',
                       'emby-item:item-102382','2026-08-25 00:00:00')
                """
            ).lastrowid
        with patch.dict(
            os.environ,
            {
                "NOTIFICATION_EXTERNAL_ENABLED": "true",
                "NOTIFICATION_ENABLED_AT": "2020-01-01T00:00:00+00:00",
                "NOTIFICATION_EVENT_TYPES": "library",
                "PUBLIC_BASE_URL": "https://media.example",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            deliver_notification(int(notification_id))

        cache_emby.assert_called_once_with("item-102382")
        self.assertEqual(
            "https://media.example/api/notifications/wecom/posters/emby-cached-poster",
            send_channels.call_args.args[3],
        )
        with db() as conn:
            row = conn.execute("SELECT poster_key FROM notifications WHERE id=?", (notification_id,)).fetchone()
        self.assertEqual("emby-cached-poster", row["poster_key"])

    @patch("app.api.emby._cache_emby_notification_poster", return_value="")
    def test_emby_library_title_prefers_series_name_and_defers_item_poster(self, _cache):
        from app.api.emby import _queue_emby_library_notification

        inserted = _queue_emby_library_notification(
            {
                "Event": "library.new",
                "SeriesId": "102382",
                "SeriesName": "凭依杂雯推主",
                "Item": {"Id": "episode-7", "Name": "奇迹的圣诞节礼物"},
            },
            "入库",
        )

        self.assertTrue(inserted)
        with db() as conn:
            row = conn.execute("SELECT title,poster_url FROM notifications ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual("凭依杂雯推主 已入库", row["title"])
        self.assertEqual("emby-item:episode-7", row["poster_url"])

    @patch("app.services.notifications.send_configured_channels")
    @patch("app.api.emby._cached_emby_group_poster", return_value="")
    @patch("app.api.emby._cache_emby_notification_poster", return_value="")
    def test_emby_folder_deletion_is_one_rich_notification_with_sidecar_poster(self, _emby, _cached, send_channels):
        from app.api.emby import _queue_emby_library_notification

        strm_root = Path(self.tempdir.name) / "strm"
        cache_root = Path(self.tempdir.name) / "cache"
        media_folder = strm_root / "测试剧"
        media_folder.mkdir(parents=True)
        (media_folder / "poster.jpg").write_bytes(b"\xff\xd8\xff" + b"sidecar-poster")
        with patch.dict(
            os.environ,
            {
                "STRM_OUTPUT_ROOT": str(strm_root),
                "CACHE_DIR": str(cache_root),
                "NOTIFICATION_EXTERNAL_ENABLED": "true",
                "NOTIFICATION_ENABLED_AT": "2020-01-01T00:00:00+00:00",
                "NOTIFICATION_EVENT_TYPES": "library",
                "PUBLIC_BASE_URL": "https://media.example",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            payload = {"Event": "item.deleted", "SeriesId": "series-7", "SeriesName": "测试剧"}
            self.assertTrue(_queue_emby_library_notification(payload, "删除", relative_strm_path="测试剧"))
            self.assertFalse(_queue_emby_library_notification(payload, "删除", relative_strm_path="测试剧"))
            with db() as conn:
                row = conn.execute(
                    "SELECT id,title,poster_key FROM notifications WHERE source_key LIKE 'library-ready:emby:删除:%'"
                ).fetchone()
            deliver_notification(int(row["id"]))

        self.assertEqual("测试剧 删除同步完成", row["title"])
        self.assertTrue(row["poster_key"])
        self.assertIn("/api/notifications/wecom/posters/", send_channels.call_args.args[3])

    @patch("app.api.tracking.run_tracking_task")
    @patch("app.services.notifications.cache_tmdb_poster", return_value="cached-poster")
    def test_manual_tracking_without_due_episode_creates_feedback(self, _cache_poster, run_task):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,poster_url,status,decision_state)
                VALUES(7,'tv','喜剧之王单口季','https://image.test/poster.jpg','active','idle')
                """
            ).lastrowid
        run_task.return_value = {
            "ok": True,
            "stage": "not_due",
            "next_check_at": "2026-07-18T02:00:00+00:00",
        }

        run_now(int(task_id))
        feed = list_notifications(limit=20, unread_only=False)

        self.assertEqual(1, feed["unread_count"])
        self.assertEqual("喜剧之王单口季 手动追更检查完成", feed["items"][0]["title"])
        self.assertIn("当前没有已播出", feed["items"][0]["message"])
        self.assertIn("07月18日 10:00", feed["items"][0]["message"])
        self.assertEqual("tracking", feed["items"][0]["action_page"])

    @patch("app.api.tracking.run_tracking_task")
    def test_manual_tracking_terminal_job_uses_transfer_notification(self, run_task):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,status,decision_state)
                VALUES(8,'tv','测试追更','active','idle')
                """
            ).lastrowid

        def create_triggered_job(_task_id, **_kwargs):
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO transfer_jobs(task_id,target,status,stage,message)
                    VALUES(?,'cloud','triggered','qas_transferring','等待 QAS 确认')
                    """,
                    (_task_id,),
                )
            return {"ok": True, "stage": "qas_transferring"}

        run_task.side_effect = create_triggered_job
        run_now(int(task_id))
        feed = list_notifications(limit=20, unread_only=False)

        self.assertEqual(1, len(feed["items"]))
        self.assertEqual("测试追更 转存任务已提交", feed["items"][0]["title"])


if __name__ == "__main__":
    unittest.main()
