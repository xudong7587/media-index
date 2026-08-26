import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.wishlist import WishlistEnabledUpdate, WishlistProviderUpdate, list_wishlist, update_wishlist_enabled, update_wishlist_provider
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.wishlist_engine import run_wishlist_item


class WishlistApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "ENABLED_CLOUD_PROVIDERS": "qas,p115",
                "P115_COOKIE": "UID=1_A1_1; CID=test; SEID=test",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_provider_rows_are_independent_but_returned_as_one_card(self):
        with db() as conn:
            item_id = conn.execute(
                """
                INSERT INTO wishlist(tmdb_id,media_type,title,provider,status,check_hour)
                VALUES(7,'movie','测试电影','qas','pending',9)
                """
            ).lastrowid

        enabled = update_wishlist_provider(
            int(item_id), WishlistProviderUpdate(provider="p115", enabled=True)
        )
        self.assertTrue(enabled["enabled"])
        grouped = list_wishlist()
        self.assertEqual(1, len(grouped))
        self.assertEqual(
            {"qas", "p115"},
            {state["provider"] for state in grouped[0]["provider_states"]},
        )

        disabled = update_wishlist_provider(
            int(item_id), WishlistProviderUpdate(provider="p115", enabled=False)
        )
        self.assertFalse(disabled["enabled"])
        self.assertEqual(["qas"], [state["provider"] for state in list_wishlist()[0]["provider_states"]])

    def test_inspection_switch_updates_all_provider_rows(self):
        with db() as conn:
            first = conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(8,'movie','测试','qas','pending')").lastrowid
            conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(8,'movie','测试','p115','pending')")
        result = update_wishlist_enabled(int(first), WishlistEnabledUpdate(enabled=False))
        self.assertFalse(result["enabled"])
        with db() as conn:
            values = [row[0] for row in conn.execute("SELECT enabled FROM wishlist WHERE tmdb_id=8").fetchall()]
        self.assertEqual([0, 0], values)
        self.assertFalse(list_wishlist()[0]["enabled"])

    @patch("app.services.wishlist_engine.resolve_wishlist_target", side_effect=RuntimeError("offline"))
    @patch("app.services.wishlist_engine.execute_transfer_v2")
    def test_no_resource_patrol_enters_retry_without_local_variable_error(self, execute_transfer, _target):
        execute_transfer.return_value = {
            "ok": False,
            "stage": "no_resource",
            "message": "暂未找到资源",
            "resolution": {},
        }
        with db() as conn:
            item_id = conn.execute(
                "INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(99,'movie','待上映电影','qas','pending')"
            ).lastrowid

        result = run_wishlist_item(int(item_id))

        self.assertFalse(result["ok"])
        self.assertEqual("no_resource", result["stage"])
        with db() as conn:
            row = conn.execute("SELECT status,next_check_at FROM wishlist WHERE id=?", (item_id,)).fetchone()
        self.assertEqual("retry_wait", row["status"])
        self.assertTrue(row["next_check_at"])


if __name__ == "__main__":
    unittest.main()
