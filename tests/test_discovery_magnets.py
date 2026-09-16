from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import pytest

from app.clients.pansou import PansouSearchResponse, normalize_pansou_results, infer_share_provider
from app.domain.magnet import magnet_key
from app.domain.media import MediaTarget, SourceFile, ProviderExecutionResult
from app.services.discovery_source import resolve_discovery_source
from app.services.movie_resolver import resolve_movie_source
from app.services.share_inspector import ShareInspection
from app.services.quality_priority import quality_priority_score
from app.services.resource_probe import _transfer_share_urls
from app.services.transfer_service_v2 import execute_transfer_v2


TARGET = MediaTarget(1, "movie", "Film", original_title="Film", series_year="2026", category="movie")
SHARE = "https://115.com/s/valid"


def magnet(number, title="Film.2026.1080p.WEB-DL"):
    return "magnet:?" + urlencode({"xt": f"urn:btih:{number:040x}", "dn": title})


def item(number, title="Film.2026.1080p.WEB-DL"):
    return {"share_url": magnet(number, title), "title": title, "provider": "p115", "cloud_type": "115"}


def provider(valid=False):
    cloud = Mock(key="p115")
    cloud.inspect_share.side_effect = lambda url: ShareInspection(
        valid, url, (SourceFile("Film.2026.mkv", 2_000_000_000, provider_file_id="file"),) if valid else (),
        error="" if valid else "分享已过期")
    return cloud


def resolve(items, cloud=None, urls=(), **options):
    pansou = Mock()
    pansou.search_detailed.return_value = PansouSearchResponse("Film", items)
    result = resolve_discovery_source(resolve_movie_source, TARGET, urls, allow_magnets=True,
                                      qas=cloud or provider(), pansou=pansou, max_queries=1,
                                      provider_filter="p115", **options)
    return result, pansou


def test_raw_and_merged_magnets_are_115_candidates_without_becoming_native_shares():
    url = magnet(1).split("&dn=")[0]
    results = normalize_pansou_results({"data": {"results": [
        {"title": "Film.2026.2160p", "links": [{"type": "magnet", "url": url}]}],
        "merged_by_type": {"magnet": [{"url": url}], "115": [{"url": SHARE}]}}}, 50)
    assert len(results) == 2
    assert results[0]["provider"] == "p115"
    assert results[0]["resource_kind"] == "magnet"
    assert "dn=" in results[0]["share_url"]
    assert infer_share_provider(results[0]["share_url"]) == ("", "")
    assert magnet_key(results[0]["share_url"]) == f"{1:040x}"


def test_expired_shares_fall_back_to_best_quality_in_large_magnet_pool():
    items = [{"share_url": SHARE, "title": "Film.2026", "provider": "p115", "cloud_type": "115"}]
    items += [item(number) for number in range(1, 120)]
    items += [item(900, "Film.2026.2160p.REMUX"), item(901, "Film.2026.4K.CAM")]
    cloud = provider()
    result, pansou = resolve(items, cloud)
    assert result.stage == "cloud_download_ready"
    assert result.share_url == magnet(900, "Film.2026.2160p.REMUX")
    assert cloud.inspect_share.call_args_list[0].args == (SHARE,)
    assert pansou.search_detailed.call_args.kwargs["limit"] == 1000
    assert pansou.search_detailed.call_args.args[0] == "Film"
    assert all("CAM" not in candidate.title for candidate in result.reviewed_candidates if not candidate.rejected)
    assert SHARE not in _transfer_share_urls(result, tuple(items), "p115")


def test_verified_native_share_wins_over_higher_quality_magnet():
    cloud = provider(True)
    result, _ = resolve([{"share_url": SHARE, "title": "Film.2026", "cloud_type": "115", "provider": "p115"},
                         item(5, "Film.2026.2160p.REMUX")], cloud)
    assert result.stage == "ready"
    assert result.share_url == SHARE
    assert any("cloud_download_candidate" in candidate.reasons for candidate in result.reviewed_candidates)


def test_frozen_native_list_checks_next_link_instead_of_stopping_at_expired_first():
    cloud = provider()
    cloud.inspect_share.side_effect = [ShareInspection(False, SHARE, error="expired"),
                                      ShareInspection(True, SHARE + "2", (SourceFile("Film.2026.mkv", 2_000_000_000),))]
    result = resolve_movie_source(TARGET, (SHARE, SHARE + "2"), qas=cloud, max_queries=0, provider_filter="p115")
    assert result.ok and result.share_url == SHARE + "2"
    assert cloud.inspect_share.call_count == 2


@pytest.mark.parametrize("title", ["Other.2026.4K", "Film.2025.4K", "Film.4K", "Film.2026.TS"])
def test_unproven_or_excluded_magnets_never_become_automatic_downloads(title):
    result, _ = resolve([item(1, title)])
    assert not result.ok


def test_explicit_magnet_snapshot_needs_no_new_search_or_share_inspection():
    cloud = provider()
    search = Mock()
    result = resolve_discovery_source(resolve_movie_source, TARGET, (magnet(1),), allow_magnets=True,
                                      qas=cloud, pansou=search, max_queries=0, provider_filter="p115")
    assert result.stage == "cloud_download_ready"
    cloud.inspect_share.assert_not_called()
    search.search_detailed.assert_not_called()


def test_compound_quality_keywords_require_resolution_and_match_separated_features():
    assert quality_priority_score("Film.2160p.BluRay.REMUX") > quality_priority_score("Film.2160p.DV")
    assert quality_priority_score("Film.2160p.DV") > quality_priority_score("Film.1080p.DV")
    assert quality_priority_score("Film.2160p.HDR") > quality_priority_score("Film.2160p.SDR")


@pytest.mark.parametrize("failed_stage, expected", [("provider_failed", "cloud_download_ready"), ("provider_partial", "provider_partial")])
def test_execution_time_expiry_falls_back_only_when_no_write_was_accepted(failed_stage, expected):
    cloud = provider(True)
    cloud.execute.return_value = ProviderExecutionResult(False, failed_stage, "分享已过期")
    search = Mock()
    search.search_detailed.return_value = PansouSearchResponse("Film", [item(1)])
    with (patch("app.services.transfer_service_v2.resolve_media_target", return_value=TARGET),
          patch("app.services.transfer_service_v2.get_transfer_provider", return_value=cloud),
          patch("app.services.transfer_service_v2.resolve_provider_key", return_value="p115"),
          patch("app.services.transfer_service_v2.build_save_path", return_value="/library/Film (2026)")):
        result = execute_transfer_v2(1, "movie", "cloud", preferred_share_urls=(SHARE, magnet(1)),
                                     preferred_share_only=True, pansou=search, provider="p115", request_source="discover")
    assert result["stage"] == expected
    assert cloud.execute.call_count == 1


def test_quark_does_not_enable_magnet_fallback():
    resolver = Mock(return_value="native-result")
    assert resolve_discovery_source(resolver, TARGET, (), allow_magnets=False) == "native-result"
    resolver.assert_called_once_with(TARGET, ())


@pytest.mark.parametrize("status", ["running", "stopped"])
@pytest.mark.parametrize("category,child", [("movie", "01电影"), ("tv", "03电视剧")])
def test_discovery_submission_reuses_job_and_preserves_identity_or_honors_stop(status, category, child):
    import sqlite3
    from app.core.config import Settings
    from app.services.direct_link_transfer import submit_discovery_cloud_download

    settings = Settings(
        _env_file=None, p115_root_path="/媒体库", p115_cloud_download_path="/媒体库/下载文件夹",
        p115_category_paths_json='{"movie":"/01电影","tv":"/03电视剧"}',
    )
    client = Mock()
    client.directory_id.return_value = "downloads"
    client.list_directory_complete.return_value = [SimpleNamespace(name=child, is_dir=True)]
    submit = client.add_cloud_download
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE transfer_jobs (id INTEGER, status TEXT, share_url TEXT, save_path TEXT, stage TEXT)")
    connection.execute("INSERT INTO transfer_jobs (id,status) VALUES (7,?)", (status,))
    try:
        with (
            patch("app.services.direct_link_transfer.db", return_value=connection),
            patch("app.services.direct_link_transfer.get_settings", return_value=settings),
            patch("app.services.cloud_download_targets.get_settings", return_value=settings),
            patch("app.services.cloud_download_targets.P115Client", return_value=client),
            patch("app.services.direct_link_transfer.P115Client", return_value=client),
            patch("app.services.direct_link_transfer.record_diagnostic_event"),
            patch("app.services.direct_link_transfer._finish_p115_cloud_download_job") as finish,
        ):
            result = submit_discovery_cloud_download(7, {"tmdb_id": 42, "title": "Film", "series_year": "2026", "category": category}, magnet(1))
        client.directory_id.assert_called_once_with("/媒体库/下载文件夹")
        client.list_directory_complete.assert_called_once_with("downloads")
        assert connection.execute("SELECT COUNT(*) FROM transfer_jobs").fetchone()[0] == 1
        if status == "stopped":
            assert not result.ok
            submit.assert_not_called()
            finish.assert_not_called()
        else:
            path = f"/媒体库/下载文件夹/{child}/Film (2026)"
            submit.assert_called_once_with(magnet(1), path)
            finish.assert_called_once_with(7, submit.return_value, path, title="Film", year="2026", tmdb_id=42)
            row = connection.execute("SELECT * FROM transfer_jobs WHERE id=7").fetchone()
            assert row["share_url"] == magnet(1) and row["save_path"] == path
    finally:
        connection.close()


@pytest.mark.parametrize("path", [
    "/媒体库/下载文件夹",
    "/媒体库/下载文件夹/01电影/另一个影片",
    "/媒体库/01电影",
    "/媒体库/下载文件夹外/01电影",
    "/媒体库/下载文件夹/../01电影",
])
def test_discovery_magnet_rejects_invalid_category_scope_before_submission(path):
    from app.core.config import Settings
    from app.services.direct_link_transfer import submit_discovery_cloud_download

    settings = Settings(
        _env_file=None, p115_root_path="/媒体库", p115_cloud_download_path="/媒体库/下载文件夹",
        p115_category_paths_json='{"movie":"/01电影"}',
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer.list_cloud_download_targets", return_value=[
            SimpleNamespace(child_name="01电影", path=path)]),
        patch("app.services.direct_link_transfer.db") as database,
        patch("app.services.direct_link_transfer.P115Client") as client,
    ):
        with pytest.raises(ValueError):
            submit_discovery_cloud_download(7, {"tmdb_id": 42, "title": "Film", "series_year": "2026", "category": "movie"}, magnet(1))
    database.assert_not_called()
    client.assert_not_called()
