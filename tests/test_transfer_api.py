import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from app.api.transfers import (
    CloudDownloadOrganizerRunRequest,
    TransferBatchCreate,
    TransferBatchItem,
    TransferCreate,
    _run_transfer_job,
    create_transfer,
    create_transfer_batch,
    delete_wecom_transfer_record,
    enqueue_transfer,
    get_transfer_batch,
    list_transfer_logs,
    list_wecom_transfer_records,
    run_cloud_download_organizer_now,
    stop_transfer,
    stop_active_transfers,
)
from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget
from app.services.transfer_service_v2 import execute_transfer_v2


class TransferApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db"), "QUARK_COOKIE": "__puus=test"})
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_create_returns_running_job_before_worker_finishes(self):
        background = BackgroundTasks()
        payload = TransferCreate(tmdb_id=1, media_type="movie", title="测试电影", target="cloud")
        response = create_transfer(payload, background)
        self.assertEqual("running", response["status"])
        self.assertEqual("tmdb_resolving", response["stage"])
        self.assertEqual(1, len(background.tasks))
        with db() as conn:
            row = conn.execute(
                "SELECT status,stage,provider,execution_key FROM transfer_jobs WHERE id=?", (response["id"],)
            ).fetchone()
        self.assertEqual(("running", "tmdb_resolving", "quark", "1:movie:0:cloud:quark"), tuple(row))

    def test_activity_log_export_can_read_more_than_the_dashboard_limit(self):
        with db() as conn:
            conn.executemany(
                "INSERT INTO transfer_jobs(target,provider,status,stage,display_title) VALUES('cloud','quark','done','provider_completed',?)",
                [(f"日志 {index}",) for index in range(105)],
            )

        records = list_transfer_logs(50000)

        self.assertEqual(105, len(records))
        self.assertEqual("日志 104", records[0]["display_title"])

    def test_manual_cloud_download_scan_endpoint_is_retained_but_rejected(self):
        background = BackgroundTasks()
        with self.assertRaises(HTTPException) as raised:
            run_cloud_download_organizer_now(CloudDownloadOrganizerRunRequest(), background)
        self.assertEqual(409, raised.exception.status_code)
        self.assertIn("前序动作事件或定时任务", str(raised.exception.detail))
        self.assertIn("不提供手动全量扫描", str(raised.exception.detail))
        self.assertEqual(0, len(background.tasks))

    def test_deleting_wecom_record_hides_only_the_record(self):
        with db() as conn:
            job_id = int(
                conn.execute(
                    """
                    INSERT INTO transfer_jobs(display_title,target,request_source,request_user)
                    VALUES(?,?,?,?)
                    """,
                    ("记录测试", "cloud", "wecom", "sunny"),
                ).lastrowid
            )

        self.assertEqual([job_id], [item["id"] for item in list_wecom_transfer_records(30)])
        self.assertEqual({"ok": True, "id": job_id}, delete_wecom_transfer_record(job_id))
        self.assertEqual([], list_wecom_transfer_records(30))
        with db() as conn:
            self.assertIsNotNone(conn.execute("SELECT id FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())

    def test_create_moviepilot_job_persists_explicit_provider(self):
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "quark,moviepilot_115",
                "MOVIEPILOT_BASE_URL": "https://moviepilot.example",
                "MOVIEPILOT_API_TOKEN": "secret",
            },
        ):
            get_settings.cache_clear()
            response = create_transfer(
                TransferCreate(
                    tmdb_id=2,
                    media_type="movie",
                    title="115 测试电影",
                    target="cloud",
                    provider="moviepilot_115",
                ),
                BackgroundTasks(),
            )
        with db() as conn:
            row = conn.execute(
                "SELECT provider,execution_key FROM transfer_jobs WHERE id=?", (response["id"],)
            ).fetchone()
        self.assertEqual(("moviepilot_115", "2:movie:0:cloud:moviepilot_115"), tuple(row))

    def test_worker_persists_progress_and_terminal_result(self):
        background = BackgroundTasks()
        payload = TransferCreate(tmdb_id=1, media_type="movie", title="测试电影", target="cloud")
        response = create_transfer(payload, background)

        def fake_execute(*args, on_progress=None, **kwargs):
            on_progress("searching_sources", "正在搜索资源")
            return {"ok": False, "stage": "internal_error", "message": "模拟失败", "save_path": ""}

        with patch("app.api.transfers.execute_transfer_v2", side_effect=fake_execute):
            _run_transfer_job(payload, response["id"])
        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (response["id"],)).fetchone()
        self.assertEqual(("failed", "internal_error", "模拟失败"), tuple(row))

    def test_worker_triggers_openlist_sync_after_confirmed_cloud_transfer(self):
        payload = TransferCreate(
            tmdb_id=1,
            media_type="tv",
            title="同步测试",
            target="cloud",
            season_number=3,
            provider="quark",
            openlist_fallback_to_p115=True,
        )
        response = create_transfer(payload, BackgroundTasks())
        result = {
            "ok": True,
            "stage": "provider_completed",
            "message": "夸克完成",
            "save_path": "/strm/tv/同步测试",
            "resolution": {
                "rename_pairs": [
                    {"source_name": "raw.mkv", "replacement": "同步测试.S03E01.mkv"},
                ],
                "share_url": "https://example.test/share",
            },
        }
        with (
            patch.dict(os.environ, {"ENABLED_CLOUD_PROVIDERS": "quark,p115", "OPENLIST_ENABLED": "true", "OPENLIST_AUTO_SYNC": "true"}),
            patch("app.api.transfers.execute_transfer_v2", return_value=result),
            patch("app.api.transfers.sync_transfer_outputs", return_value=[{"ok": True}]) as sync_outputs,
        ):
            get_settings.cache_clear()
            _run_transfer_job(payload, response["id"])

        sync_outputs.assert_called_once_with(
            "quark",
            "/strm/tv/同步测试",
            ["同步测试.S03E01.mkv"],
            tmdb_id=1,
            media_type="tv",
            season_number=3,
            display_title="同步测试",
            target_providers=("p115",),
        )
        with db() as conn:
            row = conn.execute("SELECT status,message FROM transfer_jobs WHERE id=?", (response["id"],)).fetchone()
        self.assertEqual("done", row["status"])
        self.assertIn("OpenList 已同步 1 个文件", row["message"])

    def test_native_transfer_routes_exact_outputs_to_cloud_download_organizer(self):
        payload = TransferCreate(tmdb_id=21, media_type="movie", title="定点测试", target="cloud", provider="quark")
        response = create_transfer(payload, BackgroundTasks())
        outputs = (
            {"file_id": "q-21", "parent_id": "download-movies", "file_name": "定点测试.2026.mkv", "size": 21, "path": "/媒体/云下载/01电影"},
        )
        result = {
            "ok": True,
            "stage": "provider_completed",
            "message": "夸克完成",
            "save_path": "/媒体/云下载/01电影",
            "resolution": {"rename_pairs": [{"replacement": "定点测试.2026.mkv"}]},
            "execution": {"outputs": outputs},
        }
        with (
            patch("app.api.transfers.execute_transfer_v2", return_value=result),
            patch("app.api.transfers.try_targeted_cloud_download_organization", return_value=(True, "已完成定点整理")) as organize,
            patch("app.api.transfers.sync_transfer_outputs") as openlist,
            patch("app.api.transfers.run_post_transfer_pipeline") as direct_pipeline,
        ):
            _run_transfer_job(payload, response["id"])

        organize.assert_called_once_with(
            provider="quark",
            target_path="/媒体/云下载/01电影",
            target_files=outputs,
            media_title="定点测试",
            media_year="",
        )
        openlist.assert_not_called()
        direct_pipeline.assert_not_called()
        with db() as conn:
            message = conn.execute("SELECT message FROM transfer_jobs WHERE id=?", (response["id"],)).fetchone()[0]
        self.assertIn("已完成定点整理", message)

    def test_interaction_cloud_download_never_falls_back_to_raw_strm(self):
        payload = TransferCreate(
            tmdb_id=22,
            media_type="movie",
            title="云下载测试",
            year="2026",
            target="cloud",
            provider="quark",
            request_source="wecom",
            request_user="sunny",
        )
        response = enqueue_transfer(payload, interaction_cloud_download_child="01电影")
        outputs = (
            {
                "file_id": "q-22",
                "parent_id": "download-movie",
                "file_name": "云下载测试.2026.mkv",
                "path": "/独立云下载/01电影/云下载测试 (2026)",
            },
        )
        result = {
            "ok": True,
            "stage": "provider_completed",
            "message": "夸克云下载完成",
            "save_path": "/独立云下载/01电影/云下载测试 (2026)",
            "resolution": {"rename_pairs": [{"replacement": "云下载测试.2026.mkv"}]},
            "execution": {"outputs": outputs},
        }
        with (
            patch("app.api.transfers.execute_transfer_v2", return_value=result) as execute,
            patch("app.api.transfers.try_targeted_cloud_download_organization", return_value=(False, "")),
            patch("app.api.transfers.sync_transfer_outputs") as openlist,
            patch("app.api.transfers.run_post_transfer_pipeline") as raw_pipeline,
        ):
            _run_transfer_job(
                payload,
                response["id"],
                interaction_cloud_download_child="01电影",
            )

        self.assertEqual("01电影", execute.call_args.kwargs["interaction_cloud_download_child"])
        self.assertEqual("wecom", execute.call_args.kwargs["request_source"])
        openlist.assert_not_called()
        raw_pipeline.assert_not_called()
        with db() as conn:
            job = conn.execute(
                "SELECT execution_key,message FROM transfer_jobs WHERE id=?",
                (response["id"],),
            ).fetchone()
            steps = {
                row["step_key"]: (row["status"], row["message"])
                for row in conn.execute(
                    "SELECT step_key,status,message FROM media_workflow_steps WHERE job_id=?",
                    (response["id"],),
                ).fetchall()
            }
        self.assertIn(":cloud-download:", job["execution_key"])
        self.assertIn("云下载原始文件未生成 STRM", job["message"])
        self.assertEqual("skipped", steps["strm_generate"][0])
        self.assertEqual("skipped", steps["emby_refresh"][0])

    def test_stopped_job_is_not_overwritten_by_worker_result(self):
        payload = TransferCreate(tmdb_id=1, media_type="movie", title="测试电影", target="cloud")
        response = create_transfer(payload, BackgroundTasks())
        stop_result = stop_active_transfers()
        self.assertEqual(1, stop_result["stopped"])

        with patch("app.api.transfers.execute_transfer_v2", return_value={"ok": True, "stage": "done", "message": "完成", "save_path": "/tv"}):
            _run_transfer_job(payload, response["id"])

        with db() as conn:
            row = conn.execute("SELECT status,stage,message FROM transfer_jobs WHERE id=?", (response["id"],)).fetchone()
        self.assertEqual(("stopped", "stopped", "已由用户停止"), tuple(row))

    def test_stop_transfer_only_stops_the_selected_running_job(self):
        first = create_transfer(TransferCreate(tmdb_id=1, media_type="movie", title="任务一", target="cloud"), BackgroundTasks())
        second = create_transfer(TransferCreate(tmdb_id=2, media_type="movie", title="任务二", target="cloud"), BackgroundTasks())

        result = stop_transfer(first["id"])

        self.assertEqual({"ok": True, "stopped": True, "message": "任务已终止"}, result)
        with db() as conn:
            rows = conn.execute("SELECT id,status,message FROM transfer_jobs ORDER BY id").fetchall()
        self.assertEqual(
            [(first["id"], "stopped", "已由用户终止"), (second["id"], "running", "正在匹配 TMDB 媒体信息")],
            [tuple(row) for row in rows],
        )

    def test_stop_actions_leave_non_interruptible_activity_rows_running(self):
        with db() as conn:
            cover_id = int(conn.execute(
                "INSERT INTO transfer_jobs(display_title,provider,target,status,stage) VALUES(?,?,?,?,?)",
                ("封面任务", "emby", "local", "running", "cover_rendering"),
            ).lastrowid)
            scheduled_id = int(conn.execute(
                "INSERT INTO transfer_jobs(display_title,provider,target,status,stage) VALUES(?,?,?,?,?)",
                ("计划任务", "scheduler", "local", "running", "scheduled_running"),
            ).lastrowid)
            transfer_id = int(conn.execute(
                "INSERT INTO transfer_jobs(display_title,provider,target,status,stage) VALUES(?,?,?,?,?)",
                ("转存任务", "quark", "cloud", "running", "provider_triggered"),
            ).lastrowid)

        self.assertEqual(
            {"ok": True, "stopped": False, "message": "此类任务不支持中途终止"},
            stop_transfer(cover_id),
        )
        self.assertEqual({"ok": True, "stopped": 1}, stop_active_transfers())
        with db() as conn:
            rows = conn.execute("SELECT id,status FROM transfer_jobs ORDER BY id").fetchall()
        self.assertEqual(
            [(cover_id, "running"), (scheduled_id, "running"), (transfer_id, "stopped")],
            [tuple(row) for row in rows],
        )


    def test_manual_tv_transfer_only_resolves_episodes_after_saved_folder_progress(self):
        target = MediaTarget(
            106449,
            "tv",
            "凡人修仙传",
            series_year="2020",
            season_number=1,
            episodes=tuple(EpisodeTarget(1, number, "2026-07-11") for number in range(179, 183)),
        )
        captured = {}

        def fake_resolve(candidate, *args, **kwargs):
            captured["episodes"] = tuple(ep.episode_number for ep in candidate.episodes)
            captured["max_queries"] = kwargs.get("max_queries")
            return LinkResolution(False, "no_resource", "none")

        with (
            patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
            patch("app.services.transfer_service_v2.resolve_save_path_progress", return_value=("/下载_未整理/tv/凡人修仙传(2020)", 181)),
            patch("app.services.transfer_service_v2.resolve_episode_source", side_effect=fake_resolve),
        ):
            execute_transfer_v2(106449, "tv", "cloud", 1, tmdb=object(), qas=object())

        self.assertEqual((182,), captured["episodes"])

    def test_manual_tv_transfer_catches_up_all_aired_missing_episodes(self):
        target = MediaTarget(
            1,
            "tv",
            "Test Series",
            series_year="2026",
            season_number=3,
            episodes=tuple(EpisodeTarget(3, number, "2026-07-01") for number in range(1, 5)),
        )
        captured = {}

        def fake_resolve(candidate, *args, **kwargs):
            captured["episodes"] = tuple(ep.episode_number for ep in candidate.episodes)
            captured["max_queries"] = kwargs.get("max_queries")
            return LinkResolution(False, "no_resource", "none")

        with (
            patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
            patch("app.services.transfer_service_v2.resolve_save_path_progress", return_value=("/strm/tv/Test Series(2026)", 1)),
            patch("app.services.transfer_service_v2.resolve_episode_source", side_effect=fake_resolve),
        ):
            execute_transfer_v2(1, "tv", "cloud", 3, tmdb=object(), qas=object())

        self.assertEqual((2, 3, 4), captured["episodes"])
        self.assertEqual(8, captured["max_queries"])

    def test_storage_check_failure_stops_before_resource_search(self):
        target = MediaTarget(1, "tv", "测试剧", series_year="2026", season_number=1, episodes=(EpisodeTarget(1, 1, "2026-01-01"),))
        with (
            patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
            patch("app.services.transfer_service_v2.resolve_save_path_progress", side_effect=TimeoutError("qas timeout")),
            patch("app.services.transfer_service_v2.resolve_episode_source") as resolver,
        ):
            result = execute_transfer_v2(1, "tv", "cloud", 1, tmdb=object(), qas=object())
        self.assertFalse(result["ok"])
        self.assertEqual("storage_check_failed", result["stage"])
        resolver.assert_not_called()

    def test_moviepilot_tv_search_skips_qas_storage_and_requires_confirmation(self):
        target = MediaTarget(
            1,
            "tv",
            "测试剧",
            series_year="2026",
            season_number=1,
            episodes=(EpisodeTarget(1, 1, "2026-01-01"),),
        )
        resolution = LinkResolution(False, "needs_review", "确认后提交 MoviePilot")
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "qas,moviepilot_115",
                "MOVIEPILOT_BASE_URL": "https://moviepilot.example",
                "MOVIEPILOT_API_TOKEN": "secret",
            },
        ):
            get_settings.cache_clear()
            with (
                patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
                patch("app.services.transfer_service_v2.resolve_save_path_progress") as storage,
                patch("app.services.transfer_service_v2.resolve_episode_source", return_value=resolution) as resolver,
            ):
                result = execute_transfer_v2(
                    1,
                    "tv",
                    "cloud",
                    1,
                    tmdb=object(),
                    qas=object(),
                    provider="moviepilot_115",
                )
        storage.assert_not_called()
        self.assertEqual("moviepilot_115", resolver.call_args.kwargs["provider_filter"])
        self.assertEqual("needs_review", result["stage"])

    def test_duplicate_active_manual_transfer_reuses_existing_job(self):
        payload = TransferCreate(tmdb_id=9, media_type="tv", target="cloud", season_number=1)
        first = create_transfer(payload, BackgroundTasks())
        second_background = BackgroundTasks()
        second = create_transfer(payload, second_background)
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(0, len(second_background.tasks))

    def test_enqueue_transfer_creates_job_without_background_task(self):
        result = enqueue_transfer(TransferCreate(tmdb_id=11, media_type="movie", target="local"))
        self.assertEqual("running", result["status"])
        with db() as conn:
            row = conn.execute(
                "SELECT target,stage,provider,execution_key FROM transfer_jobs WHERE id=?", (result["id"],)
            ).fetchone()
        self.assertEqual(("local", "tmdb_resolving", "", "11:movie:0:local:"), tuple(row))

    def test_direct_movie_job_has_identity_specific_execution_key(self):
        result = enqueue_transfer(
            TransferCreate(
                tmdb_id=0,
                media_type="movie",
                title="Spider Man No Way Home",
                year="2021",
                target="local",
                skip_tmdb=True,
            )
        )
        with db() as conn:
            row = conn.execute(
                "SELECT stage,execution_key FROM transfer_jobs WHERE id=?", (result["id"],)
            ).fetchone()
        self.assertEqual("pansou_identifying", row["stage"])
        self.assertEqual("0:movie:0:local::direct:spidermannowayhome:2021", row["execution_key"])

    def test_selected_episodes_use_a_distinct_transfer_execution_key(self):
        result = enqueue_transfer(TransferCreate(tmdb_id=12, media_type="tv", season_number=1, target="cloud", episode_numbers=[3, 1, 3]))
        with db() as conn:
            row = conn.execute("SELECT execution_key FROM transfer_jobs WHERE id=?", (result["id"],)).fetchone()
        self.assertEqual("12:tv:1:cloud:quark:episodes:1,3", row["execution_key"])

    def test_selected_movie_share_is_validated_without_pansou_fallback(self):
        selected_url = "https://115cdn.com/s/selected?password=abcd"
        resolution = LinkResolution(False, "no_resource", "所选链接不可用")
        with (
            patch.dict(
                os.environ,
                {
                    "ENABLED_CLOUD_PROVIDERS": "p115",
                    "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
                },
            ),
            patch(
                "app.services.transfer_service_v2.resolve_media_target",
                return_value=MediaTarget(687163, "movie", "挽救计划", category="movie", series_year="2026"),
            ),
            patch("app.services.transfer_service_v2.resolve_provider_key", return_value="p115"),
            patch("app.services.transfer_service_v2.get_transfer_provider", return_value=object()),
            patch("app.services.transfer_service_v2.resolve_movie_source", return_value=resolution) as resolver,
        ):
            execute_transfer_v2(
                687163,
                "movie",
                "cloud",
                preferred_share_urls=(selected_url,),
                preferred_share_only=True,
                provider="p115",
            )

        self.assertEqual((selected_url,), resolver.call_args.args[1])
        self.assertEqual(0, resolver.call_args.kwargs["max_queries"])

    def test_batch_creates_provider_children_and_preserves_partial_success(self):
        background = BackgroundTasks()
        payload = TransferBatchCreate(
            tmdb_id=12,
            media_type="tv",
            title="双网盘测试",
            items=[
                TransferBatchItem(provider="qas", season_number=1),
                TransferBatchItem(provider="p115", season_number=1),
            ],
        )
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "qas,p115",
                "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
            },
        ):
            get_settings.cache_clear()
            created = create_transfer_batch(payload, background)

            def fake_execute(*_args, provider=None, **_kwargs):
                if provider == "qas":
                    return {
                        "ok": True,
                        "stage": "provider_completed",
                        "message": "夸克完成",
                        "save_path": "/strm/tv/test",
                        "resolution": {},
                    }
                return {
                    "ok": False,
                    "stage": "no_resource",
                    "message": "115 未找到资源",
                    "save_path": "",
                    "target": {"title": "双网盘测试"},
                    "resolution": {},
                }

            with patch("app.api.transfers.execute_transfer_v2", side_effect=fake_execute):
                task = background.tasks[0]
                task.func(*task.args, **task.kwargs)
            result = get_transfer_batch(created["id"])

        self.assertEqual("partial", result["status"])
        self.assertEqual({"qas", "p115"}, {child["provider"] for child in result["children"]})
        statuses = {child["provider"]: child["status"] for child in result["children"]}
        self.assertEqual("done", statuses["qas"])
        self.assertEqual("failed", statuses["p115"])

    def test_batch_preserves_selected_share_and_skips_a_second_pansou_search(self):
        background = BackgroundTasks()
        selected_url = "https://115cdn.com/s/selected?password=abcd"
        payload = TransferBatchCreate(
            tmdb_id=687163,
            media_type="movie",
            title="挽救计划",
            items=[
                TransferBatchItem(
                    provider="p115",
                    preferred_share_url=selected_url,
                    preferred_share_only=True,
                ),
            ],
        )
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "p115",
                "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
            },
        ):
            get_settings.cache_clear()
            create_transfer_batch(payload, background)
            with patch(
                "app.api.transfers.execute_transfer_v2",
                return_value={
                    "ok": True,
                    "stage": "provider_completed",
                    "message": "115 完成",
                    "save_path": "/strm/movie/挽救计划 (2026)",
                    "resolution": {},
                },
            ) as execute:
                task = background.tasks[0]
                task.func(*task.args, **task.kwargs)

        call = execute.call_args
        self.assertEqual([selected_url], call.kwargs["preferred_share_urls"])
        self.assertTrue(call.kwargs["preferred_share_only"])

    def test_batch_uses_openlist_only_for_explicit_quark_to_115_fallback(self):
        background = BackgroundTasks()
        payload = TransferBatchCreate(
            tmdb_id=13,
            media_type="tv",
            title="OpenList Diff",
            items=[
                TransferBatchItem(provider="qas", season_number=3, openlist_fallback_to_p115=True),
            ],
        )
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "qas,p115",
                "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
            },
        ):
            get_settings.cache_clear()
            created = create_transfer_batch(payload, background)

            def fake_execute(*_args, provider=None, **_kwargs):
                return {
                    "ok": True,
                    "stage": "provider_completed",
                    "message": f"{provider} 完成",
                    "save_path": "/qas/strm/OpenList Diff (2024)/Season 3",
                    "resolution": {"rename_pairs": [{"replacement": "OpenList Diff.S03E01.mkv"}]},
                }

            with (
                patch("app.api.transfers.execute_transfer_v2", side_effect=fake_execute),
                patch("app.api.transfers.sync_transfer_outputs", return_value=[{"ok": True, "job_id": 77}]) as sync_outputs,
            ):
                task = background.tasks[0]
                task.func(*task.args, **task.kwargs)

        sync_outputs.assert_called_once_with(
            "qas",
            "/qas/strm/OpenList Diff (2024)/Season 3",
            ["OpenList Diff.S03E01.mkv"],
            tmdb_id=13,
            media_type="tv",
            season_number=3,
            display_title="OpenList Diff",
            target_providers=("p115",),
        )

    def test_batch_does_not_keep_wishlist_when_other_provider_covers_auto_sync_pair(self):
        background = BackgroundTasks()
        payload = TransferBatchCreate(
            tmdb_id=14,
            media_type="tv",
            title="主网盘已有资源",
            items=[
                TransferBatchItem(provider="qas", season_number=1),
                TransferBatchItem(provider="p115", season_number=1),
            ],
        )
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "qas,p115",
                "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
                "OPENLIST_ENABLED": "true",
                "OPENLIST_AUTO_SYNC": "true",
                "OPENLIST_AUTO_SYNC_DIRECTION": "qas_to_p115",
            },
        ):
            get_settings.cache_clear()
            created = create_transfer_batch(payload, background)

            def fake_execute(*_args, provider=None, **_kwargs):
                if provider == "p115":
                    return {
                        "ok": True,
                        "stage": "provider_completed",
                        "message": "115 已完成",
                        "save_path": "/media/tv/主网盘已有资源 (2026)/Season 1",
                        "resolution": {},
                    }
                return {
                    "ok": False,
                    "stage": "no_resource",
                    "message": "夸克没有资源",
                    "save_path": "",
                    "target": {"title": "主网盘已有资源"},
                    "resolution": {},
                }

            with patch("app.api.transfers.execute_transfer_v2", side_effect=fake_execute):
                task = background.tasks[0]
                task.func(*task.args, **task.kwargs)

            batch = get_transfer_batch(created["id"])
            with db() as conn:
                wishlist_count = conn.execute(
                    "SELECT COUNT(*) FROM wishlist WHERE tmdb_id=? AND media_type='tv'",
                    (14,),
                ).fetchone()[0]

        self.assertEqual("done", batch["status"])
        self.assertEqual(0, wishlist_count)


    def test_worker_syncs_terminal_transfer_notification_immediately(self):
        payload = TransferCreate(tmdb_id=99, media_type="movie", title="Immediate Notice", target="cloud")
        response = create_transfer(payload, BackgroundTasks())

        def fake_execute(*_args, **_kwargs):
            return {"ok": False, "stage": "internal_error", "message": "simulated failure", "save_path": ""}

        with patch("app.api.transfers.execute_transfer_v2", side_effect=fake_execute):
            _run_transfer_job(payload, response["id"])

        with db() as conn:
            notice = conn.execute(
                "SELECT id FROM notifications WHERE source_key=?",
                (f"transfer:{response['id']}:failed:internal_error",),
            ).fetchone()
        self.assertIsNotNone(notice)


if __name__ == "__main__":
    unittest.main()
