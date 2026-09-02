import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.qas_reconciler import (
    _confirmation_expired,
    reconcile_triggered_jobs,
    recover_interrupted_jobs,
    retry_failed_post_processing,
)
from app.services.tracking_engine_v2 import (
    prepare_tracking_cycle,
    resume_tracking_cycle,
    run_due_tracking_tasks,
    run_pending_tracking_post_processing,
    run_tracking_cycle,
)
from app.services.p115_completion import P115CompletionResult


class TrackingOpenListFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "OPENLIST_ENABLED": "true",
                "OPENLIST_URL": "http://openlist.test",
                "OPENLIST_TOKEN": "token",
                "OPENLIST_QAS_LIBRARY_PATH": "/夸克",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
            },
        )
        self.environment.start()
        self.reconcile_request = patch("app.services.qas_reconciler.request_qas_reconciliation", return_value=False)
        self.reconcile_request.start()
        get_settings.cache_clear()
        init_db()
        with db() as conn:
            self.quark_id = int(conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,season_number,provider,save_path,status,decision_state
                ) VALUES(100,'tv','Cycle Show',1,'quark','/strm/tv/Cycle Show/Season 1','active','idle')
                """
            ).lastrowid)
            self.p115_id = int(conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,season_number,provider,save_path,status,decision_state,
                    openlist_fallback_to_p115
                ) VALUES(100,'tv','Cycle Show',1,'p115','/媒体库/tv/Cycle Show/Season 1','active','idle',1)
                """
            ).lastrowid)
            conn.executemany(
                """
                INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,provider)
                VALUES(?,1,?,'retry_wait','p115')
                """,
                [(self.p115_id, 17), (self.p115_id, 18)],
            )

    def tearDown(self):
        self.reconcile_request.stop()
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def _native_result(self, task_id, *, force=False, job_id=None, **_kwargs):
        with db() as conn:
            provider = conn.execute("SELECT provider FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()[0]
            if provider == "quark":
                conn.execute(
                    """
                    UPDATE transfer_jobs SET status='done',stage='native_completed',
                        external_provider_status='post_processing_skipped',
                        rename_pairs_json=?,save_path='/strm/tv/Cycle Show/Season 1',finished_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (json.dumps([{"replacement": "Cycle.Show.S01E17.mkv", "episode_numbers": [17]}]), job_id),
                )
                return {
                    "ok": True,
                    "confirmed": True,
                    "stage": "native_completed",
                    "provider": "quark",
                    "job_id": job_id,
                    "episode_numbers": [17],
                }
            conn.execute(
                """
                UPDATE transfer_jobs SET status='retry_wait',stage='no_resource',rename_pairs_json=?,finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (json.dumps([{"_tracking_cycle": {"requested": [17]}}]), job_id),
            )
            return {
                "ok": False,
                "stage": "retry_wait",
                "resolution_stage": "no_resource",
                "provider": "p115",
                "job_id": job_id,
                "episode_numbers": [17],
            }

    def _confirm_p115_fallback(self):
        class ConfirmedP115:
            def reconcile(self, _path, expected):
                return bool(expected)

        with (
            patch("app.services.qas_reconciler.get_transfer_provider", return_value=ConfirmedP115()),
            patch("app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing", return_value=True),
        ):
            return reconcile_triggered_jobs()

    def test_cycle_waits_for_native_lanes_then_runs_explicit_quark_to_p115_fallback(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")
        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=self._native_result),
            patch(
                "app.services.tracking_engine_v2.sync_tracking_fallback_to_p115",
                return_value={
                    "ok": True,
                    "message": "已提交 1 集",
                    "job_id": 0,
                    "copied": [17],
                    "skipped": [],
                    "missing": [],
                    "files": [{"episode_number": 17, "file_name": "Cycle.Show.S01E17.mkv"}],
                },
            ) as fallback,
        ):
            results = run_tracking_cycle(int(cycle["batch_id"]))

        self.assertEqual(3, len(results))
        fallback.assert_called_once()
        self.assertEqual(self.p115_id, fallback.call_args.kwargs["target_task_id"])
        self.assertEqual([17], fallback.call_args.kwargs["episode_numbers"])
        with db() as conn:
            batch = conn.execute(
                "SELECT status,message FROM transfer_batches WHERE id=?",
                (cycle["batch_id"],),
            ).fetchone()
            pending_notification_count = int(conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE source_key=?",
                (f"tracking-cycle:{cycle['batch_id']}:terminal",),
            ).fetchone()[0])
        self.assertEqual("running", batch["status"])
        self.assertIn("等待 115", batch["message"])
        self.assertEqual(0, pending_notification_count)

        class ConfirmedP115:
            def reconcile(self, _path, expected):
                return expected == ["Cycle.Show.S01E17.mkv"]

        with (
            patch("app.services.qas_reconciler.get_transfer_provider", return_value=ConfirmedP115()),
            patch("app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing", return_value=True) as post_process,
        ):
            reconciled = reconcile_triggered_jobs()

        self.assertEqual(1, len(reconciled))
        self.assertTrue(reconciled[0]["confirmed"])
        post_process.assert_called_once()
        with db() as conn:
            batch = conn.execute(
                "SELECT status,message FROM transfer_batches WHERE id=?",
                (cycle["batch_id"],),
            ).fetchone()
            task = conn.execute(
                "SELECT decision_state,last_error,next_check_at FROM tracking_tasks WHERE id=?",
                (self.p115_id,),
            ).fetchone()
            episode = conn.execute(
                "SELECT status,last_error FROM tracking_episodes WHERE task_id=? AND episode_number=17",
                (self.p115_id,),
            ).fetchone()
            notification_count = int(conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE source_key=?",
                (f"tracking-cycle:{cycle['batch_id']}:terminal",),
            ).fetchone()[0])
            unmarked_job_count = int(conn.execute(
                """
                SELECT COUNT(*) FROM transfer_jobs
                WHERE id IN (SELECT job_id FROM transfer_batch_jobs WHERE batch_id=?)
                  AND notification_sent_at IS NULL
                """,
                (cycle["batch_id"],),
            ).fetchone()[0])
        self.assertEqual("done", batch["status"])
        self.assertIn("OpenList", batch["message"])
        self.assertEqual("pending", task["decision_state"])
        self.assertEqual("", task["last_error"])
        self.assertTrue(task["next_check_at"])
        self.assertEqual("saved", episode["status"])
        self.assertEqual("", episode["last_error"])
        self.assertEqual(1, notification_count)
        self.assertEqual(0, unmarked_job_count)

    def test_cycle_uses_existing_quark_episode_when_source_lane_is_not_due(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")

        def native_result(task_id, *, job_id=None, **_kwargs):
            with db() as conn:
                provider = conn.execute("SELECT provider FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()[0]
                if provider == "quark":
                    conn.execute(
                        "UPDATE transfer_jobs SET status='done',stage='not_due',external_provider_status='post_processing_skipped',finished_at=CURRENT_TIMESTAMP WHERE id=?",
                        (job_id,),
                    )
                    return {"ok": True, "stage": "not_due", "provider": "quark", "job_id": job_id, "episode_numbers": []}
                return self._native_result(task_id, job_id=job_id)

        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=native_result),
            patch(
                "app.services.tracking_engine_v2.sync_tracking_fallback_to_p115",
                return_value={"ok": True, "message": "已提交", "job_id": 0, "copied": [17], "skipped": [], "missing": [], "files": [{"episode_number": 17, "file_name": "Cycle.Show.S01E17.mkv"}]},
            ) as fallback,
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        fallback.assert_called_once_with(target_task_id=self.p115_id, episode_numbers=[17])

    def test_no_resource_without_an_actual_copy_finishes_quietly(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")

        def native_result(task_id, *, job_id=None, **_kwargs):
            with db() as conn:
                provider = conn.execute("SELECT provider FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()[0]
                if provider == "quark":
                    conn.execute(
                        "UPDATE transfer_jobs SET status='done',stage='not_due',external_provider_status='post_processing_skipped',finished_at=CURRENT_TIMESTAMP WHERE id=?",
                        (job_id,),
                    )
                    return {"ok": True, "confirmed": True, "stage": "not_due", "provider": "quark", "job_id": job_id, "episode_numbers": []}
            return self._native_result(task_id, job_id=job_id)

        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=native_result),
            patch(
                "app.services.tracking_engine_v2.sync_tracking_fallback_to_p115",
                return_value={"ok": False, "message": "源网盘未找到 1 集", "job_id": 0, "copied": [], "skipped": [], "missing": [17], "files": []},
            ),
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        with db() as conn:
            batch = conn.execute("SELECT status,finished_at FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()
            notifications = int(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
        self.assertEqual("partial", batch["status"])
        self.assertTrue(batch["finished_at"])
        self.assertEqual(0, notifications)

    def test_partial_quark_result_only_copies_available_episodes_and_keeps_retry(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")

        def native_result(task_id, *, job_id=None, **_kwargs):
            result = self._native_result(task_id, job_id=job_id)
            if result["provider"] == "quark":
                result.update({"episode_numbers": [17, 18], "matched_episode_count": 1, "unmatched_episode_count": 1})
            else:
                result["episode_numbers"] = [17, 18]
                with db() as conn:
                    conn.execute(
                        "UPDATE transfer_jobs SET rename_pairs_json=? WHERE id=?",
                        (json.dumps([{"_tracking_cycle": {"requested": [17, 18]}}]), job_id),
                    )
            return result

        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=native_result),
            patch(
                "app.services.tracking_engine_v2.sync_tracking_fallback_to_p115",
                return_value={"ok": True, "message": "已提交 1 集，源网盘未找到 1 集", "job_id": 0, "copied": [17], "skipped": [], "missing": [18], "files": [{"episode_number": 17, "file_name": "Cycle.Show.S01E17.mkv"}]},
            ),
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        from app.api.transfers import _refresh_batch_status

        _refresh_batch_status(int(cycle["batch_id"]))
        self._confirm_p115_fallback()
        with db() as conn:
            batch = conn.execute("SELECT status,message FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()
            states = {
                int(row["episode_number"]): str(row["status"])
                for row in conn.execute(
                    "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
                    (self.p115_id,),
                ).fetchall()
            }
        self.assertEqual("partial", batch["status"])
        self.assertEqual("saved", states[17])
        self.assertEqual("retry_wait", states[18])

    def test_complete_fallback_does_not_hide_other_unmatched_quark_episodes(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")

        def native_result(task_id, *, job_id=None, **_kwargs):
            result = self._native_result(task_id, job_id=job_id)
            if result["provider"] == "quark":
                result.update({"episode_numbers": [17, 18], "matched_episode_count": 1, "unmatched_episode_count": 1})
                with db() as conn:
                    conn.execute(
                        "UPDATE transfer_jobs SET rename_pairs_json=? WHERE id=?",
                        (
                            json.dumps([
                                {"replacement": "Cycle.Show.S01E17.mkv", "episode_numbers": [17]},
                                {"_tracking_cycle": {"requested": [17, 18]}},
                            ]),
                            job_id,
                        ),
                    )
            return result

        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=native_result),
            patch(
                "app.services.tracking_engine_v2.sync_tracking_fallback_to_p115",
                return_value={"ok": True, "message": "已提交 1 集", "job_id": 0, "copied": [17], "skipped": [], "missing": [], "files": [{"episode_number": 17, "file_name": "Cycle.Show.S01E17.mkv"}]},
            ),
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        self._confirm_p115_fallback()

        with db() as conn:
            batch = conn.execute("SELECT status,message FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()
        self.assertEqual("partial", batch["status"])
        self.assertIn("夸克", batch["message"])

    def test_single_provider_cycle_finishes_as_done(self):
        with db() as conn:
            conn.execute("UPDATE tracking_tasks SET status='paused' WHERE id=?", (self.p115_id,))
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_manual")

        def quark_only(_task_id, *, job_id=None, **_kwargs):
            with db() as conn:
                conn.execute(
                    "UPDATE transfer_jobs SET status='done',stage='not_due',external_provider_status='post_processing_skipped',finished_at=CURRENT_TIMESTAMP WHERE id=?",
                    (job_id,),
                )
            return {"ok": True, "stage": "not_due", "provider": "quark", "job_id": job_id, "episode_numbers": []}

        with patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=quark_only):
            run_tracking_cycle(int(cycle["batch_id"]))

        with db() as conn:
            batch = conn.execute("SELECT status,message FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()
            notification_count = int(conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE source_key=?",
                (f"tracking-cycle:{cycle['batch_id']}:terminal",),
            ).fetchone()[0])
        self.assertEqual("done", batch["status"])
        self.assertIn("夸克", batch["message"])
        self.assertEqual(0, notification_count)

    def test_legacy_qas_confirmation_resumes_fallback_and_notifies_only_after_p115_confirmation(self):
        with db() as conn:
            conn.execute("UPDATE tracking_tasks SET provider='qas' WHERE id=?", (self.quark_id,))
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")

        def native_result(task_id, *, job_id=None, **_kwargs):
            with db() as conn:
                provider = conn.execute("SELECT provider FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()[0]
                if provider == "qas":
                    conn.execute(
                        """
                        UPDATE transfer_jobs SET status='triggered',stage='provider_triggered',rename_pairs_json=?,
                            save_path='/strm/tv/Cycle Show/Season 1'
                        WHERE id=?
                        """,
                        (json.dumps([
                            {"replacement": "Cycle.Show.S01E17.mkv", "episode_numbers": [17]},
                            {"_tracking_cycle": {"requested": [17]}},
                        ]), job_id),
                    )
                    return {
                        "ok": True,
                        "confirmed": False,
                        "stage": "provider_triggered",
                        "provider": "qas",
                        "job_id": job_id,
                        "episode_numbers": [17],
                        "matched_episode_count": 1,
                        "unmatched_episode_count": 0,
                    }
                conn.execute(
                    "UPDATE transfer_jobs SET status='retry_wait',stage='no_resource',rename_pairs_json=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                    (json.dumps([{"_tracking_cycle": {"requested": [17]}}]), job_id),
                )
                return {
                    "ok": False,
                    "stage": "retry_wait",
                    "resolution_stage": "no_resource",
                    "provider": "p115",
                    "job_id": job_id,
                    "episode_numbers": [17],
                }

        with patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=native_result):
            run_tracking_cycle(int(cycle["batch_id"]))
        with db() as conn:
            self.assertEqual("running", conn.execute("SELECT status FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()[0])
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])

        class ConfirmedQas:
            def reconcile(self, _path, expected, *, expected_count=0):
                return expected == ["Cycle.Show.S01E17.mkv"] and expected_count == 0

        fallback_result = {
            "ok": True,
            "message": "已提交 1 集",
            "job_id": 0,
            "copied": [17],
            "skipped": [],
            "missing": [],
            "files": [{"episode_number": 17, "file_name": "Cycle.Show.S01E17.mkv"}],
        }
        with (
            patch("app.services.qas_reconciler.get_transfer_provider", return_value=ConfirmedQas()),
            patch("app.services.tracking_engine_v2.sync_tracking_fallback_to_p115", return_value=fallback_result) as fallback,
        ):
            reconcile_triggered_jobs()
        fallback.assert_called_once_with(target_task_id=self.p115_id, episode_numbers=[17])
        with db() as conn:
            self.assertEqual("running", conn.execute("SELECT status FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()[0])
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])

        self._confirm_p115_fallback()
        with db() as conn:
            self.assertEqual("done", conn.execute("SELECT status FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])

    def test_qas_confirmation_waits_for_slow_p115_and_finalizes_from_durable_state(self):
        with db() as conn:
            conn.execute("UPDATE tracking_tasks SET provider='qas' WHERE id=?", (self.quark_id,))
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")
        p115_started = threading.Event()
        qas_confirmed = threading.Event()

        def racing_native(task_id, *, job_id=None, **_kwargs):
            with db() as conn:
                provider = conn.execute("SELECT provider FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()[0]
            if provider == "p115":
                p115_started.set()
                self.assertTrue(qas_confirmed.wait(timeout=2))
                with db() as conn:
                    conn.execute(
                        "UPDATE transfer_jobs SET status='retry_wait',stage='no_resource',rename_pairs_json=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                        (json.dumps([{"_tracking_cycle": {"requested": [17]}}]), job_id),
                    )
                return {
                    "ok": False,
                    "stage": "retry_wait",
                    "resolution_stage": "no_resource",
                    "provider": "p115",
                    "job_id": job_id,
                    "episode_numbers": [17],
                }

            self.assertTrue(p115_started.wait(timeout=2))
            with db() as conn:
                conn.execute(
                    """
                    UPDATE transfer_jobs SET status='done',stage='provider_completed',rename_pairs_json=?,
                        external_provider_status='post_processing_skipped',
                        finished_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (json.dumps([
                        {"replacement": "Cycle.Show.S01E17.mkv", "episode_numbers": [17]},
                        {"_tracking_cycle": {"requested": [17]}},
                    ]), job_id),
                )
            # Simulate the background QAS reconciler advancing the batch before
            # this future returns its now-stale confirmed=False result.
            resume_tracking_cycle(int(cycle["batch_id"]))
            qas_confirmed.set()
            return {
                "ok": True,
                "confirmed": False,
                "stage": "provider_triggered",
                "provider": "qas",
                "job_id": job_id,
                "episode_numbers": [17],
                "matched_episode_count": 1,
                "unmatched_episode_count": 0,
            }

        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=racing_native),
            patch(
                "app.services.tracking_engine_v2.sync_tracking_fallback_to_p115",
                return_value={"ok": False, "message": "源网盘未找到 1 集", "job_id": 0, "copied": [], "skipped": [], "missing": [17], "files": []},
            ) as fallback,
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        fallback.assert_called_once_with(target_task_id=self.p115_id, episode_numbers=[17])
        with db() as conn:
            batch = conn.execute("SELECT status,finished_at FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()
            notifications = int(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
        self.assertEqual("partial", batch["status"])
        self.assertTrue(batch["finished_at"])
        self.assertEqual(1, notifications)

    def test_post_processing_failure_waits_for_durable_retry_before_notification(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")
        fallback_result = {
            "ok": True,
            "message": "已提交 1 集",
            "job_id": 0,
            "copied": [17],
            "skipped": [],
            "missing": [],
            "files": [{"episode_number": 17, "file_name": "Cycle.Show.S01E17.mkv"}],
        }
        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=self._native_result),
            patch("app.services.tracking_engine_v2.sync_tracking_fallback_to_p115", return_value=fallback_result),
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        class ConfirmedP115:
            def reconcile(self, _path, expected):
                return bool(expected)

        with (
            patch("app.services.qas_reconciler.get_transfer_provider", return_value=ConfirmedP115()),
            patch("app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing", return_value=False),
        ):
            reconcile_triggered_jobs()
        with db() as conn:
            batch = conn.execute("SELECT status,message FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()
            notifications = int(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
        self.assertEqual("running", batch["status"])
        self.assertEqual(0, notifications)

        with patch(
            "app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing",
            return_value=False,
        ):
            self.assertEqual(1, retry_failed_post_processing())
        with db() as conn:
            batch = conn.execute("SELECT status,message FROM transfer_batches WHERE id=?", (cycle["batch_id"],)).fetchone()
            notifications = int(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
        self.assertEqual("partial", batch["status"])
        self.assertIn("STRM/Emby", batch["message"])
        self.assertEqual(1, notifications)

    def test_failed_tracking_post_processing_retries_exact_outputs_without_provider_transfer(self):
        with db() as conn:
            conn.execute("UPDATE tracking_tasks SET status='paused' WHERE id=?", (self.quark_id,))
        cycle = prepare_tracking_cycle(self.p115_id, request_source="tracking_scheduler")
        exact_outputs = ({"file_id": "p115-17", "file_name": "Cycle.Show.S01E17.mkv"},)
        with db() as conn:
            job_id = int(conn.execute(
                "SELECT job_id FROM transfer_batch_jobs WHERE batch_id=?",
                (int(cycle["batch_id"]),),
            ).fetchone()[0])
            conn.execute(
                """
                UPDATE transfer_jobs SET status='done',stage='provider_completed',
                    external_provider_status='post_processing_pending',rename_pairs_json=?,
                    save_path='/媒体库/tv/Cycle Show/Season 1',finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    json.dumps([
                        {"replacement": "Cycle.Show.S01E17.mkv", "episode_numbers": [17]},
                        {"_tracking_cycle": {"requested": [17]}},
                    ]),
                    job_id,
                ),
            )

        enabled_settings = type("Settings", (), {"p115_strm_enabled": True})()
        with (
            patch("app.services.tracking_engine_v2.get_settings", return_value=enabled_settings),
            patch(
                "app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing",
                side_effect=(False, True),
            ) as post_process,
            patch("app.services.tracking_engine_v2.run_tracking_task") as provider_transfer,
        ):
            self.assertFalse(run_pending_tracking_post_processing(job_id, outputs=exact_outputs))
            resume_tracking_cycle(int(cycle["batch_id"]))
            with db() as conn:
                waiting = conn.execute(
                    "SELECT status,finished_at FROM transfer_batches WHERE id=?",
                    (int(cycle["batch_id"]),),
                ).fetchone()
                waiting_notifications = int(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
            self.assertEqual("running", waiting["status"])
            self.assertIsNone(waiting["finished_at"])
            self.assertEqual(0, waiting_notifications)

            self.assertEqual(1, retry_failed_post_processing())
            self.assertEqual(0, retry_failed_post_processing())

        provider_transfer.assert_not_called()
        self.assertEqual(2, post_process.call_count)
        self.assertEqual(exact_outputs, post_process.call_args_list[1].kwargs["outputs"])
        with db() as conn:
            job = conn.execute(
                "SELECT external_provider_status,rename_pairs_json FROM transfer_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            batch = conn.execute(
                "SELECT status,finished_at FROM transfer_batches WHERE id=?",
                (int(cycle["batch_id"]),),
            ).fetchone()
            notifications = int(conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE source_key=?",
                (f"tracking-cycle:{cycle['batch_id']}:terminal",),
            ).fetchone()[0])
        metadata = next(
            item["_post_processing"]
            for item in json.loads(job["rename_pairs_json"])
            if "_post_processing" in item
        )
        self.assertEqual("post_processing_completed", job["external_provider_status"])
        self.assertEqual(list(exact_outputs), metadata["outputs"])
        self.assertEqual(2, metadata["attempts"])
        self.assertEqual("done", batch["status"])
        self.assertTrue(batch["finished_at"])
        self.assertEqual(1, notifications)

    def test_confirmed_organized_backfill_syncs_new_quark_files_to_115(self):
        exact_outputs = ({"file_id": "quark-18", "file_name": "Cycle.Show.S01E18.mkv"},)
        with db() as conn:
            job_id = int(conn.execute(
                """INSERT INTO transfer_jobs(
                       task_id,tmdb_id,media_type,display_title,season_number,target,provider,status,stage,
                       save_path,request_source,external_provider_status,rename_pairs_json
                   ) VALUES(?,100,'tv','Cycle Show',1,'cloud','quark','done','provider_completed',
                       '/strm/tv/Cycle Show/Season 1','organized_backfill','post_processing_pending',?)""",
                (self.quark_id, json.dumps([{"_post_processing": {"outputs": list(exact_outputs)}}])),
            ).lastrowid)
        completion = P115CompletionResult(True, True, True, (), (), "115 已同步新补集", "done")
        with (
            patch("app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing", return_value=True),
            patch("app.services.p115_completion.complete_quark_to_p115", return_value=completion) as sync_p115,
        ):
            self.assertTrue(run_pending_tracking_post_processing(job_id, outputs=exact_outputs))

        sync_p115.assert_called_once()
        self.assertEqual(("Cycle.Show.S01E18.mkv",), sync_p115.call_args.kwargs["filenames"])
        self.assertEqual("/strm/tv/Cycle Show/Season 1", sync_p115.call_args.kwargs["save_path"])

    def test_running_post_processing_is_not_success_and_restart_requeues_it(self):
        with db() as conn:
            conn.execute("UPDATE tracking_tasks SET status='paused' WHERE id=?", (self.quark_id,))
        cycle = prepare_tracking_cycle(self.p115_id, request_source="tracking_scheduler")
        with db() as conn:
            job_id = int(conn.execute(
                "SELECT job_id FROM transfer_batch_jobs WHERE batch_id=?",
                (int(cycle["batch_id"]),),
            ).fetchone()[0])
            conn.execute(
                """
                UPDATE transfer_jobs SET status='done',stage='provider_completed',
                    external_provider_status='post_processing_running',
                    rename_pairs_json=?,save_path='/媒体库/tv/Cycle Show/Season 1',
                    finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    json.dumps([
                        {"replacement": "Cycle.Show.S01E17.mkv", "episode_numbers": [17]},
                        {"_tracking_cycle": {"requested": [17]}},
                    ]),
                    job_id,
                ),
            )

        before_restart = resume_tracking_cycle(int(cycle["batch_id"]))
        self.assertIsNone(before_restart[0]["post_processing_ok"])
        with db() as conn:
            batch = conn.execute(
                "SELECT status,finished_at FROM transfer_batches WHERE id=?",
                (int(cycle["batch_id"]),),
            ).fetchone()
            notifications = int(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
        self.assertEqual("running", batch["status"])
        self.assertIsNone(batch["finished_at"])
        self.assertEqual(0, notifications)

        enabled_settings = type("Settings", (), {"p115_strm_enabled": True})()
        with (
            patch("app.services.tracking_engine_v2.get_settings", return_value=enabled_settings),
            patch(
                "app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing",
                return_value=True,
            ) as post_process,
        ):
            self.assertEqual(0, recover_interrupted_jobs())

        post_process.assert_called_once()
        with db() as conn:
            job = conn.execute(
                "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            batch = conn.execute(
                "SELECT status,finished_at FROM transfer_batches WHERE id=?",
                (int(cycle["batch_id"]),),
            ).fetchone()
            notifications = int(conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE source_key=?",
                (f"tracking-cycle:{cycle['batch_id']}:terminal",),
            ).fetchone()[0])
        self.assertEqual("post_processing_completed", job["external_provider_status"])
        self.assertEqual("done", batch["status"])
        self.assertTrue(batch["finished_at"])
        self.assertEqual(1, notifications)

    def test_openlist_confirmation_timeout_starts_at_copy_submission(self):
        now = datetime.now(timezone.utc)
        submitted_at = now - timedelta(minutes=1)
        job = {
            "created_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
            "rename_pairs_json": json.dumps([
                {
                    "_tracking_openlist_fallback": {
                        "requested": [17],
                        "submitted": [17],
                        "missing": [],
                        "submitted_at": submitted_at.isoformat(timespec="seconds"),
                    }
                }
            ]),
        }
        settings = type("Settings", (), {"qas_confirmation_timeout_minutes": 5})()
        with patch("app.services.qas_reconciler.get_settings", return_value=settings):
            self.assertFalse(_confirmation_expired(job, now=now))
            self.assertTrue(_confirmation_expired(job, now=submitted_at + timedelta(minutes=5)))

    def test_restart_closes_interrupted_tracking_cycle(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")
        self.assertEqual(2, recover_interrupted_jobs())
        with db() as conn:
            batch = conn.execute(
                "SELECT status,finished_at FROM transfer_batches WHERE id=?",
                (cycle["batch_id"],),
            ).fetchone()
            notifications = int(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
        self.assertEqual("failed", batch["status"])
        self.assertTrue(batch["finished_at"])
        self.assertEqual(0, notifications)

    def test_concurrent_prepare_reuses_one_active_cycle(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(prepare_tracking_cycle, self.quark_id, request_source="tracking_manual")
                for _ in range(2)
            ]
            cycles = [future.result() for future in futures]

        self.assertEqual(1, sum(not bool(item.get("duplicate")) for item in cycles))
        self.assertEqual(1, sum(bool(item.get("duplicate")) for item in cycles))
        self.assertEqual(1, len({int(item["batch_id"]) for item in cycles}))
        with db() as conn:
            batch_count = int(conn.execute("SELECT COUNT(*) FROM transfer_batches").fetchone()[0])
        self.assertEqual(1, batch_count)

    def test_first_transfer_batch_blocks_cycle_without_being_resumed_as_tracking(self):
        with db() as conn:
            batch_id = int(conn.execute(
                "INSERT INTO transfer_batches(tmdb_id,media_type,display_title,status) VALUES(100,'tv','Cycle Show','running')"
            ).lastrowid)
            job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    task_id,tmdb_id,media_type,provider,target,status,stage,execution_key,batch_id
                ) VALUES(?,100,'tv','quark','cloud','running','provider_submitting','transfer:first-run',?)
                """,
                (self.quark_id, batch_id),
            ).lastrowid)
            conn.execute("INSERT INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)", (batch_id, job_id))

        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")
        self.assertTrue(cycle["duplicate"])
        self.assertTrue(cycle["blocked"])
        self.assertEqual(batch_id, cycle["batch_id"])
        self.assertEqual([], resume_tracking_cycle(batch_id))
        with db() as conn:
            batch = conn.execute("SELECT status,finished_at FROM transfer_batches WHERE id=?", (batch_id,)).fetchone()
        self.assertEqual("running", batch["status"])
        self.assertIsNone(batch["finished_at"])

        self.assertEqual(1, recover_interrupted_jobs())
        resumed = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")
        self.assertFalse(resumed["duplicate"])
        self.assertNotEqual(batch_id, resumed["batch_id"])
        with db() as conn:
            recovered = conn.execute("SELECT status,finished_at FROM transfer_batches WHERE id=?", (batch_id,)).fetchone()
        self.assertEqual("failed", recovered["status"])
        self.assertTrue(recovered["finished_at"])

    def test_scheduler_without_fallback_skips_linked_first_transfer_batch(self):
        with db() as conn:
            conn.execute(
                "UPDATE tracking_tasks SET openlist_fallback_to_p115=0,next_check_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                (self.quark_id,),
            )
            conn.execute("UPDATE tracking_tasks SET status='paused' WHERE id=?", (self.p115_id,))
            batch_id = int(conn.execute(
                "INSERT INTO transfer_batches(tmdb_id,media_type,display_title,status) VALUES(100,'tv','Cycle Show','running')"
            ).lastrowid)
            job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    task_id,tmdb_id,media_type,provider,target,status,stage,execution_key,batch_id
                ) VALUES(?,100,'tv','quark','cloud','triggered','provider_triggered','transfer:first-run',?)
                """,
                (self.quark_id, batch_id),
            ).lastrowid)
            conn.execute("INSERT INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)", (batch_id, job_id))

        with (
            patch("app.services.tracking_engine_v2.refresh_tracking_metadata", return_value=[]),
            patch("app.services.tracking_engine_v2.run_tracking_task") as run_task,
        ):
            result = run_due_tracking_tasks()

        self.assertEqual([], result)
        run_task.assert_not_called()
        with db() as conn:
            self.assertEqual("running", conn.execute("SELECT status FROM transfer_batches WHERE id=?", (batch_id,)).fetchone()[0])

    def test_native_p115_partial_fallback_only_requests_confirmed_gap(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")

        def native_result(task_id, *, job_id=None, **_kwargs):
            with db() as conn:
                provider = conn.execute(
                    "SELECT provider FROM tracking_tasks WHERE id=?",
                    (task_id,),
                ).fetchone()[0]
            if provider != "p115":
                return self._native_result(task_id, job_id=job_id)
            with db() as conn:
                conn.execute(
                    """
                    UPDATE transfer_jobs SET status='done',stage='provider_partial',
                        external_provider_status='post_processing_completed',rename_pairs_json=?,
                        finished_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        json.dumps([
                            {"replacement": "Cycle.Show.S01E17.mkv", "episode_numbers": [17]},
                            {"_tracking_cycle": {"requested": [17, 18]}},
                        ]),
                        job_id,
                    ),
                )
            return {
                "ok": True,
                "confirmed": True,
                "stage": "provider_partial",
                "provider": "p115",
                "job_id": job_id,
                "episode_numbers": [17, 18],
                "matched_episode_count": 1,
                "unmatched_episode_count": 1,
                "post_processing_ok": True,
            }

        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=native_result),
            patch(
                "app.services.tracking_engine_v2.sync_tracking_fallback_to_p115",
                return_value={
                    "ok": False,
                    "message": "夸克目录暂未发现 E18",
                    "job_id": 0,
                    "copied": [],
                    "skipped": [],
                    "missing": [18],
                    "files": [],
                },
            ) as fallback,
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        fallback.assert_called_once_with(target_task_id=self.p115_id, episode_numbers=[18])
        with db() as conn:
            batch = conn.execute(
                "SELECT status FROM transfer_batches WHERE id=?",
                (int(cycle["batch_id"]),),
            ).fetchone()
        self.assertEqual("partial", batch["status"])

    def test_p115_source_not_updated_is_fallback_eligible(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")

        def native_result(task_id, *, job_id=None, **_kwargs):
            with db() as conn:
                provider = conn.execute(
                    "SELECT provider FROM tracking_tasks WHERE id=?",
                    (task_id,),
                ).fetchone()[0]
            if provider != "p115":
                return self._native_result(task_id, job_id=job_id)
            with db() as conn:
                conn.execute(
                    """
                    UPDATE transfer_jobs SET status='retry_wait',stage='source_not_updated',
                        rename_pairs_json=?,finished_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (json.dumps([{"_tracking_cycle": {"requested": [17]}}]), job_id),
                )
            return {
                "ok": False,
                "stage": "retry_wait",
                "resolution_stage": "source_not_updated",
                "provider": "p115",
                "job_id": job_id,
                "episode_numbers": [17],
            }

        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=native_result),
            patch(
                "app.services.tracking_engine_v2.sync_tracking_fallback_to_p115",
                return_value={
                    "ok": False,
                    "message": "夸克目录暂未发现 E17",
                    "job_id": 0,
                    "copied": [],
                    "skipped": [],
                    "missing": [17],
                    "files": [],
                },
            ) as fallback,
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        fallback.assert_called_once_with(target_task_id=self.p115_id, episode_numbers=[17])

    def test_cycle_does_not_fallback_on_a_p115_error_that_is_not_no_resource(self):
        cycle = prepare_tracking_cycle(self.quark_id, request_source="tracking_scheduler")

        def provider_error(task_id, *, job_id=None, **kwargs):
            result = self._native_result(task_id, job_id=job_id, **kwargs)
            if result["provider"] == "p115":
                with db() as conn:
                    conn.execute("UPDATE transfer_jobs SET stage='storage_check_failed' WHERE id=?", (job_id,))
                result["resolution_stage"] = "storage_check_failed"
            return result

        with (
            patch("app.services.tracking_engine_v2.run_tracking_task", side_effect=provider_error),
            patch("app.services.tracking_engine_v2.sync_tracking_fallback_to_p115") as fallback,
        ):
            run_tracking_cycle(int(cycle["batch_id"]))

        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
