import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.notifications import MarkReadRequest, clear_notifications, list_notifications, mark_notifications_read
from app.core.config import get_settings
from app.db.database import db, init_db


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

    def test_terminal_transfer_is_synced_once_and_uses_linked_media_title(self):
        with db() as conn:
            wishlist_id = conn.execute(
                "INSERT INTO wishlist(tmdb_id,media_type,title,status) VALUES(1,'movie','测试电影','pending')"
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


if __name__ == "__main__":
    unittest.main()
