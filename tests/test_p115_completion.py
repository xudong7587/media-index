from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget, ProviderExecutionResult, RenamePair, SourceFile
from app.services.p115_completion import _native_search_target, _resolve_confirmed_tv_p115_source, complete_quark_to_p115
from app.services.share_inspector import ShareInspection


def completion_settings():
    return SimpleNamespace(
        openlist_enabled=True,
        openlist_auto_sync=True,
        openlist_auto_sync_direction="qas_to_p115",
        provider_save_root=lambda provider: "/quark" if provider == "quark" else "/115",
    )


def test_existing_exact_p115_files_skip_pansou_and_openlist():
    provider = Mock()
    provider.configured.return_value = True
    provider.reconcile.return_value = True
    with (
        patch("app.services.p115_completion.get_settings", return_value=completion_settings()),
        patch("app.services.p115_completion.get_transfer_provider", return_value=provider),
        patch("app.services.p115_completion._native_search_target") as build_target,
        patch("app.services.p115_completion.resolve_movie_source") as pansou_search,
        patch("app.services.p115_completion.sync_transfer_outputs") as openlist,
    ):
        result = complete_quark_to_p115(
            job_id=7,
            save_path="/quark/movie/已存在电影 (2026)",
            filenames=["已存在电影.2026.mkv"],
            tmdb_id=7,
            media_type="movie",
            title="已存在电影",
        )

    assert result.native_completed
    assert result.workflow_status == "done"
    assert result.remaining_filenames == ()
    provider.reconcile.assert_called_once_with("/115/movie/已存在电影 (2026)", ["已存在电影.2026.mkv"])
    build_target.assert_not_called()
    pansou_search.assert_not_called()
    openlist.assert_not_called()


def test_native_p115_complete_skips_openlist():
    target = MediaTarget(1, "movie", "测试电影", series_year="2026")
    resolution = LinkResolution(
        True,
        "ready",
        "matched",
        share_url="https://115.com/s/demo",
        rename_pairs=(RenamePair("source.mkv", "", "测试电影.2026.mkv"),),
    )
    provider = Mock()
    provider.configured.return_value = True
    provider.reconcile.return_value = False
    provider.execute.return_value = ProviderExecutionResult(
        True,
        "provider_completed",
        "done",
        confirmed=True,
        outputs=({"file_id": "115-1", "file_name": "测试电影.2026.2160p.mkv"},),
    )
    with (
        patch("app.services.p115_completion.get_settings", return_value=completion_settings()),
        patch("app.services.p115_completion.resolve_media_target", return_value=target),
        patch("app.services.p115_completion.get_transfer_provider", return_value=provider),
        patch("app.services.p115_completion.resolve_movie_source", return_value=resolution),
        patch("app.services.p115_completion.sync_transfer_outputs") as openlist,
        patch("app.services.p115_completion.run_confirmed_native_transfer_post_processing", return_value=True) as post,
    ):
        result = complete_quark_to_p115(
            job_id=8,
            save_path="/quark/movie/测试电影 (2026)",
            filenames=["测试电影.2026.mkv"],
            tmdb_id=1,
            media_type="movie",
            title="测试电影",
        )

    assert result.native_completed
    assert result.workflow_status == "done"
    openlist.assert_not_called()
    assert provider.execute.call_args.args[0].save_path == "/115/movie/测试电影 (2026)"
    post.assert_called_once()


def test_no_safe_p115_candidate_falls_back_to_exact_openlist_files():
    target = MediaTarget(2, "movie", "无资源电影", series_year="2026")
    provider = Mock()
    provider.configured.return_value = True
    provider.reconcile.return_value = False
    with (
        patch("app.services.p115_completion.get_settings", return_value=completion_settings()),
        patch("app.services.p115_completion.resolve_media_target", return_value=target),
        patch("app.services.p115_completion.get_transfer_provider", return_value=provider),
        patch(
            "app.services.p115_completion.resolve_movie_source",
            return_value=LinkResolution(False, "no_resource", "none"),
        ),
        patch(
            "app.services.p115_completion.sync_transfer_outputs",
            return_value=[{"ok": True, "job_id": 12, "landed": 1}],
        ) as openlist,
    ):
        result = complete_quark_to_p115(
            job_id=9,
            save_path="/quark/movie/无资源电影 (2026)",
            filenames=["无资源电影.2026.mkv"],
            tmdb_id=2,
            media_type="movie",
            title="无资源电影",
        )

    assert result.workflow_status == "done"
    openlist.assert_called_once_with(
        "quark",
        "/quark/movie/无资源电影 (2026)",
        ["无资源电影.2026.mkv"],
        tmdb_id=2,
        media_type="movie",
        season_number=None,
        display_title="无资源电影",
        target_providers=("p115",),
    )


def test_partial_native_p115_uses_openlist_only_for_remaining_episode():
    episodes = (EpisodeTarget(1, 1), EpisodeTarget(1, 2))
    target = MediaTarget(3, "tv", "测试剧", season_number=1, episodes=episodes)
    resolution = LinkResolution(
        True,
        "ready",
        "partial",
        share_url="https://115.com/s/partial",
        rename_pairs=(
            RenamePair("one.mkv", "", "测试剧.S01E01.mkv", episode_number=1, episode_numbers=(1,)),
        ),
    )
    provider = Mock()
    provider.configured.return_value = True
    provider.reconcile.return_value = False
    provider.execute.return_value = ProviderExecutionResult(
        True,
        "provider_completed",
        "done",
        confirmed=True,
        outputs=({"file_id": "115-1", "file_name": "测试剧.S01E01.mkv"},),
    )
    with (
        patch("app.services.p115_completion.get_settings", return_value=completion_settings()),
        patch("app.services.p115_completion.resolve_media_target", return_value=target),
        patch("app.services.p115_completion.get_transfer_provider", return_value=provider),
        patch("app.services.p115_completion.resolve_episode_source", return_value=resolution),
        patch(
            "app.services.p115_completion.sync_transfer_outputs",
            return_value=[{"ok": True, "job_id": 13, "landed": 1}],
        ) as openlist,
        patch("app.services.p115_completion.run_confirmed_native_transfer_post_processing", return_value=True),
    ):
        result = complete_quark_to_p115(
            job_id=10,
            save_path="/quark/tv/测试剧/Season 1",
            filenames=["测试剧.S01E01.mkv", "测试剧.S01E02.mkv"],
            tmdb_id=3,
            media_type="tv",
            season_number=1,
            title="测试剧",
        )

    assert result.remaining_filenames == ("测试剧.S01E02.mkv",)
    assert result.workflow_status == "done"
    assert openlist.call_args.args[2] == ["测试剧.S01E02.mkv"]


def test_organized_p115_search_can_cover_all_aired_episodes_not_only_quark_files():
    target = MediaTarget(
        31,
        "tv",
        "测试剧",
        season_number=1,
        episodes=(
            EpisodeTarget(1, 1, "2026-01-01"),
            EpisodeTarget(1, 2, "2026-01-02"),
            EpisodeTarget(1, 3, "2099-01-01"),
        ),
    )
    with patch("app.services.p115_completion.resolve_media_target", return_value=target):
        resolved = _native_search_target(
            tmdb_id=31,
            media_type="tv",
            season_number=1,
            title="测试剧",
            year="2026",
            category="tv",
            filenames=("测试剧.S01E01.mkv",),
            supplement_missing_episodes=True,
        )

    assert resolved is not None
    assert [episode.episode_number for episode in resolved.episodes] == [1, 2]


def test_organized_p115_search_recovers_missing_season_from_verified_filenames():
    target = MediaTarget(
        276161,
        "tv",
        "铁拳教育",
        season_number=1,
        episodes=tuple(EpisodeTarget(1, number, "2026-08-01") for number in range(1, 11)),
    )
    with patch("app.services.p115_completion.resolve_media_target", return_value=target) as resolve:
        resolved = _native_search_target(
            tmdb_id=276161,
            media_type="tv",
            season_number=None,
            title="铁拳教育",
            year="2026",
            category="tv",
            filenames=tuple(f"铁拳教育.2026.S01E{number:02d}.mp4" for number in range(1, 11)),
            supplement_missing_episodes=True,
        )

    assert resolved == target
    assert [episode.episode_number for episode in resolved.episodes] == list(range(1, 11))
    assert resolve.call_args.args[2] == 1


def test_confirmed_tv_p115_search_uses_title_once_without_candidate_title_recheck():
    target = MediaTarget(
        276161,
        "tv",
        "铁拳教育",
        season_number=1,
        episodes=(EpisodeTarget(1, 1), EpisodeTarget(1, 2)),
    )
    provider = Mock()
    provider.inspect_share.return_value = ShareInspection(
        True,
        "https://115.com/s/usable",
        (
            SourceFile("发布组A.S01E01.mkv", 100, "/发布组A.S01E01.mkv", "1", "0"),
            SourceFile("发布组B.S01E02.mkv", 100, "/发布组B.S01E02.mkv", "2", "0"),
        ),
    )
    pansou = Mock()
    pansou.search_detailed.return_value = SimpleNamespace(
        items=[
            {
                "title": "完全不可信的网盘发布名",
                "share_url": "https://115.com/s/usable",
                "cloud_type": "115",
            }
        ],
        error="",
    )

    with (
        patch("app.services.p115_completion.PansouClient", return_value=pansou),
        patch("app.services.p115_completion.get_settings", return_value=SimpleNamespace(pansou_search_timeout_seconds=45)),
    ):
        result = _resolve_confirmed_tv_p115_source(target, provider)

    assert result.ok
    assert [pair.replacement for pair in result.rename_pairs] == [
        "铁拳教育.S01E01.mkv",
        "铁拳教育.S01E02.mkv",
    ]
    pansou.search_detailed.assert_called_once_with(
        "铁拳教育",
        limit=100,
        timeout=45,
        result_mode="all",
    )
