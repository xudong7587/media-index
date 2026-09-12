import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import EpisodeTarget, MediaTarget
from app.api.tracking import list_tracking, resume_tracking, update_final_episode, TrackingFinalEpisodeUpdate
from app.services.saved_episode_scanner import refresh_saved_episodes, SavePathProgress
from app.services.tracking_completion import reconcile_tracking_completion
from app.services.tracking_engine_v2 import refresh_tracking_task_metadata, sync_tracking_episodes, prepare_tracking_cycle
from app.services.tracking_run_dispatch import enqueue_tracking_run


class TrackingCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DB_PATH": str(Path(self.temp.name) / "test.db")})
        self.env.start()
        get_settings.cache_clear()
        init_db()
        with db() as conn:
            self.task_id = conn.execute("""INSERT INTO tracking_tasks
                (tmdb_id,media_type,title,season_number,provider,status,decision_state,storage_inventory_verified)
                VALUES(17,'tv','完成测试',1,'p115','active','idle',1)""").lastrowid

    def tearDown(self):
        self.env.stop()
        get_settings.cache_clear()
        self.temp.cleanup()

    def target(self, count=3, *, ended=True):
        return MediaTarget(17, "tv", "完成测试", season_number=1, status="Ended" if ended else "Returning Series",
                           episodes=tuple(EpisodeTarget(1, n, "2026-01-01") for n in range(1, count + 1)))

    def save_all(self):
        with db() as conn:
            conn.execute("UPDATE tracking_episodes SET status='saved' WHERE task_id=?", (self.task_id,))

    def task(self):
        with db() as conn:
            return dict(conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (self.task_id,)).fetchone())

    def test_retracted_and_storage_only_ordinals_do_not_inflate_season(self):
        sync_tracking_episodes(self.task_id, self.target(5))
        self.save_all()
        refresh_tracking_task_metadata(self.task_id, self.target(3))
        with patch("app.services.saved_episode_scanner.resolve_save_path_progress", return_value=SavePathProgress("/tv", 99, frozenset({1, 2, 3, 99}), True, True)):
            refresh_saved_episodes(self.task_id, qas=object())
        state = list_tracking()[0]["provider_states"][0]
        self.assertEqual((3, 3, 3), (state["episode_count"], state["saved_count"], state["last_saved_episode"]))
        with db() as conn:
            self.assertEqual(6, conn.execute("SELECT COUNT(*) FROM tracking_episodes").fetchone()[0])
        self.assertEqual("archived", self.task()["status"])

    def test_empty_snapshot_keeps_history(self):
        sync_tracking_episodes(self.task_id, self.target())
        with self.assertRaises(ValueError):
            sync_tracking_episodes(self.task_id, self.target(0))
        self.assertEqual(3, list_tracking()[0]["provider_states"][0]["episode_count"])

    def test_caught_up_returning_series_finale_does_not_archive(self):
        target = self.target(ended=False)
        sync_tracking_episodes(self.task_id, target)
        self.save_all()
        self.assertEqual("caught_up", reconcile_tracking_completion(self.task_id))
        self.assertEqual("active", self.task()["status"])
        target = replace(target, episodes=(*target.episodes[:-1], replace(target.episodes[-1], episode_type="finale")))
        refresh_tracking_task_metadata(self.task_id, target)
        self.assertEqual("active", self.task()["status"])
        self.assertEqual("caught_up", self.task()["completion_state"])
        self.assertTrue(self.task()["next_check_at"])

    def test_fanren_191_reopens_automatic_archive_without_resetting_saved_history(self):
        target = self.target(190)
        sync_tracking_episodes(self.task_id, target)
        self.save_all()
        reconcile_tracking_completion(self.task_id)
        self.assertEqual("archived", self.task()["status"])
        target = self.target(191, ended=False)
        with patch("app.services.tracking_engine_v2.resolve_media_target", return_value=target):
            from app.services.tracking_engine_v2 import refresh_tracking_metadata
            refresh_tracking_metadata()
        self.assertEqual("active", self.task()["status"])
        self.assertTrue(self.task()["next_check_at"])
        with db() as conn:
            self.assertEqual(190, conn.execute("SELECT COUNT(*) FROM tracking_episodes WHERE status='saved'").fetchone()[0])
            self.assertEqual("pending", conn.execute("SELECT status FROM tracking_episodes WHERE episode_number=191").fetchone()[0])

    def test_manual_final_archive_is_not_reopened_by_new_metadata(self):
        sync_tracking_episodes(self.task_id, self.target(3, ended=False))
        self.save_all()
        update_final_episode(self.task_id, TrackingFinalEpisodeUpdate(final_episode=3))
        refresh_tracking_task_metadata(self.task_id, self.target(4, ended=False))
        self.assertEqual("archived", self.task()["status"])

    def test_hole_future_date_unknown_date_and_unverified_storage_block_archive(self):
        target = self.target()
        for reason in ("missing", "future", "unknown", "unverified", "triggered", "metadata_hole"):
            with self.subTest(reason=reason):
                sync_tracking_episodes(self.task_id, target)
                self.save_all()
                with db() as conn:
                    conn.execute("UPDATE tracking_tasks SET status='active',storage_inventory_verified=1")
                    if reason == "missing": conn.execute("UPDATE tracking_episodes SET status='pending' WHERE episode_number=2")
                    if reason == "future": conn.execute("UPDATE tracking_episodes SET air_date='2099-01-01' WHERE episode_number=3")
                    if reason == "unknown": conn.execute("UPDATE tracking_episodes SET air_date='' WHERE episode_number=3")
                    if reason == "unverified": conn.execute("UPDATE tracking_tasks SET storage_inventory_verified=0")
                    if reason == "triggered": conn.execute("UPDATE tracking_episodes SET status='triggered' WHERE episode_number=3")
                    if reason == "metadata_hole": conn.execute("UPDATE tracking_episodes SET metadata_active=0 WHERE episode_number=2")
                self.assertNotEqual("complete", reconcile_tracking_completion(self.task_id))
                self.assertEqual("active", self.task()["status"])

    def test_manual_final_is_reversible_and_resume_does_not_immediately_rearchive(self):
        target = self.target(5, ended=False)
        sync_tracking_episodes(self.task_id, target)
        with db() as conn:
            conn.execute("UPDATE tracking_episodes SET status='saved' WHERE episode_number<=3")
        update_final_episode(self.task_id, TrackingFinalEpisodeUpdate(final_episode=3))
        self.assertEqual("archived", self.task()["status"])
        with patch("app.api.tracking.resolve_media_target", return_value=target):
            resume_tracking(self.task_id)
        reconcile_tracking_completion(self.task_id)
        self.assertEqual("active", self.task()["status"])
        self.assertFalse(self.task()["auto_archive"])
        update_final_episode(self.task_id, TrackingFinalEpisodeUpdate(final_episode=None))
        self.assertEqual(5, list_tracking()[0]["provider_states"][0]["episode_count"])
        self.assertEqual("active", self.task()["status"])

    def test_active_transfer_blocks_archive_until_confirmation(self):
        sync_tracking_episodes(self.task_id, self.target())
        self.save_all()
        job = enqueue_tracking_run(self.task_id, selected_episode_numbers=(3,), request_source="tracking_fill")
        reconcile_tracking_completion(self.task_id)
        self.assertEqual("active", self.task()["status"])
        with db() as conn: conn.execute("UPDATE transfer_jobs SET status='done' WHERE id=?", (job["id"],))
        reconcile_tracking_completion(self.task_id)
        self.assertEqual("archived", self.task()["status"])

    def test_date_correction_reschedules_without_adding_episodes(self):
        target = self.target(ended=False)
        target = replace(target, episodes=(EpisodeTarget(1, 1, "2099-01-01"),))
        refresh_tracking_task_metadata(self.task_id, target)
        first = self.task()["next_check_at"]
        result = refresh_tracking_task_metadata(self.task_id, replace(target, episodes=(EpisodeTarget(1, 1, "2026-01-01"),)))
        self.assertEqual([], result["added_episode_numbers"])
        self.assertLess(self.task()["next_check_at"], first)

    def test_running_ready_triggered_and_different_selections_share_one_slot(self):
        first = enqueue_tracking_run(self.task_id, selected_episode_numbers=(1, 2), request_source="tracking_fill")
        for status in ("running", "ready", "triggered"):
            with db() as conn: conn.execute("UPDATE transfer_jobs SET status=? WHERE id=?", (status, first["id"]))
            same = enqueue_tracking_run(self.task_id, selected_episode_numbers=(2, 1), request_source="tracking_fill")
            different = enqueue_tracking_run(self.task_id, selected_episode_numbers=(3,), request_source="tracking_fill")
            self.assertTrue(same["ok"])
            self.assertEqual(first["id"], same["id"])
            self.assertTrue(different["blocked"])
            self.assertFalse(different["ok"])
        with db() as conn: self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM transfer_jobs").fetchone()[0])

    def test_share_identity_and_scheduler_conflict_do_not_create_placeholder_jobs(self):
        first = enqueue_tracking_run(self.task_id, selected_episode_numbers=(1,), request_source="tracking_share_fill", approved_share_url="https://example.com/a")
        other = enqueue_tracking_run(self.task_id, selected_episode_numbers=(1,), request_source="tracking_share_fill", approved_share_url="https://example.com/b")
        self.assertTrue(other["blocked"])
        self.assertNotIn("example.com", self._job_key(first["id"]))
        self.assertTrue(prepare_tracking_cycle(self.task_id, request_source="tracking_scheduler")["blocked"])
        with db() as conn: self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM transfer_jobs").fetchone()[0])

    def _job_key(self, job_id):
        with db() as conn: return conn.execute("SELECT execution_key FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()[0]

    def test_concurrent_submissions_and_database_guard(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda n: enqueue_tracking_run(self.task_id, selected_episode_numbers=(n,), request_source="tracking_fill"), range(1, 7)))
        self.assertEqual(1, sum(not result["duplicate"] for result in results))
        with db() as conn:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "tracking execution already active"):
                conn.execute("INSERT INTO transfer_jobs(task_id,target,status,execution_key) VALUES(?,'cloud','running','tracking-cycle:other')", (self.task_id,))
        init_db()  # Additive migration remains repeatable with an active job.

    def test_provider_lanes_are_independent(self):
        with db() as conn:
            other = conn.execute("INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider) VALUES(17,'tv','完成测试',1,'quark')").lastrowid
        first = enqueue_tracking_run(self.task_id, selected_episode_numbers=(1,), request_source="tracking_fill")
        second = enqueue_tracking_run(other, selected_episode_numbers=(1,), request_source="tracking_fill")
        self.assertTrue(first["ok"] and second["ok"])
        self.assertNotEqual(first["id"], second["id"])

    def test_old_database_upgrade_preserves_history_and_uses_safe_defaults(self):
        sync_tracking_episodes(self.task_id, self.target())
        with db() as conn:
            for column in ("final_episode_override", "season_complete", "completion_state", "archived_at", "auto_archive", "storage_inventory_verified"):
                conn.execute(f"ALTER TABLE tracking_tasks DROP COLUMN {column}")
            conn.execute("ALTER TABLE tracking_episodes DROP COLUMN metadata_active")
            for key in ("legacy-a", "legacy-b"):
                conn.execute("INSERT INTO transfer_jobs(task_id,target,status,execution_key) VALUES(?,'cloud','triggered',?)", (self.task_id, key))
        init_db()
        self.assertIsNone(self.task()["final_episode_override"])
        self.assertFalse(self.task()["storage_inventory_verified"])
        with db() as conn:
            self.assertEqual(3, conn.execute("SELECT COUNT(*) FROM tracking_episodes WHERE metadata_active=1").fetchone()[0])
            self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM transfer_jobs WHERE status='triggered'").fetchone()[0])
        self.assertTrue(enqueue_tracking_run(self.task_id, selected_episode_numbers=(1,), request_source="tracking_fill")["blocked"])

    def test_retry_interval_survives_unchanged_metadata(self):
        sync_tracking_episodes(self.task_id, self.target(ended=False))
        with db() as conn:
            conn.execute("UPDATE tracking_tasks SET decision_state='retry_wait',next_check_at='2099-01-01T00:00:00+00:00'")
        refresh_tracking_task_metadata(self.task_id, self.target(ended=False))
        self.assertEqual("2099-01-01T00:00:00+00:00", self.task()["next_check_at"])

    def test_backup_keeps_manual_final_and_withdrawn_metadata(self):
        from app.api.config import _export_task_data, _restore_task_data, ConfigTaskBackup
        sync_tracking_episodes(self.task_id, self.target(5))
        sync_tracking_episodes(self.task_id, self.target(4))
        update_final_episode(self.task_id, TrackingFinalEpisodeUpdate(final_episode=3))
        backup = _export_task_data()
        _restore_task_data(ConfigTaskBackup(**backup))
        with db() as conn:
            restored = conn.execute("SELECT * FROM tracking_tasks").fetchone()
            self.assertEqual(3, restored["final_episode_override"])
            self.assertEqual(0, conn.execute("SELECT metadata_active FROM tracking_episodes WHERE episode_number=5").fetchone()[0])
        self.assertEqual(3, list_tracking()[0]["provider_states"][0]["episode_count"])

    def test_cross_cloud_fill_excludes_withdrawn_and_manually_excluded_episodes(self):
        from app.services.openlist_sync import sync_tracking_storage_between_providers
        sync_tracking_episodes(self.task_id, self.target(5))
        sync_tracking_episodes(self.task_id, self.target(4))
        update_final_episode(self.task_id, TrackingFinalEpisodeUpdate(final_episode=3))
        with patch("app.services.openlist_sync.get_settings", return_value=type("Settings", (), {"openlist_enabled": True, "tracking_timezone": "Asia/Shanghai"})()), patch("app.services.openlist_sync.sync_selected_tracking_episodes", return_value={"ok": True}) as sync:
            sync_tracking_storage_between_providers(self.task_id)
        sync.assert_called_once_with(self.task_id, [1, 2, 3])
