import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.wishlist import WishlistEnabledUpdate, WishlistProviderUpdate, list_wishlist, update_wishlist_enabled, update_wishlist_provider
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.wishlist_engine import run_wishlist_item
from app.services.wishlist_engine import _recover_unavailable_reviews
import json


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

    def test_magnet_download_is_submitted_and_not_retried_as_missing(self):
        from app.services.direct_link_transfer import DirectLinkResult, _finish_job
        with db() as conn:
            item_id = conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(16605,'movie','生命翻筋斗','p115','pending')").lastrowid
        resolution = {"ok": True, "stage": "cloud_download_ready", "provider": "p115",
                      "target": {"tmdb_id": 16605, "title": "生命翻筋斗"},
                      "resolution": {"share_url": "magnet:?xt=urn:btih:" + "a" * 40}}
        def submit(job_id, target, link):
            with db() as conn:
                conn.execute("UPDATE transfer_jobs SET status='triggered',stage='provider_target_monitoring' WHERE id=?", (job_id,))
            return DirectLinkResult(True, job_id, "已提交")
        with patch("app.services.wishlist_engine.execute_transfer_v2", return_value=resolution), patch("app.services.direct_link_transfer.submit_discovery_cloud_download", side_effect=submit) as download:
            result = run_wishlist_item(item_id)
            self.assertTrue(result["ok"])
            download.assert_called_once()
            self.assertEqual("duplicate_active", run_wishlist_item(item_id)["stage"])
        with db() as conn:
            row = conn.execute("SELECT status,next_check_at FROM wishlist WHERE id=?", (item_id,)).fetchone()
        self.assertEqual("triggered", row["status"])
        self.assertIsNone(row["next_check_at"])
        _finish_job(result["job_id"], "done", "provider_completed", "已核验")
        with db() as conn:
            self.assertEqual("completed", conn.execute("SELECT status FROM wishlist WHERE id=?", (item_id,)).fetchone()[0])

    def test_magnet_monitor_terminal_result_is_not_overwritten_by_submission(self):
        from app.services.direct_link_transfer import DirectLinkResult, _finish_job
        for index, terminal in enumerate(("done", "failed", "needs_review"), start=1):
            with self.subTest(terminal=terminal):
                with db() as conn:
                    item_id = conn.execute(
                        "INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(?,'movie','电影','p115','pending')",
                        (80000 + index,),
                    ).lastrowid
                resolution = {"ok": True, "stage": "cloud_download_ready", "provider": "p115",
                              "target": {"tmdb_id": 80000 + index, "title": "电影"},
                              "resolution": {"share_url": "magnet:?xt=urn:btih:" + "a" * 40}}
                def submit(job_id, target, link):
                    _finish_job(job_id, terminal, "provider_completed" if terminal == "done" else "provider_target_unverified", "监控结果")
                    return DirectLinkResult(terminal == "done", job_id, "监控结果")
                with patch("app.services.wishlist_engine.execute_transfer_v2", return_value=resolution), patch("app.services.direct_link_transfer.submit_discovery_cloud_download", side_effect=submit):
                    result = run_wishlist_item(item_id)
                with db() as conn:
                    row = conn.execute("SELECT status,next_check_at,last_error FROM wishlist WHERE id=?", (item_id,)).fetchone()
                    job = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (result["job_id"],)).fetchone()
                self.assertEqual(terminal, job["status"])
                self.assertEqual("completed" if terminal == "done" else "needs_review", row["status"])
                self.assertIsNone(row["next_check_at"])
                self.assertEqual("" if terminal == "done" else "监控结果", row["last_error"])

    def test_magnet_submission_exception_schedules_retry_instead_of_staying_triggered(self):
        with db() as conn:
            item_id = conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(80004,'movie','电影','p115','pending')").lastrowid
        resolution = {"ok": True, "stage": "cloud_download_ready", "provider": "p115",
                      "target": {"tmdb_id": 80004, "title": "电影"},
                      "resolution": {"share_url": "magnet:?xt=urn:btih:" + "a" * 40}}
        with patch("app.services.wishlist_engine.execute_transfer_v2", return_value=resolution), patch("app.services.direct_link_transfer.submit_discovery_cloud_download", side_effect=ValueError("invalid destination")), patch("app.services.wishlist_engine.resolve_wishlist_target", side_effect=OSError("offline")):
            result = run_wishlist_item(item_id)
        self.assertEqual("provider_failed", result["stage"])
        with db() as conn:
            row = conn.execute("SELECT status,next_check_at FROM wishlist WHERE id=?", (item_id,)).fetchone()
        self.assertEqual("retry_wait", row["status"])
        self.assertTrue(row["next_check_at"])

    def test_stopped_download_does_not_complete_linked_wishlist(self):
        from app.services.direct_link_transfer import _finish_job
        with db() as conn:
            item_id = conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(80005,'movie','电影','p115','pending')").lastrowid
            job_id = conn.execute("INSERT INTO transfer_jobs(wishlist_id,tmdb_id,media_type,target,provider,status) VALUES(?,80005,'movie','cloud','p115','stopped')", (item_id,)).lastrowid
        _finish_job(job_id, "done", "provider_completed", "迟到的监控结果")
        with db() as conn:
            self.assertEqual("pending", conn.execute("SELECT status FROM wishlist WHERE id=?", (item_id,)).fetchone()[0])
            self.assertEqual("stopped", conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()[0])

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

    @patch("app.services.wishlist_engine.notify_review_required")
    @patch("app.services.wishlist_engine.resolve_wishlist_target", side_effect=RuntimeError("offline"))
    @patch("app.services.wishlist_engine.execute_transfer_v2")
    def test_unreadable_provider_retries_without_freezing_as_manual_review(self, execute_transfer, _target, notify):
        execute_transfer.return_value = {
            "ok": False, "stage": "needs_review", "message": "夸克接口暂时无法读取分享",
            "resolution": {"reviewed_candidates": [{
                "share_url": "https://pan.quark.cn/s/candidate", "provider": "quark",
                "cloud_type": "quark", "reasons": ["provider_inspection_unavailable"], "files": [],
            }]},
        }
        with db() as conn:
            item_id = conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES(99,'movie','挖掘者','quark','pending')").lastrowid
        result = run_wishlist_item(int(item_id))
        assert result["stage"] == "provider_failed"
        notify.assert_not_called()
        with db() as conn:
            row = conn.execute("SELECT status,next_check_at FROM wishlist WHERE id=?", (item_id,)).fetchone()
            job = conn.execute("SELECT status,stage FROM transfer_jobs WHERE wishlist_id=?", (item_id,)).fetchone()
        assert row["status"] == "retry_wait" and row["next_check_at"]
        assert job["stage"] == "provider_failed" and job["status"] == "failed"

    def test_historical_api_failure_recovers_only_without_user_choice_or_ambiguity(self):
        now = "2026-10-10T06:00:00+00:00"
        ids = []
        with db() as conn:
            for index, (reasons, files, enabled, decision, checked) in enumerate([
                (["provider_inspection_unavailable"], [], 1, "pending", "2026-10-09 01:00:00"),
                (["title"], ["版本A.mp4", "版本B.mp4"], 1, "pending", "2026-10-09 01:00:00"),
                (["provider_inspection_unavailable"], [], 0, "pending", "2026-10-09 01:00:00"),
                (["provider_inspection_unavailable"], [], 1, "approved", "2026-10-09 01:00:00"),
                (["provider_inspection_unavailable"], [], 1, "pending", "2026-10-10 05:30:00"),
            ]):
                item_id = conn.execute("INSERT INTO wishlist(tmdb_id,media_type,title,provider,status,enabled,last_checked_at) VALUES(?,'movie','测试','quark','needs_review',?,?)", (100 + index, enabled, checked)).lastrowid
                ids.append(item_id)
                job = conn.execute("INSERT INTO transfer_jobs(wishlist_id,target,provider,status,stage) VALUES(?,'cloud','quark','needs_review','needs_review')", (item_id,)).lastrowid
                conn.execute("INSERT INTO candidates(job_id,share_url,reasons_json,files_json,decision) VALUES(?,'https://pan.quark.cn/s/test',?,?,?)", (job, json.dumps(reasons), json.dumps(files), decision))
        _recover_unavailable_reviews(now, 3)
        with db() as conn:
            rows = [dict(conn.execute("SELECT status,next_check_at FROM wishlist WHERE id=?", (item_id,)).fetchone()) for item_id in ids]
        assert rows[0] == {"status": "retry_wait", "next_check_at": now}
        assert all(row["status"] == "needs_review" for row in rows[1:])


if __name__ == "__main__":
    unittest.main()
