import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.qas_reconciler import reconcile_triggered_jobs, recover_interrupted_jobs


class EmptyDirectoryQas:
    def savepath_detail(self, path):
        return {"success": True, "data": {"list": []}}

    def task_data(self):
        return {"push_config": {}}


class ConfirmedDirectoryQas:
    def savepath_detail(self, path):
        return {
            "success": True,
            "data": {"list": [{"name": "测试剧 2026 S01E01.mkv", "size": 1}]},
        }

    def task_data(self):
        return {"push_config": {}}


class QasReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "QAS_CONFIRMATION_TIMEOUT_MINUTES": "30",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_expired_triggered_job_returns_tracking_to_retry(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,save_path,decision_state)
                VALUES(1,'tv','测试剧',1,'/strm/tv/测试剧','awaiting_confirmation')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,rename_to)
                VALUES(?,1,1,'triggered','测试剧.2026.S01E01.mkv')
                """,
                (task_id,),
            )
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(task_id,tmdb_id,media_type,target,status,stage,save_path,
                                          rename_pairs_json,created_at)
                VALUES(?,1,'tv','cloud','triggered','qas_triggered','/strm/tv/测试剧',?,?)
                """,
                (task_id, '[{"replacement":"测试剧.2026.S01E01.mkv"}]', old),
            ).lastrowid

        result = reconcile_triggered_jobs(qas=EmptyDirectoryQas())
        self.assertEqual([{"job_id": job_id, "confirmed": False, "expired": True}], result)
        with db() as conn:
            job = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
            task = conn.execute("SELECT decision_state,next_check_at FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
            episode = conn.execute("SELECT status FROM tracking_episodes WHERE task_id=?", (task_id,)).fetchone()
        self.assertEqual(("failed", "provider_confirmation_timeout"), tuple(job))
        self.assertEqual("retry_wait", task["decision_state"])
        self.assertTrue(task["next_check_at"])
        self.assertEqual("retry_wait", episode["status"])

    def test_repeated_confirmation_timeout_enters_review(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,save_path,decision_state,retry_count)
                VALUES(2,'tv','测试剧',1,'/strm/tv/测试剧','awaiting_confirmation',4)
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,rename_to)
                VALUES(?,1,1,'triggered','测试剧.2026.S01E01.mkv')
                """,
                (task_id,),
            )
            conn.execute(
                """
                INSERT INTO transfer_jobs(task_id,tmdb_id,media_type,target,status,stage,save_path,
                                          rename_pairs_json,created_at)
                VALUES(?,2,'tv','cloud','triggered','qas_triggered','/strm/tv/测试剧',?,?)
                """,
                (task_id, '[{"replacement":"测试剧.2026.S01E01.mkv"}]', old),
            )
        reconcile_triggered_jobs(qas=EmptyDirectoryQas())
        with db() as conn:
            task = conn.execute("SELECT decision_state,next_check_at,retry_count FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        self.assertEqual("needs_review", task["decision_state"])
        self.assertEqual("", task["next_check_at"])
        self.assertEqual(5, task["retry_count"])

    def test_startup_recovery_never_leaves_manual_job_running(self):
        with db() as conn:
            job_id = conn.execute(
                "INSERT INTO transfer_jobs(tmdb_id,media_type,target,status,stage) VALUES(3,'movie','cloud','running','searching_sources')"
            ).lastrowid
        self.assertEqual(1, recover_interrupted_jobs())
        with db() as conn:
            job = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(("failed", "interrupted"), tuple(job))

    def test_restart_resumes_generic_partial_post_processing_with_exact_outputs(self):
        with db() as conn:
            batch_id = int(conn.execute(
                """
                INSERT INTO transfer_batches(tmdb_id,media_type,display_title,status)
                VALUES(31,'tv','部分成功剧','running')
                """
            ).lastrowid)
            completed_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    tmdb_id,media_type,display_title,target,provider,status,stage,batch_id
                ) VALUES(31,'tv','部分成功剧','cloud','quark','done','provider_completed',?)
                """,
                (batch_id,),
            ).lastrowid)
            job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    tmdb_id,media_type,display_title,target,provider,status,stage,message,
                    save_path,rename_pairs_json,external_provider_status,batch_id,execution_key
                ) VALUES(
                    31,'tv','部分成功剧','cloud','p115','running','provider_partial','E02 转存失败',
                    '/媒体库/tv/部分成功剧/Season 1',?,'post_processing_running',?,'generic-partial'
                )
                """,
                (
                    json.dumps(
                        [
                            {"replacement": "Partial.Show.S01E01.mkv"},
                            {"replacement": "Partial.Show.S01E02.mkv"},
                            {
                                "_post_processing": {
                                    "outputs": [
                                        {
                                            "file_id": "confirmed-1",
                                            "file_name": "Partial.Show.S01E01.mkv",
                                        }
                                    ],
                                    "terminal_status": "failed",
                                }
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    batch_id,
                ),
            ).lastrowid)
            conn.executemany(
                "INSERT INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)",
                [(batch_id, completed_id), (batch_id, job_id)],
            )
            conn.executemany(
                """
                INSERT INTO media_workflow_steps(job_id,step_key,status,message)
                VALUES(?,?,'pending','等待继续')
                """,
                [
                    (job_id, step_key)
                    for step_key in (
                        "resource_search",
                        "tmdb_rename",
                        "transfer",
                        "openlist_sync",
                        "strm_generate",
                        "emby_refresh",
                        "library_notification",
                    )
                ],
            )

        enabled_settings = type("Settings", (), {"p115_strm_enabled": True})()
        with (
            patch("app.services.tracking_engine_v2.get_settings", return_value=enabled_settings),
            patch(
                "app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing",
                return_value=True,
            ) as post_process,
        ):
            self.assertEqual(1, recover_interrupted_jobs())

        post_process.assert_called_once()
        self.assertEqual(
            ({"file_id": "confirmed-1", "file_name": "Partial.Show.S01E01.mkv"},),
            post_process.call_args.kwargs["outputs"],
        )
        with db() as conn:
            job = conn.execute(
                "SELECT status,stage,external_provider_status FROM transfer_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            batch = conn.execute(
                "SELECT status,finished_at FROM transfer_batches WHERE id=?",
                (batch_id,),
            ).fetchone()
            notifications = int(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
            spinners = int(conn.execute(
                """
                SELECT COUNT(*) FROM media_workflow_steps
                WHERE job_id=? AND status IN ('pending','running')
                """,
                (job_id,),
            ).fetchone()[0])
        self.assertEqual(("failed", "provider_partial", "post_processing_completed"), tuple(job))
        self.assertEqual("partial", batch["status"])
        self.assertTrue(batch["finished_at"])
        self.assertEqual(1, notifications)
        self.assertEqual(0, spinners)

    def test_restart_finalizes_generic_job_after_post_processing_completed(self):
        with db() as conn:
            batch_id = int(conn.execute(
                """
                INSERT INTO transfer_batches(tmdb_id,media_type,display_title,status)
                VALUES(32,'tv','已完成后处理剧','running')
                """
            ).lastrowid)
            job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    tmdb_id,media_type,display_title,target,provider,status,stage,save_path,
                    rename_pairs_json,external_provider_status,batch_id,execution_key
                ) VALUES(
                    32,'tv','已完成后处理剧','cloud','quark','running','provider_completed',
                    '/媒体库/tv/已完成后处理剧/Season 1',?,'post_processing_completed',?,'generic-completed'
                )
                """,
                (
                    json.dumps(
                        [
                            {
                                "_post_processing": {
                                    "outputs": [{"file_name": "Completed.Show.S01E01.mkv"}],
                                    "terminal_status": "done",
                                }
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    batch_id,
                ),
            ).lastrowid)
            conn.execute(
                "INSERT INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)",
                (batch_id, job_id),
            )

        with patch(
            "app.services.tracking_engine_v2.run_pending_tracking_post_processing"
        ) as post_process:
            self.assertEqual(1, recover_interrupted_jobs())

        post_process.assert_not_called()
        with db() as conn:
            job = conn.execute(
                "SELECT status,stage,external_provider_status FROM transfer_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            batch = conn.execute(
                "SELECT status,finished_at FROM transfer_batches WHERE id=?",
                (batch_id,),
            ).fetchone()
        self.assertEqual(("done", "provider_completed", "post_processing_completed"), tuple(job))
        self.assertEqual("done", batch["status"])
        self.assertTrue(batch["finished_at"])

    def test_restart_deduplicates_post_processing_and_refreshes_every_parent(self):
        with db() as conn:
            parent_ids = [
                int(conn.execute(
                    """
                    INSERT INTO transfer_batches(tmdb_id,media_type,display_title,status)
                    VALUES(33,'tv','重用任务','running')
                    """
                ).lastrowid)
                for _ in range(2)
            ]
            job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    tmdb_id,media_type,display_title,target,provider,status,stage,save_path,
                    rename_pairs_json,external_provider_status,batch_id,execution_key
                ) VALUES(
                    33,'tv','重用任务','cloud','p115','running','provider_completed',
                    '/媒体库/tv/重用任务/Season 1',?,'post_processing_running',?,'generic-reused'
                )
                """,
                (
                    json.dumps([
                        {
                            "_post_processing": {
                                "outputs": [{"file_name": "Reused.Show.S01E01.mkv"}],
                                "terminal_status": "done",
                            }
                        }
                    ]),
                    parent_ids[0],
                ),
            ).lastrowid)
            conn.executemany(
                "INSERT INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)",
                [(batch_id, job_id) for batch_id in parent_ids],
            )

        enabled_settings = type("Settings", (), {"p115_strm_enabled": True})()
        with (
            patch("app.services.tracking_engine_v2.get_settings", return_value=enabled_settings),
            patch(
                "app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing",
                return_value=True,
            ) as post_process,
        ):
            self.assertEqual(1, recover_interrupted_jobs())

        post_process.assert_called_once()
        with db() as conn:
            statuses = [
                str(conn.execute(
                    "SELECT status FROM transfer_batches WHERE id=?",
                    (batch_id,),
                ).fetchone()[0])
                for batch_id in parent_ids
            ]
        self.assertEqual(["done", "done"], statuses)

    def test_restart_invalid_exact_output_metadata_fails_closed(self):
        with db() as conn:
            job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    tmdb_id,media_type,display_title,target,provider,status,stage,save_path,
                    rename_pairs_json,external_provider_status,execution_key
                ) VALUES(
                    34,'tv','无效后处理元数据','cloud','p115','running','provider_completed',
                    '/媒体库/tv/无效后处理元数据/Season 1',?,'post_processing_pending','generic-invalid'
                )
                """,
                (
                    json.dumps([
                        {"replacement": "Must.Not.Be.Used.S01E01.mkv"},
                        {
                            "_post_processing": {
                                "outputs": "invalid",
                                "terminal_status": "done",
                            }
                        },
                    ]),
                ),
            ).lastrowid)

        enabled_settings = type("Settings", (), {"p115_strm_enabled": True})()

        def reject_empty_outputs(*_args, **kwargs):
            self.assertEqual((), kwargs["outputs"])
            return False

        with (
            patch("app.services.tracking_engine_v2.get_settings", return_value=enabled_settings),
            patch(
                "app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing",
                side_effect=reject_empty_outputs,
            ) as post_process,
        ):
            self.assertEqual(1, recover_interrupted_jobs())

        post_process.assert_called_once()
        with db() as conn:
            job = conn.execute(
                "SELECT status,stage,external_provider_status FROM transfer_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        self.assertEqual(("failed", "post_processing_failed", "post_processing_failed"), tuple(job))

    def test_generic_linked_qas_confirmation_refreshes_exact_tracking_episode(self):
        with db() as conn:
            task_id = int(conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,season_number,provider,save_path,decision_state
                ) VALUES(30,'tv','测试剧',1,'qas','/strm/tv/测试剧','pending')
                """
            ).lastrowid)
            conn.executemany(
                """
                INSERT INTO tracking_episodes(
                    task_id,season_number,episode_number,status,provider
                ) VALUES(?,1,?,'pending','qas')
                """,
                [(task_id, 1), (task_id, 2)],
            )
            job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    task_id,tmdb_id,media_type,target,provider,status,stage,save_path,
                    rename_pairs_json,created_at,execution_key
                ) VALUES(?,30,'tv','cloud','qas','triggered','qas_triggered','/strm/tv/测试剧',
                         ?,CURRENT_TIMESTAMP,'generic-linked-qas')
                """,
                (task_id, '[{"replacement":"测试剧 2026 S01E01.mkv"}]'),
            ).lastrowid)

        result = reconcile_triggered_jobs(qas=ConfirmedDirectoryQas())

        self.assertEqual([{"job_id": job_id, "confirmed": True}], result)
        with db() as conn:
            states = {
                int(row["episode_number"]): str(row["status"])
                for row in conn.execute(
                    "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
                    (task_id,),
                ).fetchall()
            }
        self.assertEqual({1: "saved", 2: "pending"}, states)

    @patch.dict(os.environ, {"NOTIFICATION_EXTERNAL_ENABLED": "true"})
    @patch("app.services.qas_reconciler.sync_transfer_notifications")
    @patch("app.services.qas_reconciler.sync_transfer_outputs", return_value=[{"ok": True, "job_id": 42}])
    def test_confirmed_qas_job_flushes_openlist_notification_immediately(self, sync_outputs, sync_notifications):
        get_settings.cache_clear()
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(tmdb_id,media_type,display_title,target,provider,status,stage,save_path,
                                          rename_pairs_json,openlist_fallback_to_p115,created_at)
                VALUES(4,'tv','测试剧','cloud','qas','triggered','qas_triggered','/夸克/测试剧',?,1,CURRENT_TIMESTAMP)
                """,
                ('[{"replacement":"测试剧 2026 S01E01.mkv"}]',),
            ).lastrowid

        result = reconcile_triggered_jobs(qas=ConfirmedDirectoryQas())

        self.assertEqual([{"job_id": job_id, "confirmed": True}], result)
        sync_outputs.assert_called_once()
        sync_notifications.assert_called_once()
        with db() as conn:
            message = conn.execute("SELECT message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()[0]
        self.assertIn("OpenList 已提交后台复制任务 #42", message)
        get_settings.cache_clear()


    @patch("app.services.qas_reconciler.sync_transfer_outputs", return_value=[{"ok": True, "job_id": 43}])
    def test_count_only_qas_job_waits_for_all_files_then_syncs_directory(self, sync_outputs):
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(tmdb_id,media_type,display_title,target,provider,status,stage,save_path,
                                          rename_pairs_json,openlist_fallback_to_p115,created_at)
                VALUES(5,'tv','test','cloud','qas','triggered','qas_triggered','/quark/test',?,1,CURRENT_TIMESTAMP)
                """,
                ('[{"expected_count":2}]',),
            ).lastrowid

        class CountQas:
            def savepath_detail(self, path):
                return {
                    "success": True,
                    "data": {"list": [{"name": "one.mkv", "size": 1}, {"name": "two.mkv", "size": 1}]},
                }

            def task_data(self):
                return {"push_config": {}}

        result = reconcile_triggered_jobs(qas=CountQas())

        self.assertEqual([{"job_id": job_id, "confirmed": True}], result)
        sync_outputs.assert_called_once()
        self.assertEqual([], sync_outputs.call_args.args[2])

    @patch("app.services.qas_reconciler.sync_transfer_notifications")
    @patch(
        "app.services.qas_reconciler.sync_transfer_outputs",
        return_value=[{"ok": True, "job_id": 44, "landed": 1}],
    )
    def test_confirmed_qas_wishlist_removes_all_provider_rows_after_openlist_pipeline(
        self,
        sync_outputs,
        sync_notifications,
    ):
        with db() as conn:
            qas_wishlist_id = int(conn.execute(
                """
                INSERT INTO wishlist(tmdb_id,media_type,title,save_target,provider,status)
                VALUES(40,'movie','愿望单电影','cloud','qas','triggered')
                """
            ).lastrowid)
            conn.execute(
                """
                INSERT INTO wishlist(tmdb_id,media_type,title,save_target,provider,status)
                VALUES(40,'movie','愿望单电影','cloud','p115','retry_wait')
                """
            )
            job_id = int(conn.execute(
                """
                INSERT INTO transfer_jobs(
                    wishlist_id,tmdb_id,media_type,display_title,target,provider,status,stage,
                    save_path,rename_pairs_json,openlist_fallback_to_p115,created_at
                ) VALUES(?,40,'movie','愿望单电影','cloud','qas','triggered','qas_triggered',
                         '/quark/movie/愿望单电影',?,1,CURRENT_TIMESTAMP)
                """,
                (qas_wishlist_id, '[{"replacement":"测试剧 2026 S01E01.mkv"}]'),
            ).lastrowid)

        result = reconcile_triggered_jobs(qas=ConfirmedDirectoryQas())

        self.assertEqual([{"job_id": job_id, "confirmed": True}], result)
        sync_outputs.assert_called_once()
        sync_notifications.assert_called_once()
        with db() as conn:
            wishlist_count = int(conn.execute(
                "SELECT COUNT(*) FROM wishlist WHERE tmdb_id=40 AND media_type='movie'"
            ).fetchone()[0])
            source_job = conn.execute(
                "SELECT notification_sent_at FROM transfer_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        self.assertEqual(0, wishlist_count)
        self.assertTrue(source_job["notification_sent_at"])


if __name__ == "__main__":
    unittest.main()
