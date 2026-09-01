from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget, ProviderExecutionResult, RenamePair
from app.services.p115_completion import complete_quark_to_p115


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
