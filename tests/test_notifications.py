import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.notifications import MarkReadRequest, clear_notifications, list_notifications, mark_notifications_read
from app.api.tracking import run_now
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.notifications import add_notification


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
