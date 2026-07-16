import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks

from app.api.transfers import TransferCreate, _run_transfer_job, create_transfer, enqueue_transfer
from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget
from app.services.transfer_service_v2 import execute_transfer_v2


class TransferApiTests(unittest.TestCase):
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

    def test_create_returns_running_job_before_worker_finishes(self):
        background = BackgroundTasks()
        payload = TransferCreate(tmdb_id=1, media_type="movie", title="测试电影", target="cloud")
        response = create_transfer(payload, background)
        self.assertEqual("running", response["status"])
        self.assertEqual("tmdb_resolving", response["stage"])
        self.assertEqual(1, len(background.tasks))
        with db() as conn:
            row = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (response["id"],)).fetchone()
        self.assertEqual(("running", "tmdb_resolving"), tuple(row))

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
            return LinkResolution(False, "no_resource", "none")

        with (
            patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
            patch("app.services.transfer_service_v2.resolve_save_path_progress", return_value=("/strm/tv/Test Series(2026)", 1)),
            patch("app.services.transfer_service_v2.resolve_episode_source", side_effect=fake_resolve),
        ):
            execute_transfer_v2(1, "tv", "cloud", 3, tmdb=object(), qas=object())

        self.assertEqual((2, 3, 4), captured["episodes"])

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
            row = conn.execute("SELECT target,stage FROM transfer_jobs WHERE id=?", (result["id"],)).fetchone()
        self.assertEqual(("local", "tmdb_resolving"), tuple(row))


if __name__ == "__main__":
    unittest.main()
