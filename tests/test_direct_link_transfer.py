from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.clients.p115 import P115CloudDownloadResult, P115Error
from app.domain.media import SourceFile
from app.services.direct_link_transfer import (
    DirectLinkRequest,
    _direct_target_options,
    _mark_direct_qas_triggered,
    _provider_child_directories,
    _resolve_direct_year,
    _transfer_qas_share_with_files,
    _transfer_p115_cloud_download,
    extract_download_link,
    handle_direct_link_transfer,
    looks_like_download_link,
    prepare_direct_link_request,
)
from app.services.share_inspector import ShareInspection


def test_extracts_direct_download_links():
    assert looks_like_download_link("转存 magnet:?xt=urn:btih:abcdef")
    assert extract_download_link("请保存 https://115cdn.com/s/demo?password=123") == "https://115cdn.com/s/demo?password=123"


def test_direct_download_disabled_does_not_fall_through_as_resource():
    settings = SimpleNamespace(direct_download_enabled=False)
    with patch("app.services.direct_link_transfer.get_settings", return_value=settings):
        result = handle_direct_link_transfer("magnet:?xt=urn:btih:abcdef", "Sunny")
    assert not result.ok
    assert "尚未启用" in result.message


def test_offline_link_uses_115_even_when_legacy_setting_is_qas():
    settings = SimpleNamespace(
        direct_download_enabled=True,
        direct_download_provider="qas",
        direct_download_save_path="/strm/downloads",
        default_provider_key=lambda: "qas",
        provider_save_root=lambda provider: "/strm",
    )
    with patch("app.services.direct_link_transfer.get_settings", return_value=settings):
        request = prepare_direct_link_request("magnet:?xt=urn:btih:abcdef")
    assert request.provider == "p115"


def test_offline_link_submits_115_cloud_download_when_enabled():
    settings = SimpleNamespace(
        direct_download_enabled=True,
        direct_download_provider="p115",
        direct_download_save_path="/strm/downloads",
        default_provider_key=lambda: "p115",
        provider_save_root=lambda provider: "/strm",
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(42, False)),
        patch(
            "app.services.direct_link_transfer._transfer_p115_cloud_download",
            return_value=P115CloudDownloadResult({}, "123", "submitted", "115 已接受离线下载任务，仍在处理中"),
        ) as submit,
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer.add_notification"),
    ):
        result = handle_direct_link_transfer("magnet:?xt=urn:btih:abcdef", "Sunny")
    assert result.ok
    assert result.job_id == 42
    assert "后续进度请在 115 中查看" in result.message
    submit.assert_called_once_with("magnet:?xt=urn:btih:abcdef", "/strm/downloads")
    finish.assert_called_once_with(42, "done", "provider_submitted", result.message)


def test_offline_link_returns_done_when_115_reports_completed():
    settings = SimpleNamespace(
        direct_download_enabled=True,
        direct_download_provider="p115",
        direct_download_save_path="/strm/downloads",
        default_provider_key=lambda: "p115",
        provider_save_root=lambda provider: "/strm",
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(42, False)),
        patch(
            "app.services.direct_link_transfer._transfer_p115_cloud_download",
            return_value=P115CloudDownloadResult({}, "123", "done", "115 云下载已完成"),
        ),
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer.add_notification") as notify,
    ):
        result = handle_direct_link_transfer("magnet:?xt=urn:btih:abcdef", "Sunny")
    assert result.ok
    assert "云下载已完成" in result.message
    finish.assert_called_once_with(42, "done", "provider_completed", result.message)
    notify.assert_called_once()


def test_offline_link_failure_returns_actionable_115_message():
    settings = SimpleNamespace(
        direct_download_enabled=True,
        direct_download_provider="p115",
        direct_download_save_path="/strm/downloads",
        default_provider_key=lambda: "p115",
        provider_save_root=lambda provider: "/strm",
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(42, False)),
        patch(
            "app.services.direct_link_transfer._transfer_p115_cloud_download",
            side_effect=P115Error("115 离线下载任务提交失败：下载失败，含违规内容（错误码 50038）"),
        ),
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer.add_notification"),
    ):
        result = handle_direct_link_transfer("magnet:?xt=urn:btih:abcdef", "Sunny")
    assert not result.ok
    assert "含违规内容" in result.message
    assert "PermissionError" not in result.message
    finish.assert_called_once()


def test_qas_direct_transfer_waits_for_renamed_files_before_openlist_sync():
    request = DirectLinkRequest(
        link="https://pan.quark.cn/s/demo",
        provider="qas",
        root_path="/strm/tv/黑夜告白/Season 1",
        options=(),
        title="黑夜告白",
        year="2026",
        category="tv",
    )
    with (
        patch("app.services.direct_link_transfer.prepare_direct_link_request", return_value=request),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(57, False)) as create_job,
        patch(
            "app.services.direct_link_transfer._transfer_qas_share_with_files",
            return_value=(2, ["黑夜告白.2026.S01E01.mp4", "黑夜告白.2026.S01E02.mp4"]),
        ),
        patch("app.services.direct_link_transfer._mark_direct_qas_triggered") as mark_triggered,
        patch("app.services.direct_link_transfer._add_direct_notification"),
        patch("app.services.direct_link_transfer.infer_share_provider", return_value=("quark", "qas")),
        patch("app.services.qas_reconciler.request_qas_reconciliation"),
    ):
        result = handle_direct_link_transfer(
            request.link,
            "Sunny",
            request.root_path,
            "web",
            title=request.title,
            year=request.year,
            category=request.category,
        )

    assert result.ok
    assert "等待夸克完成改名" in result.message
    create_job.assert_called_once()
    mark_triggered.assert_called_once_with(57, ["黑夜告白.2026.S01E01.mp4", "黑夜告白.2026.S01E02.mp4"], result.message)


def test_qas_direct_transfer_tracks_expected_count_when_tv_pro_names_are_unknown():
    request = DirectLinkRequest(
        link="https://pan.quark.cn/s/demo",
        provider="qas",
        root_path="/strm/tv/榛戝鍛婄櫧/Season 1",
        options=(),
        title="榛戝鍛婄櫧",
        year="2026",
        category="tv",
    )
    with (
        patch("app.services.direct_link_transfer.prepare_direct_link_request", return_value=request),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(58, False)),
        patch("app.services.direct_link_transfer._transfer_qas_share_with_files", return_value=(27, [])),
        patch("app.services.direct_link_transfer._mark_direct_qas_triggered") as mark_triggered,
        patch("app.services.direct_link_transfer._add_direct_notification"),
        patch("app.services.direct_link_transfer.infer_share_provider", return_value=("quark", "qas")),
        patch("app.services.qas_reconciler.request_qas_reconciliation"),
    ):
        result = handle_direct_link_transfer(
            request.link,
            "Sunny",
            request.root_path,
            "web",
            title=request.title,
            year=request.year,
            category=request.category,
        )

    assert result.ok
    mark_triggered.assert_called_once_with(58, [], result.message, expected_count=27)


def test_offline_link_falls_back_to_openlist_when_p115_open_tls_fails():
    settings = SimpleNamespace(
        p115_auth_mode="open",
        openlist_url="https://openlist.internal",
        openlist_token="token",
        p115_root_path="/媒体库",
        openlist_p115_library_path="/115/媒体库",
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer.P115Client") as p115_client,
        patch("app.services.direct_link_transfer.OpenListClient") as openlist_client,
    ):
        p115_client.return_value.add_cloud_download.side_effect = P115Error("TLS EOF")
        openlist_client.return_value.p115_storage_path.return_value = "/115/下载文件夹"
        openlist_client.return_value.offline_download_115.return_value = {"code": 200, "message": "ok"}

        result = _transfer_p115_cloud_download("magnet:?xt=urn:btih:abcdef", "/下载文件夹")

    self_message = result.message
    assert result.status == "submitted"
    assert "OpenList" in self_message
    openlist_client.return_value.p115_storage_path.assert_called_once_with("/下载文件夹")
    openlist_client.return_value.offline_download_115.assert_called_once_with("/115/下载文件夹", "magnet:?xt=urn:btih:abcdef")


def test_direct_link_subfolders_fall_back_to_openlist_when_115_open_path_is_unavailable():
    settings = SimpleNamespace(
        p115_auth_mode="open",
        openlist_url="https://openlist.internal",
        openlist_token="token",
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer.P115Client") as p115_client,
        patch("app.services.direct_link_transfer.OpenListClient") as openlist_client,
    ):
        p115_client.return_value.directory_id.return_value = "0"
        openlist_client.return_value.p115_storage_path.return_value = "/115/媒体库/下载文件夹"
        openlist_client.return_value.list_directories.return_value = [{"name": "电影", "is_dir": True}, {"name": "剧集", "is_dir": True}]

        result = _provider_child_directories("p115", "/媒体库/下载文件夹")

    assert result == ["剧集", "电影"]
    openlist_client.return_value.p115_storage_path.assert_called_once_with("/媒体库/下载文件夹")
    openlist_client.return_value.list_directories.assert_called_once_with("/115/媒体库/下载文件夹")


def test_direct_link_target_prompt_uses_folder_names_not_full_paths():
    with patch("app.services.direct_link_transfer._provider_child_directories", return_value=["电影", "剧集"]):
        options = _direct_target_options("qas", "/夸克/下载链接")

    assert [item.label for item in options] == ["电影", "剧集"]
    assert [item.path for item in options] == ["/夸克/下载链接/电影", "/夸克/下载链接/剧集"]


def test_direct_link_with_media_name_offers_media_library_categories():
    with patch(
        "app.services.direct_link_transfer.build_save_path",
        side_effect=lambda target, media_type, title, year, provider, season=None: f"/{provider}/{media_type}/{title} ({year})" + (f"/Season {season}" if season else ""),
    ):
        with patch(
            "app.services.direct_link_transfer.get_settings",
            return_value=SimpleNamespace(season_subdirectory_enabled=True),
        ):
            options = _direct_target_options("qas", "/夸克/下载链接", title="黑夜告白", year="2026")

    assert [item.category for item in options] == ["movie", "tv", "variety", "concert", "documentary", "anime"]
    assert [item.label for item in options[:2]] == ["电影", "电视剧"]
    assert options[0].path == "/qas/movie/黑夜告白 (2026)"
    assert options[1].path == "/qas/tv/黑夜告白 (2026)/Season 1"


def test_direct_quark_multi_episode_uses_one_tv_pro_task():
    files = (
        SourceFile(name="01.4K.SDR.60fps.mkv", size=1, path="01.4K.SDR.60fps.mkv"),
        SourceFile(name="02.4K.SDR.60fps.mkv", size=1, path="02.4K.SDR.60fps.mkv"),
    )
    run_task = Mock(return_value={"success": True})
    client = SimpleNamespace(configured=lambda: True, run_task=run_task)
    with (
        patch("app.services.direct_link_transfer.QasClient", return_value=client),
        patch(
            "app.services.direct_link_transfer.inspect_share",
            return_value=ShareInspection(True, "https://pan.quark.cn/s/demo", files),
        ),
    ):
        count, filenames = _transfer_qas_share_with_files(
            "https://pan.quark.cn/s/demo",
            "/strm/01电视剧/黑夜告白 (2026)",
            title="黑夜告白",
            year="2026",
            category="tv",
        )

    assert count == 2
    assert filenames == ["黑夜告白.2026.S01E01.mkv", "黑夜告白.2026.S01E02.mkv"]
    run_task.assert_called_once()
    task = run_task.call_args.args[0]
    assert task["pattern"] == "$TV_PRO"
    assert task["taskname"] == "黑夜告白.2026"
    assert task["replace"] == "{TASKNAME}.{SXX}E{E}.{EXT}"


def test_direct_movie_multi_file_selects_quality_preference_and_renames_once():
    files = (
        SourceFile(name="Obsession.4K.mkv", size=12_000_000_000, path="Obsession.4K.mkv"),
        SourceFile(name="Obsession.1080p.mkv", size=5_000_000_000, path="Obsession.1080p.mkv"),
    )
    run_task = Mock(return_value={"success": True})
    client = SimpleNamespace(configured=lambda: True, run_task=run_task)
    settings = SimpleNamespace(
        quality_priority_keywords_json='["1080P", "4K"]',
        movie_naming_rule="{title}.{year}",
    )
    with (
        patch("app.services.direct_link_transfer.QasClient", return_value=client),
        patch(
            "app.services.direct_link_transfer.inspect_share",
            return_value=ShareInspection(True, "https://pan.quark.cn/s/demo", files),
        ),
        patch("app.services.episode_matcher.get_settings", return_value=settings),
        patch("app.services.movie_matcher.get_settings", return_value=settings),
    ):
        count, filenames = _transfer_qas_share_with_files(
            "https://pan.quark.cn/s/demo",
            "/strm/01/Obsession (2021)",
            title="Obsession",
            year="2021",
            category="movie",
        )

    assert count == 1
    assert filenames == ["Obsession.2021.mkv"]
    run_task.assert_called_once()
    task = run_task.call_args.args[0]
    assert task["pattern"] == "^Obsession\\.1080p\\.mkv$"
    assert task["replace"] == "Obsession.2021.mkv"


def test_direct_tv_pro_does_not_require_episode_tokens_for_tv_category():
    files = (
        SourceFile(name="part-a.mkv", size=1, path="part-a.mkv"),
        SourceFile(name="part-b.mkv", size=1, path="part-b.mkv"),
    )
    run_task = Mock(return_value={"success": True})
    client = SimpleNamespace(configured=lambda: True, run_task=run_task)
    with (
        patch("app.services.direct_link_transfer.QasClient", return_value=client),
        patch(
            "app.services.direct_link_transfer.inspect_share",
            return_value=ShareInspection(True, "https://pan.quark.cn/s/demo", files),
        ),
    ):
        _transfer_qas_share_with_files(
            "https://pan.quark.cn/s/demo",
            "/strm/03电视剧/黑夜告白 (2026)",
            title="黑夜告白",
            year="2026",
            category="tv",
        )

    run_task.assert_called_once()
    assert run_task.call_args.args[0]["pattern"] == "$TV_PRO"


def test_direct_variety_link_does_not_use_tv_pro_batch_magic():
    files = (
        SourceFile(name="01.mkv", size=1, path="01.mkv"),
        SourceFile(name="02.mkv", size=1, path="02.mkv"),
    )
    run_task = Mock(return_value={"success": True})
    client = SimpleNamespace(configured=lambda: True, run_task=run_task)
    with (
        patch("app.services.direct_link_transfer.QasClient", return_value=client),
        patch(
            "app.services.direct_link_transfer.inspect_share",
            return_value=ShareInspection(True, "https://pan.quark.cn/s/demo", files),
        ),
    ):
        _transfer_qas_share_with_files(
            "https://pan.quark.cn/s/demo",
            "/strm/02综艺/节目 (2026)",
            title="节目",
            year="2026",
            category="variety",
        )

    assert run_task.call_count == 2
    assert all(call.args[0]["pattern"] != "$TV_PRO" for call in run_task.call_args_list)


def test_direct_link_looks_up_missing_year_from_tmdb():
    settings = SimpleNamespace(
        direct_download_enabled=True,
        direct_download_provider="qas",
        default_provider_key=lambda: "qas",
        provider_save_root=lambda provider: "/strm",
        provider_category_paths=lambda provider: {"tv": "/03电视剧"},
        season_subdirectory_enabled=True,
        media_folder_naming_rule="{title} ({year})",
        season_folder_naming_rule="Season {season}",
        tmdb_api_key="configured",
    )
    tmdb = Mock()
    tmdb.configured.return_value = True
    tmdb.search.return_value = {"results": [{"title": "黑夜告白", "year": "2026"}]}
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.paths.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer.TmdbClient", return_value=tmdb),
    ):
        request = prepare_direct_link_request(
            "https://pan.quark.cn/s/demo",
            title="黑夜告白",
            category="tv",
        )

    assert request.year == "2026"
    assert request.root_path.endswith("/黑夜告白 (2026)/Season 1")
    tmdb.search.assert_called_once_with("黑夜告白", media_type="tv")


def test_direct_year_prefers_explicit_year_without_tmdb_lookup():
    with patch("app.services.direct_link_transfer.TmdbClient") as tmdb:
        assert _resolve_direct_year("黑夜告白", "2026", "tv") == "2026"
    tmdb.assert_not_called()
