import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import BackgroundTasks

from app.api.tracking import (
    TrackingOpenListFallbackUpdate,
    TrackingProviderUpdate,
    TrackingSavePathUpdate,
    TrackingShareFillRequest,
    _enqueue_tracking_run,
    fill_missing_episodes_from_share,
    list_tracking,
    update_provider,
    update_openlist_fallback,
    update_tracking_save_path,
)
from app.core.config import get_settings
from app.db.database import db, init_db


class TrackingApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "ENABLED_CLOUD_PROVIDERS": "qas,quark,p115",
                "P115_COOKIE": "UID=1_A1_1; CID=test; SEID=test",
                "P115_ROOT_PATH": "/媒体库",
                "QUARK_ROOT_PATH": "/夸克媒体库",
                "QUARK_COOKIE": "__puus=test",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_triggered_count_remains_cumulative_after_qas_confirmation(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number)
                VALUES(1,'tv','测试剧',3)
                """
            ).lastrowid
            conn.executemany(
                """
                INSERT INTO tracking_episodes(
                    task_id,season_number,episode_number,status,source_file,rename_to
                ) VALUES(?,3,?,?,?,?)
                """,
                [
                    (task_id, 1, "saved", "", ""),
                    (task_id, 2, "saved", "02.mp4", "测试剧.2026.S03E02.mp4"),
                    (task_id, 3, "triggered", "03.mp4", "测试剧.2026.S03E03.mp4"),
                    (task_id, 4, "pending", "", ""),
                ],
            )

        task = list_tracking()[0]

        self.assertEqual(2, task["saved_count"])
        self.assertEqual(2, task["triggered_count"])
        self.assertEqual(4, task["episode_count"])

    def test_enabling_second_provider_preserves_first_provider_storage_state(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,year,season_number,provider,save_path,last_saved_episode
                ) VALUES(2,'tv','测试剧','2026',1,'qas','/strm/tv/测试剧(2026)',8)
                """
            ).lastrowid
            conn.execute(
                "INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,provider) VALUES(?,1,1,'saved','qas')",
                (task_id,),
            )

        result = update_provider(task_id, TrackingProviderUpdate(provider="p115"))

        self.assertEqual("p115", result["provider"])
        with db() as conn:
            tasks = conn.execute(
                "SELECT provider,last_saved_episode FROM tracking_tasks WHERE tmdb_id=2 ORDER BY provider"
            ).fetchall()
            episode = conn.execute("SELECT provider,status FROM tracking_episodes WHERE task_id=?", (task_id,)).fetchone()
        self.assertEqual([("p115", 0), ("qas", 8)], [tuple(row) for row in tasks])
        self.assertEqual(("qas", "saved"), tuple(episode))
        grouped = list_tracking()
        self.assertEqual(1, len(grouped))
        self.assertEqual(["qas", "p115"], [state["provider"] for state in grouped[0]["provider_states"]])

    def test_authoritative_qas_scan_is_not_overridden_by_legacy_local_progress(self):
        with db() as conn:
            legacy_id = conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,year,season_number,save_target,provider,last_saved_episode
                ) VALUES(3,'variety','Legacy Show','2024',3,'local','',3)
                """
            ).lastrowid
            qas_id = conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,year,season_number,save_target,provider,last_saved_episode,last_storage_check_at
                ) VALUES(3,'variety','Legacy Show','2024',3,'cloud','qas',5,'2026-07-26T09:00:00+00:00')
                """
            ).lastrowid
            conn.executemany(
                "INSERT INTO tracking_episodes(task_id,season_number,episode_number,status,provider) VALUES(?,3,?,'saved',?)",
                [
                    (legacy_id, 1, ""),
                    (legacy_id, 2, ""),
                    (legacy_id, 3, ""),
                    (qas_id, 4, "qas"),
                    (qas_id, 5, "qas"),
                ],
            )

        task = list_tracking()[0]
        qas_state = task["provider_states"][0]

        self.assertEqual("qas", qas_state["provider"])
        self.assertEqual(2, qas_state["saved_count"])
        self.assertEqual(5, qas_state["last_saved_episode"])

    def test_list_tracking_marks_provider_states_when_openlist_sync_is_running(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,year,season_number,provider)
                VALUES(4,'variety','Sync Show','2024',3,'qas')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO transfer_jobs(
                    task_id,tmdb_id,media_type,season_number,target,provider,status,stage
                ) VALUES(?,4,'variety',3,'cloud','openlist','running','openlist_sync')
                """,
                (task_id,),
            )

        task = list_tracking()[0]

        self.assertTrue(task["provider_states"][0]["storage_syncing"])

    def test_manual_share_fill_uses_only_selected_episodes(self):
        background_tasks = BackgroundTasks()
        with patch(
            "app.api.tracking._enqueue_tracking_run",
            return_value={"ok": True, "id": 91, "status": "running", "stage": "checking_saved", "message": "正在准备追更任务", "duplicate": False},
        ) as enqueue:
            result = fill_missing_episodes_from_share(
                8,
                TrackingShareFillRequest(share_url="https://pan.quark.cn/s/example", episode_numbers=[3, 1, 3]),
                background_tasks,
            )

        self.assertTrue(result["ok"])
        enqueue.assert_called_once_with(
            8,
            selected_episode_numbers=(1, 3),
            request_source="tracking_share_fill",
        )
        self.assertEqual(1, len(background_tasks.tasks))
        self.assertEqual("https://pan.quark.cn/s/example", background_tasks.tasks[0].kwargs["approved_share_url"])

    def test_tracking_run_is_persisted_before_background_work_starts(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_target,save_path)
                VALUES(11,'tv','进度测试',1,'p115','cloud','/媒体库/tv/进度测试')
                """
            ).lastrowid

        first = _enqueue_tracking_run(int(task_id), selected_episode_numbers=(1, 3), request_source="tracking_fill")
        duplicate = _enqueue_tracking_run(int(task_id), selected_episode_numbers=(1, 3), request_source="tracking_fill")

        self.assertEqual("running", first["status"])
        self.assertEqual("checking_saved", first["stage"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["id"], duplicate["id"])
        with db() as conn:
            job = conn.execute("SELECT task_id,provider,status,stage,message FROM transfer_jobs WHERE id=?", (first["id"],)).fetchone()
        self.assertEqual((int(task_id), "p115", "running", "checking_saved"), tuple(job)[:4])
        self.assertIn("准备", job[4])

    def test_tracking_save_path_must_stay_inside_provider_category(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,category,title,season_number,provider,save_path)
                VALUES(9,'tv','tv','Path Show',1,'p115','/媒体库/tv/Path Show/Season 1')
                """
            ).lastrowid

        with patch("app.api.tracking.refresh_saved_episodes", return_value={"ok": True, "message": "已刷新"}):
            result = update_tracking_save_path(
                int(task_id),
                TrackingSavePathUpdate(save_path="/媒体库/tv/Path Show/自定义季目录"),
            )

        self.assertTrue(result["ok"])
        self.assertEqual("/媒体库/tv/Path Show/自定义季目录", result["save_path"])
        with db() as conn:
            saved_path = conn.execute("SELECT save_path FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()[0]
        self.assertEqual("/媒体库/tv/Path Show/自定义季目录", saved_path)

    def test_native_quark_tracking_save_path_can_be_changed(self):
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,category,title,season_number,provider,save_path)
                VALUES(10,'tv','tv','Quark Path Show',1,'quark','/夸克媒体库/tv/Quark Path Show/Season 1')
                """
            ).lastrowid

        with patch("app.api.tracking.refresh_saved_episodes", return_value={"ok": True, "message": "已刷新"}):
            result = update_tracking_save_path(
                int(task_id),
                TrackingSavePathUpdate(save_path="/夸克媒体库/tv/Quark Path Show/自定义季目录"),
            )

        self.assertTrue(result["ok"])
        self.assertEqual("/夸克媒体库/tv/Quark Path Show/自定义季目录", result["save_path"])

    def test_openlist_fallback_is_an_explicit_p115_season_setting(self):
        with db() as conn:
            quark_id = int(conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path)
                VALUES(12,'tv','Fallback Show',1,'quark','/夸克媒体库/tv/Fallback Show/Season 1')
                """
            ).lastrowid)
            p115_id = int(conn.execute(
                """
                INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,save_path)
                VALUES(12,'tv','Fallback Show',1,'p115','/媒体库/tv/Fallback Show/Season 1')
                """
            ).lastrowid)

        with patch.dict(
            os.environ,
            {
                "OPENLIST_ENABLED": "true",
                "OPENLIST_URL": "http://openlist.test",
                "OPENLIST_TOKEN": "token",
                "OPENLIST_QAS_LIBRARY_PATH": "/夸克",
                "OPENLIST_P115_LIBRARY_PATH": "/115",
            },
        ):
            get_settings.cache_clear()
            result = update_openlist_fallback(p115_id, TrackingOpenListFallbackUpdate(enabled=True))

        self.assertTrue(result["enabled"])
        task = list_tracking()[0]
        p115_state = next(state for state in task["provider_states"] if state["provider"] == "p115")
        self.assertTrue(p115_state["openlist_fallback_to_p115"])

        update_provider(quark_id, TrackingProviderUpdate(provider="quark", enabled=False))
        with db() as conn:
            enabled = conn.execute(
                "SELECT openlist_fallback_to_p115 FROM tracking_tasks WHERE id=?",
                (p115_id,),
            ).fetchone()[0]
        self.assertEqual(0, enabled)


if __name__ == "__main__":
    unittest.main()
