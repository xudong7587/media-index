from unittest.mock import Mock, patch
from urllib.parse import urlencode

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.transfers import TransferBatchCreate, TransferBatchItem, create_transfer_batch, _job_cloud_download_child, _run_transfer_job, _sync_openlist_for_batch
from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import MediaTarget, EpisodeTarget, LinkResolution, ProviderExecutionResult
from app.services.transfer_service_v2 import execute_transfer_v2
from app.services.cloud_download_targets import CloudDownloadTarget
from app.services.discovery_source import resolve_discovery_source
from app.services.movie_resolver import resolve_movie_source
from app.clients.pansou import PansouSearchResponse

def magnet(number, title):
    return "magnet:?" + urlencode({"xt": f"urn:btih:{number:040x}", "dn": title})


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("QUARK_COOKIE", "__puus=test")
    monkeypatch.setenv("P115_COOKIE", "UID=1_A1_1; CID=test; SEID=test")
    monkeypatch.setenv("ENABLED_CLOUD_PROVIDERS", "quark,p115")
    monkeypatch.setenv("P115_CLOUD_DOWNLOAD_PATH", "/Downloads")
    monkeypatch.setenv("QUARK_CLOUD_DOWNLOAD_PATH", "/QuarkDownloads")
    get_settings.cache_clear()
    init_db()
    yield
    get_settings.cache_clear()


def test_somersault_without_release_year_selects_one_magnet_without_quark_inspection():
    target = MediaTarget(16605, "movie", "生命翻筋斗", original_title="Somersault", series_year="2004")
    selected = magnet(1, "生命翻筋斗 Somersault")
    search = Mock()
    search.search_detailed.return_value = PansouSearchResponse(target.title, [
        {"title": "生命翻筋斗 (2004)", "share_url": "https://pan.quark.cn/s/example"},
        {"title": "生命翻筋斗 Somersault", "share_url": selected, "provider": "p115", "cloud_type": "115"},
        {"title": "生命翻筋斗 2005 4K", "share_url": magnet(2, "生命翻筋斗 2005 4K")},
    ])
    cloud = Mock(key="p115")
    result = resolve_discovery_source(resolve_movie_source, target, allow_magnets=True, qas=cloud,
                                      pansou=search, max_queries=1, provider_filter="p115")
    assert result.stage == "cloud_download_ready" and result.share_url == selected
    cloud.inspect_share.assert_not_called()


@pytest.mark.parametrize("child", ["../16其他电影", "16其他电影/子目录", "不存在"])
def test_invalid_destination_creates_no_batch_or_job(isolated_db, child):
    payload = TransferBatchCreate(tmdb_id=1, media_type="movie", items=[TransferBatchItem(provider="p115", cloud_download_child=child)])
    with patch("app.services.cloud_download_targets.list_cloud_download_targets", return_value=[CloudDownloadTarget("p115", "16其他电影", "/Downloads/16其他电影")]):
        with pytest.raises(HTTPException) as caught:
            create_transfer_batch(payload, BackgroundTasks())
    assert caught.value.status_code == 422
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM transfer_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM transfer_batches").fetchone()[0] == 0


def test_batch_persists_each_provider_destination_and_keeps_old_callers(isolated_db):
    payload = TransferBatchCreate(tmdb_id=1, media_type="movie", items=[
        TransferBatchItem(provider="p115", cloud_download_child="16其他电影"),
        TransferBatchItem(provider="quark", cloud_download_child="02系列电影"),
    ])
    def choices(key):
        child = "16其他电影" if key == "p115" else "02系列电影"
        return [CloudDownloadTarget(key, child, "/Downloads/" + child)]
    background = BackgroundTasks()
    with patch("app.services.cloud_download_targets.list_cloud_download_targets", side_effect=choices):
        result = create_transfer_batch(payload, background)
    jobs = background.tasks[0].args[1]
    assert len(result["child_ids"]) == 2
    assert [_job_cloud_download_child(job_id, child) for child, job_id, _duplicate in jobs] == ["16其他电影", "02系列电影"]
    assert all(child.request_source == "discover" for child, _job_id, _duplicate in jobs)
    legacy = create_transfer_batch(TransferBatchCreate(tmdb_id=2, media_type="movie", items=[TransferBatchItem(provider="p115")]), BackgroundTasks())
    with db() as conn:
        row = conn.execute("SELECT request_source,execution_key FROM transfer_jobs WHERE id=?", (legacy["child_ids"][0],)).fetchone()
    assert row["request_source"] == "" and "cloud-download:" not in row["execution_key"]


def test_stale_persisted_destination_fails_before_transfer_execution(isolated_db):
    background = BackgroundTasks()
    with patch("app.services.cloud_download_targets.list_cloud_download_targets", return_value=[CloudDownloadTarget("p115", "16其他电影", "/Downloads/16其他电影")]):
        create_transfer_batch(TransferBatchCreate(tmdb_id=1, media_type="movie", items=[TransferBatchItem(provider="p115", cloud_download_child="16其他电影")]), background)
    child, job_id, _duplicate = background.tasks[0].args[1][0]
    with patch("app.api.transfers.resolve_interaction_cloud_download_child", return_value=""), patch("app.api.transfers.execute_transfer_v2") as execute:
        _run_transfer_job(child, job_id)
    execute.assert_not_called()
    with db() as conn:
        row = conn.execute("SELECT status,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "failed" and "目录已失效" in row["message"]


@pytest.mark.parametrize("kind,season", [("movie", None), ("tv", 1)])
def test_discovery_native_transfer_uses_selected_staging_path(isolated_db, kind, season):
    target = MediaTarget(1, kind, "作品", series_year="2026", category=kind,
                         season_number=season, episodes=(EpisodeTarget(1, 1),) if season else ())
    cloud = Mock(key="p115")
    cloud.execute.return_value = ProviderExecutionResult(True, "provider_completed", "done")
    with (patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
          patch("app.services.transfer_service_v2.get_transfer_provider", return_value=cloud),
          patch("app.services.transfer_service_v2.resolve_discovery_source", return_value=LinkResolution(True, "ready", "verified", share_url="https://115.com/s/example")),
          patch("app.services.transfer_service_v2.resolve_save_path_progress", side_effect=lambda path, *_args, **_kwargs: (path, 0))):
        result = execute_transfer_v2(1, kind, "cloud", season, provider="p115", request_source="discover",
                                     interaction_cloud_download_child="16其他电影", preferred_share_urls=("https://115.com/s/example",), preferred_share_only=True)
    plan = cloud.execute.call_args.args[0]
    assert result["ok"] and plan.save_path.startswith("/Downloads/16其他电影/作品 (2026)")
    assert plan.destination_scope == "cloud_download" and plan.cloud_download_child == "16其他电影"


def test_batch_never_uses_download_staging_as_p115_completion_source(isolated_db):
    with patch("app.services.cloud_download_targets.list_cloud_download_targets", return_value=[CloudDownloadTarget("quark", "16其他电影", "/QuarkDownloads/16其他电影")]):
        batch = create_transfer_batch(TransferBatchCreate(tmdb_id=1, media_type="movie", items=[TransferBatchItem(provider="quark", cloud_download_child="16其他电影", openlist_fallback_to_p115=True)]), BackgroundTasks())
    with db() as conn:
        conn.execute("UPDATE transfer_jobs SET status='done',save_path='/QuarkDownloads/16其他电影/作品' WHERE id=?", (batch["child_ids"][0],))
    with patch("app.api.transfers.complete_quark_to_p115") as completion, patch("app.api.transfers.sync_transfer_outputs") as sync:
        _sync_openlist_for_batch(batch["id"])
    completion.assert_not_called()
    sync.assert_not_called()
