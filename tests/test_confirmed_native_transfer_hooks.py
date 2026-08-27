import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.api.review import _run_confirmed_candidate
from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import (
    EpisodeMatch,
    EpisodeTarget,
    LinkResolution,
    MediaTarget,
    ProviderExecutionResult,
    RenamePair,
    SourceFile,
)
from app.services.tracking_engine_v2 import run_tracking_task
from app.services.wishlist_engine import run_wishlist_item
from app.services.interaction_transfer_context import interaction_cloud_download_execution_marker


class ConfirmedNativeTransferHookTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "ENABLED_CLOUD_PROVIDERS": "qas,p115,quark",
                "P115_COOKIE": "UID=1_A1_1; CID=test; SEID=test",
                "QUARK_COOKIE": "__uid=test",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    @patch("app.services.wishlist_engine.run_confirmed_native_transfer_post_processing")
    @patch("app.services.wishlist_engine.execute_transfer_v2")
    @patch("app.services.qas_reconciler.request_qas_reconciliation")
    def test_wishlist_only_confirmed_native_transfer_continues_with_exact_outputs(
        self,
        _request_reconciliation,
        execute,
        post_process,
    ):
        outputs = (
            {
                "file_id": "p115-1",
                "parent_id": "folder-1",
                "file_name": "测试电影.2026.mkv",
                "path": "/媒体库/movie/测试电影 (2026)",
            },
        )
        execute.return_value = {
            "ok": True,
            "stage": "provider_completed",
            "message": "完成",
            "provider": "p115",
            "save_path": "/媒体库/movie/测试电影 (2026)",
            "target": {"title": "测试电影"},
            "resolution": {"rename_pairs": []},
            "execution": {"confirmed": True, "outputs": outputs},
        }
        with db() as conn:
            item_id = conn.execute(
                """
                INSERT INTO wishlist(tmdb_id,media_type,title,poster_url,save_target,provider,status)
                VALUES(1,'movie','测试电影','poster:test','cloud','p115','pending')
                """
            ).lastrowid

        result = run_wishlist_item(int(item_id))

        self.assertEqual("provider_completed", result["stage"])
        post_process.assert_called_once_with(
            result["job_id"],
            provider="p115",
            save_path="/媒体库/movie/测试电影 (2026)",
            outputs=outputs,
            title="测试电影",
            poster_url="poster:test",
        )

        post_process.reset_mock()
        for tmdb_id, provider, stage in ((4, "p115", "provider_triggered"), (5, "qas", "provider_completed")):
            execute.return_value = {
                "ok": True,
                "stage": stage,
                "message": "已提交" if stage == "provider_triggered" else "完成",
                "provider": provider,
                "save_path": "/媒体库/movie/不应后处理",
                "target": {"title": "不应后处理"},
                "resolution": {"rename_pairs": []},
                "execution": {"confirmed": stage == "provider_completed", "outputs": outputs},
            }
            with db() as conn:
                skipped_item_id = conn.execute(
                    """
                    INSERT INTO wishlist(tmdb_id,media_type,title,save_target,provider,status)
                    VALUES(?,'movie','不应后处理','cloud',?,'pending')
                    """,
                    (tmdb_id, provider),
                ).lastrowid
            run_wishlist_item(int(skipped_item_id))
        post_process.assert_not_called()

    @patch("app.services.tracking_engine_v2.run_confirmed_native_transfer_post_processing")
    @patch("app.services.tracking_engine_v2.refresh_saved_episodes")
    @patch("app.services.tracking_engine_v2.sync_tracking_episodes")
    @patch("app.services.tracking_engine_v2.disable_compatible_qas_schedules")
    @patch("app.services.tracking_engine_v2.build_save_path")
    @patch("app.services.tracking_engine_v2.resolve_media_target")
    @patch("app.services.tracking_engine_v2.resolve_episode_source")
    @patch("app.services.tracking_engine_v2.get_transfer_provider")
    def test_tracking_confirmed_native_transfer_continues_with_exact_outputs(
        self,
        get_provider,
        resolve_source,
        resolve_target,
        build_path,
        _disable_qas,
        _sync_episodes,
        refresh_saved,
        post_process,
    ):
        episode = EpisodeTarget(1, 1, "2026-01-01", "第一集")
        target = MediaTarget(
            2,
            "tv",
            "测试剧",
            category="tv",
            series_year="2026",
            season_number=1,
            episodes=(episode,),
        )
        source = SourceFile("Test.S01E01.mkv", size=1024, provider_file_id="source-1")
        resolution = LinkResolution(
            True,
            "ready",
            "匹配完成",
            share_url="https://pan.quark.cn/s/test",
            matches=(EpisodeMatch(episode, source, 100, "high"),),
            rename_pairs=(
                RenamePair(
                    source.name,
                    "S01E01",
                    "测试剧.2026.S01E01.mkv",
                    episode_number=1,
                    episode_numbers=(1,),
                ),
            ),
        )
        save_path = "/夸克媒体库/tv/测试剧 (2026)/Season 1"
        outputs = (
            {
                "file_id": "quark-1",
                "parent_id": "folder-2",
                "file_name": "测试剧.2026.S01E01.mkv",
                "path": save_path,
            },
        )
        provider = Mock()
        provider.execute.return_value = ProviderExecutionResult(
            True,
            "provider_completed",
            "完成",
            executed_items=1,
            confirmed=True,
            outputs=outputs,
        )
        get_provider.return_value = provider
        resolve_source.return_value = resolution
        resolve_target.return_value = target
        build_path.return_value = save_path
        refresh_saved.return_value = {"ok": True, "save_path": save_path, "last_saved_episode": 0}
        with db() as conn:
            task_id = conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,category,title,poster_url,season_number,
                    save_target,provider,save_path,status,decision_state
                ) VALUES(2,'tv','tv','测试剧','poster:tracking',1,
                         'cloud','quark',?,'active','pending')
                """,
                (save_path,),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO tracking_episodes(task_id,season_number,episode_number,air_date,status,provider)
                VALUES(?,1,1,'2026-01-01','pending','quark')
                """,
                (task_id,),
            )

        result = run_tracking_task(int(task_id), approved_share_url=resolution.share_url, force=True)

        self.assertTrue(result["confirmed"])
        post_process.assert_called_once()
        call = post_process.call_args
        self.assertEqual("quark", call.kwargs["provider"])
        self.assertEqual(save_path, call.kwargs["save_path"])
        self.assertEqual(outputs, call.kwargs["outputs"])
        self.assertEqual("poster:tracking", call.kwargs["poster_url"])

    @patch("app.api.review.run_confirmed_native_transfer_post_processing")
    @patch("app.api.review.execute_transfer_v2")
    def test_review_confirmed_native_transfer_continues_with_exact_outputs(self, execute, post_process):
        outputs = (
            {
                "file_id": "quark-review-1",
                "parent_id": "folder-review",
                "file_name": "待确认电影.2026.mkv",
                "path": "/夸克媒体库/movie/待确认电影 (2026)",
            },
        )
        execute.return_value = {
            "ok": True,
            "stage": "provider_completed",
            "message": "完成",
            "provider": "quark",
            "save_path": "/夸克媒体库/movie/待确认电影 (2026)",
            "target": {"title": "待确认电影", "poster_url": "poster:review"},
            "resolution": {"share_url": "https://pan.quark.cn/s/review", "rename_pairs": []},
            "execution": {"confirmed": True, "outputs": outputs},
        }
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(tmdb_id,media_type,display_title,target,provider,status,stage)
                VALUES(3,'movie','待确认电影','cloud','quark','running','matching_files')
                """
            ).lastrowid
        candidate = {
            "share_url": "https://pan.quark.cn/s/review",
            "source_title": "待确认电影资源",
            "provider": "quark",
        }
        job = {
            "id": int(job_id),
            "tmdb_id": 3,
            "media_type": "movie",
            "display_title": "待确认电影",
            "target": "cloud",
            "provider": "quark",
        }

        _run_confirmed_candidate(candidate, job, [])

        post_process.assert_called_once_with(
            int(job_id),
            provider="quark",
            save_path="/夸克媒体库/movie/待确认电影 (2026)",
            outputs=outputs,
            title="待确认电影",
            poster_url="poster:review",
        )

    @patch("app.api.review.run_confirmed_native_transfer_post_processing")
    @patch("app.api.review.execute_transfer_v2")
    def test_interaction_review_restores_cloud_download_child(self, execute, post_process):
        child = "01电影"
        save_path = "/独立云下载/01电影/待确认电影 (2026)"
        outputs = (
            {
                "file_id": "quark-staging-1",
                "parent_id": "staging-movie",
                "file_name": "待确认电影.2026.mkv",
                "path": save_path,
            },
        )
        execute.return_value = {
            "ok": True,
            "stage": "provider_completed",
            "message": "完成",
            "provider": "quark",
            "save_path": save_path,
            "target": {"title": "待确认电影", "series_year": "2026"},
            "resolution": {"share_url": "https://pan.quark.cn/s/review", "rename_pairs": []},
            "execution": {"confirmed": True, "outputs": outputs},
        }
        execution_key = f"3:movie:0:cloud:quark:{interaction_cloud_download_execution_marker(child)}"
        with patch.dict(os.environ, {"QUARK_CLOUD_DOWNLOAD_PATH": "/独立云下载"}):
            get_settings.cache_clear()
            with db() as conn:
                job_id = conn.execute(
                    """
                    INSERT INTO transfer_jobs(
                        tmdb_id,media_type,display_title,target,provider,status,stage,execution_key,request_source
                    ) VALUES(3,'movie','待确认电影','cloud','quark','running','matching_files',?,'wecom')
                    """,
                    (execution_key,),
                ).lastrowid
            candidate = {
                "share_url": "https://pan.quark.cn/s/review",
                "source_title": "待确认资源",
                "provider": "quark",
            }
            job = {
                "id": int(job_id),
                "tmdb_id": 3,
                "media_type": "movie",
                "display_title": "待确认电影",
                "target": "cloud",
                "provider": "quark",
                "execution_key": execution_key,
                "request_source": "wecom",
            }

            _run_confirmed_candidate(candidate, job, [])

        self.assertEqual(child, execute.call_args.kwargs["interaction_cloud_download_child"])
        self.assertEqual("wecom", execute.call_args.kwargs["request_source"])
        post_process.assert_called_once_with(
            int(job_id),
            provider="quark",
            save_path=save_path,
            outputs=outputs,
            title="待确认电影",
            poster_url="",
            media_year="2026",
            cloud_download_child=child,
        )


if __name__ == "__main__":
    unittest.main()
