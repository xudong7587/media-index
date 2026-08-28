from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import (
    EpisodeTarget,
    LinkResolution,
    MediaTarget,
    ProviderExecutionResult,
    RenamePair,
    ResourceCandidate,
)
from app.services.query_planner import build_search_queries
from app.services.saved_episode_scanner import SavePathProgress
from app.services.transfer_recovery import recover_untracked_provider_submissions
from app.services.transfer_service_v2 import _combine_executions, execute_transfer_v2


@pytest.fixture
def initialized_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    init_db()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_recovery_closes_only_untracked_external_provider_submissions(initialized_db):
    with db() as conn:
        p115_id = conn.execute(
            """
            INSERT INTO transfer_jobs(media_type,target,provider,status,stage,message)
            VALUES('direct','cloud','p115','triggered','provider_submitting','115 已接受任务')
            """
        ).lastrowid
        moviepilot_id = conn.execute(
            """
            INSERT INTO transfer_jobs(media_type,target,provider,status,stage,message)
            VALUES('movie','cloud','moviepilot_115','triggered','provider_triggered','MoviePilot 已接受任务')
            """
        ).lastrowid
        qas_id = conn.execute(
            """
            INSERT INTO transfer_jobs(media_type,target,provider,status,stage,message)
            VALUES('tv','cloud','qas','triggered','provider_triggered','等待 QAS 确认')
            """
        ).lastrowid

    assert recover_untracked_provider_submissions() == 2

    with db() as conn:
        p115 = conn.execute("SELECT status,stage,message,finished_at FROM transfer_jobs WHERE id=?", (p115_id,)).fetchone()
        moviepilot = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (moviepilot_id,)).fetchone()
        qas = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (qas_id,)).fetchone()

    assert (p115["status"], p115["stage"]) == ("done", "provider_submitted")
    assert "不再持续跟踪" in p115["message"]
    assert p115["finished_at"]
    assert tuple(moviepilot) == ("done", "provider_submitted")
    assert tuple(qas) == ("triggered", "provider_triggered")


def test_p115_pending_message_respects_qas_to_p115_direction():
    execution = SimpleNamespace(ok=True, confirmed=False, stage="provider_triggered", outputs=())
    resolution = SimpleNamespace(rename_pairs=())
    target = SimpleNamespace(media_type="tv", episodes=())
    settings = SimpleNamespace(
        openlist_enabled=True,
        openlist_auto_sync=True,
        openlist_auto_sync_direction="qas_to_p115",
    )

    with patch("app.services.transfer_service_v2.get_settings", return_value=settings):
        p115 = _combine_executions([execution], [resolution], resolution, target, provider="p115")
        qas = _combine_executions([execution], [resolution], resolution, target, provider="qas")

    assert "OpenList 复制" not in p115["message"]
    assert "确认后将发起 OpenList 复制" in qas["message"]


def test_movie_execution_failure_preserves_provider_error():
    execution = SimpleNamespace(
        ok=False,
        confirmed=False,
        stage="provider_failed",
        message="115 创建暂存目录失败（错误码 990002）",
        executed_items=0,
        outputs=(),
    )
    resolution = SimpleNamespace(rename_pairs=(SimpleNamespace(episode_numbers=(), episode_number=None),))
    target = SimpleNamespace(media_type="movie", episodes=())

    result = _combine_executions([execution], [resolution], resolution, target, provider="p115")

    assert not result["ok"]
    assert result["stage"] == "provider_failed"
    assert result["message"] == "链接 1：115 创建暂存目录失败（错误码 990002）"
    assert "0 集" not in result["message"]


def test_direct_tv_transfer_uses_exact_sparse_inventory_before_high_water():
    target = MediaTarget(
        1,
        "tv",
        "测试剧",
        series_year="2026",
        season_number=1,
        episodes=tuple(EpisodeTarget(1, number, "2026-01-01") for number in range(1, 18)),
    )
    captured_targets = []

    def resolve(target_to_search, *_args, **_kwargs):
        captured_targets.append(target_to_search)
        return LinkResolution(False, "no_resource", "none")

    with (
        patch("app.services.transfer_service_v2.resolve_provider_key", return_value="p115"),
        patch("app.services.transfer_service_v2.get_transfer_provider", return_value=object()),
        patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
        patch(
            "app.services.transfer_service_v2.resolve_save_path_progress",
            return_value=SavePathProgress(
                "/媒体库/测试剧/Season 1",
                17,
                frozenset({16, 17}),
                True,
                True,
            ),
        ),
        patch("app.services.transfer_service_v2.resolve_episode_source", side_effect=resolve),
    ):
        result = execute_transfer_v2(
            1,
            "tv",
            "cloud",
            1,
            tmdb=object(),
            pansou=object(),
            qas=object(),
            provider="p115",
        )

    assert result["stage"] == "no_resource"
    assert len(captured_targets) == 1
    assert [episode.episode_number for episode in captured_targets[0].episodes] == list(range(1, 16))


def test_p115_duplicate_candidate_falls_through_to_per_episode_links_and_aggregates_once():
    links = tuple(f"https://115.com/s/episode-{number}" for number in range(4))
    target = MediaTarget(
        1,
        "tv",
        "测试剧",
        series_year="2026",
        season_number=1,
        episodes=tuple(EpisodeTarget(1, number, "2026-01-01") for number in range(1, 4)),
    )

    def resolution(url: str, episode: int, reviewed=()) -> LinkResolution:
        return LinkResolution(
            True,
            "ready",
            "ready",
            share_url=url,
            rename_pairs=(
                RenamePair(
                    f"source-{episode}.mkv",
                    f"source-{episode}\\.mkv",
                    f"测试剧.2026.S01E{episode:02d}.mkv",
                    episode_number=episode,
                ),
            ),
            reviewed_candidates=tuple(ResourceCandidate(item, provider="p115", cloud_type="115") for item in reviewed),
        )

    resolutions = (
        resolution(links[0], 1, links),
        resolution(links[1], 1, (links[1],)),
        resolution(links[2], 2, (links[2],)),
        resolution(links[3], 3, (links[3],)),
    )

    class Provider:
        def __init__(self):
            self.calls = []

        def execute(self, plan):
            self.calls.append(plan.resolution.share_url)
            if plan.resolution.share_url == links[0]:
                return ProviderExecutionResult(
                    False,
                    "provider_failed",
                    "115 转存失败：该分享文件已接收过（错误码 4200045）",
                )
            episode = plan.resolution.rename_pairs[0].episode_number
            return ProviderExecutionResult(
                True,
                "provider_completed",
                "done",
                executed_items=1,
                confirmed=True,
                outputs=({"file_name": f"测试剧.2026.S01E{episode:02d}.mkv"},),
            )

    provider = Provider()
    with (
        patch("app.services.transfer_service_v2.resolve_provider_key", return_value="p115"),
        patch("app.services.transfer_service_v2.get_transfer_provider", return_value=provider),
        patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
        patch("app.services.transfer_service_v2.resolve_save_path_progress", return_value=("/媒体库/测试剧/Season 1", 0)),
        patch("app.services.transfer_service_v2.resolve_episode_source", side_effect=resolutions) as resolver,
    ):
        result = execute_transfer_v2(
            1,
            "tv",
            "cloud",
            1,
            tmdb=object(),
            pansou=object(),
            qas=object(),
            provider="p115",
        )

    assert result["ok"]
    assert result["stage"] == "provider_completed"
    assert provider.calls == list(links)
    assert resolver.call_count == 4
    assert len(result["resolution"]["rename_pairs"]) == 3
    assert [item["file_name"] for item in result["execution"]["outputs"]] == [
        "测试剧.2026.S01E01.mkv",
        "测试剧.2026.S01E02.mkv",
        "测试剧.2026.S01E03.mkv",
    ]


def test_p115_per_episode_links_continue_with_title_search_after_first_twenty_candidates():
    links = tuple(f"https://115.com/s/episode-{number}" for number in range(1, 23))
    target = MediaTarget(
        1,
        "tv",
        "测试剧",
        series_year="2026",
        season_number=1,
        episodes=tuple(EpisodeTarget(1, number, "2026-01-01") for number in range(1, 23)),
    )

    def resolution(url: str, episode: int, reviewed=()) -> LinkResolution:
        return LinkResolution(
            True,
            "ready",
            "ready",
            share_url=url,
            rename_pairs=(
                RenamePair(
                    f"source-{episode}.mkv",
                    f"source-{episode}\\.mkv",
                    f"测试剧.2026.S01E{episode:02d}.mkv",
                    episode_number=episode,
                ),
            ),
            reviewed_candidates=tuple(
                ResourceCandidate(item, provider="p115", cloud_type="115") for item in reviewed
            ),
        )

    resolver_calls = []

    def resolver(remaining_target, _previous_share_url, **kwargs):
        resolver_calls.append((remaining_target, kwargs))
        if len(resolver_calls) == 1:
            return resolution(links[0], 1, links[:20])

        candidates = tuple(kwargs.get("candidate_share_urls") or ())
        if candidates:
            assert len(candidates) == 1
            episode = links.index(candidates[0]) + 1
            return resolution(candidates[0], episode, candidates)

        assert kwargs["max_queries"] == 1
        assert tuple(query.keyword for query in build_search_queries(remaining_target, max_queries=1)) == ("测试剧",)
        assert [episode.episode_number for episode in remaining_target.episodes] == [21, 22]
        return resolution(links[20], 21, links[20:])

    class Provider:
        def __init__(self):
            self.calls = []

        def execute(self, plan):
            self.calls.append(plan.resolution.share_url)
            episode = plan.resolution.rename_pairs[0].episode_number
            return ProviderExecutionResult(
                True,
                "provider_completed",
                "done",
                executed_items=1,
                confirmed=True,
                outputs=({"file_name": f"测试剧.2026.S01E{episode:02d}.mkv"},),
            )

    provider = Provider()
    with (
        patch("app.services.transfer_service_v2.resolve_provider_key", return_value="p115"),
        patch("app.services.transfer_service_v2.get_transfer_provider", return_value=provider),
        patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
        patch("app.services.transfer_service_v2.resolve_save_path_progress", return_value=("/媒体库/测试剧/Season 1", 0)),
        patch("app.services.transfer_service_v2.resolve_episode_source", side_effect=resolver) as mocked_resolver,
    ):
        result = execute_transfer_v2(
            1,
            "tv",
            "cloud",
            1,
            tmdb=object(),
            pansou=object(),
            qas=object(),
            provider="p115",
        )

    assert result["ok"]
    assert provider.calls == list(links)
    assert mocked_resolver.call_count == 22
    assert sum(1 for _target, kwargs in resolver_calls if kwargs.get("max_queries") == 1) == 1
    assert len(result["resolution"]["rename_pairs"]) == 22
    assert len(result["execution"]["outputs"]) == 22


def test_verified_snapshot_uses_all_links_without_a_follow_up_search():
    links = ("https://115.com/s/e1", "https://115.com/s/e2")
    target = MediaTarget(
        1,
        "tv",
        "测试剧",
        season_number=1,
        episodes=(EpisodeTarget(1, 1, "2026-01-01"), EpisodeTarget(1, 2, "2026-01-01")),
    )

    def ready(url: str, episode: int) -> LinkResolution:
        return LinkResolution(
            True,
            "ready",
            "ready",
            share_url=url,
            rename_pairs=(RenamePair(
                f"source-{episode}.mkv",
                f"source-{episode}\\.mkv",
                f"测试剧.S01E{episode:02d}.mkv",
                episode_number=episode,
            ),),
        )

    resolver_calls = []

    def resolver(_target, previous, **kwargs):
        resolver_calls.append((previous, kwargs))
        if len(resolver_calls) == 1:
            assert tuple(previous) == links
            return ready(links[0], 1)
        assert kwargs["max_queries"] == 0
        assert tuple(kwargs["candidate_share_urls"]) == (links[1],)
        return ready(links[1], 2)

    class Provider:
        def execute(self, plan):
            episode = plan.resolution.rename_pairs[0].episode_number
            return ProviderExecutionResult(
                True,
                "provider_completed",
                "done",
                executed_items=1,
                confirmed=True,
                outputs=({"file_name": f"测试剧.S01E{episode:02d}.mkv"},),
            )

    with (
        patch("app.services.transfer_service_v2.resolve_provider_key", return_value="p115"),
        patch("app.services.transfer_service_v2.get_transfer_provider", return_value=Provider()),
        patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
        patch("app.services.transfer_service_v2.resolve_save_path_progress", return_value=("/媒体库/测试剧/Season 1", 0)),
        patch("app.services.transfer_service_v2.resolve_episode_source", side_effect=resolver),
    ):
        result = execute_transfer_v2(
            1,
            "tv",
            "cloud",
            1,
            preferred_share_urls=links,
            preferred_share_only=True,
            tmdb=object(),
            pansou=object(),
            qas=object(),
            provider="p115",
        )

    assert result["ok"]
    assert len(resolver_calls) == 2
