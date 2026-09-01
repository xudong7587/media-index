from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.api.transfers import (
    DirectLinkRenamePreviewRequest,
    DirectLinkTransferCreate,
    create_direct_link_transfer,
    direct_link_rename_preview,
)
from app.clients.p115 import P115CloudDownloadResult, P115Error
from app.core.config import Settings
from app.domain.media import ProviderExecutionResult, RenamePair, SourceFile
from app.services.direct_link_transfer import (
    DirectLinkRenamePreview,
    DirectLinkRequest,
    DirectLinkTargetOption,
    _direct_execution_key,
    _direct_openlist_sync_message,
    _direct_target_options,
    _finish_p115_cloud_download_job,
    _mark_direct_qas_triggered,
    _provider_child_directories,
    _resolve_direct_year,
    _transfer_quark_share_with_files,
    _transfer_qas_share_with_files,
    _transfer_p115_cloud_download,
    _transfer_p115_share_with_files,
    _trigger_targeted_cloud_organizer,
    _validate_provider_path,
    extract_download_link,
    handle_direct_link_transfer,
    infer_direct_link_category,
    looks_like_download_link,
    prepare_direct_link_request,
    resolve_direct_link_resource_name,
)
from app.services.p115_completion import P115CompletionResult
from app.services.share_inspector import ShareInspection


def test_extracts_direct_download_links():
    assert looks_like_download_link("转存 magnet:?xt=urn:btih:abcdef")
    assert extract_download_link("请保存 https://115cdn.com/s/demo?password=123") == "https://115cdn.com/s/demo?password=123"


def test_quark_direct_link_auto_sync_targets_only_p115():
    settings = SimpleNamespace(openlist_enabled=True, openlist_auto_sync=True)
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch(
            "app.services.direct_link_transfer.complete_quark_to_p115",
            return_value=P115CompletionResult(True, True, True, (), (), "115 原生补齐完成 #81", "done"),
        ) as complete_p115,
    ):
        message = _direct_openlist_sync_message(
            "quark",
            "/quark/云下载/03电视剧",
            ["测试剧.S01E01.mkv"],
            category="tv",
            title="测试剧",
        )

    complete_p115.assert_called_once_with(
        job_id=0,
        save_path="/quark/云下载/03电视剧",
        filenames=["测试剧.S01E01.mkv"],
        media_type="tv",
        title="测试剧",
        year="",
        category="tv",
    )
    assert "#81" in message


def test_interaction_resource_name_uses_magnet_dn_and_ed2k_filename():
    assert resolve_direct_link_resource_name("magnet:?xt=urn:btih:abc&dn=黑夜告白.2026", "p115") == "黑夜告白.2026"
    assert resolve_direct_link_resource_name("ed2k://|file|黑夜告白%202026.mkv|123|hash|/", "p115") == "黑夜告白 2026.mkv"


def test_interactive_metadata_preserves_selected_cloud_download_subfolder():
    request = DirectLinkRequest(
        "magnet:?xt=urn:btih:abc",
        "p115",
        "/115/媒体库/黑夜告白 (2026)",
        (),
        title="黑夜告白",
        year="2026",
    )
    completed = P115CloudDownloadResult({}, "target", "submitted", "已提交")
    with (
        patch("app.services.direct_link_transfer.prepare_direct_link_request", return_value=request),
        patch("app.services.direct_link_transfer._validate_provider_path"),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(51, False)),
        patch("app.services.direct_link_transfer._transfer_p115_cloud_download", return_value=completed) as submit,
        patch("app.services.direct_link_transfer._finish_p115_cloud_download_job", return_value=Mock(ok=True, job_id=51, message="已提交")) as finish,
    ):
        result = handle_direct_link_transfer(
            request.link,
            "Sunny",
            save_path="/115/云下载/03电视剧",
            title="黑夜告白",
            year="2026",
            category="tv",
            preserve_save_path=True,
        )

    assert result.ok
    staging_path = "/115/云下载/03电视剧/黑夜告白 (2026)"
    submit.assert_called_once_with(request.link, staging_path)
    finish.assert_called_once_with(51, completed, staging_path, title="黑夜告白", year="2026")


def test_web_named_link_keeps_the_selected_cloud_download_child():
    request = DirectLinkRequest(
        "https://pan.quark.cn/s/demo",
        "quark",
        "/夸克/云下载",
        (
            DirectLinkTargetOption(
                "quark",
                "/夸克/云下载/03电视剧",
                "03电视剧",
                "tv",
            ),
        ),
        title="黑夜告白",
        year="2026",
        category="tv",
    )
    background = Mock()
    with patch("app.api.transfers.prepare_direct_link_request", return_value=request):
        result = create_direct_link_transfer(
            DirectLinkTransferCreate(
                link=request.link,
                save_path="/夸克/云下载/03电视剧",
                title="黑夜告白",
                year="2026",
                category="tv",
            ),
            background,
        )

    assert result["save_path"] == "/夸克/云下载/03电视剧"
    task_args = background.add_task.call_args.args
    assert task_args[2:6] == (
        "/夸克/云下载/03电视剧",
        "黑夜告白",
        "2026",
        "tv",
    )
    assert task_args[6:] == (True, True, False, "cloud_download")
    with patch("app.api.transfers.handle_direct_link_transfer") as transfer:
        task_args[0](*task_args[1:])
    assert transfer.call_args.kwargs["preserve_save_path"] is True
    assert transfer.call_args.args[2] == "/夸克/云下载/03电视剧"


def test_library_mode_uses_server_generated_path_without_cloud_child_selection():
    request = DirectLinkRequest(
        "https://pan.quark.cn/s/demo",
        "quark",
        "/夸克媒体/03电视剧/花开锦绣 (2026)/Season 1",
        (),
        title="花开锦绣",
        year="2026",
        category="tv",
    )
    background = Mock()
    with patch("app.api.transfers.prepare_direct_library_request", return_value=request):
        result = create_direct_link_transfer(
            DirectLinkTransferCreate(
                link=request.link,
                save_path="/不可信客户端路径",
                title=request.title,
                year=request.year,
                category=request.category,
                destination_mode="library",
                apply_rename_plan=True,
            ),
            background,
        )

    assert result["direct_link_contract_version"] == 2
    assert result["save_path"] == request.root_path
    assert result["destination_mode"] == "library"
    task_args = background.add_task.call_args.args
    assert task_args[2:6] == (request.root_path, request.title, request.year, request.category)
    assert task_args[6:] == (False, True, True, "library")


def test_rename_preview_endpoint_returns_contract_and_generated_names():
    preview = DirectLinkRenamePreview(
        link="https://pan.quark.cn/s/demo",
        provider="quark",
        save_path="/夸克媒体/03电视剧/花开锦绣 (2026)/Season 1",
        title="花开锦绣",
        year="2026",
        category="tv",
        pairs=(RenamePair("01.mkv", "^01\\.mkv$", "花开锦绣.2026.S01E01.mkv", confidence="high"),),
    )
    with patch("app.api.transfers.preview_direct_link_rename", return_value=preview):
        result = direct_link_rename_preview(
            DirectLinkRenamePreviewRequest(
                link=preview.link,
                title=preview.title,
                year=preview.year,
                category=preview.category,
            )
        )

    assert result["direct_link_contract_version"] == 2
    assert result["save_path"] == preview.save_path
    assert result["files"][0]["target_name"] == "花开锦绣.2026.S01E01.mkv"


def test_direct_library_transfer_runs_exact_strm_pipeline_without_cloud_organizer():
    request = DirectLinkRequest(
        "https://115.com/s/demo",
        "p115",
        "/115媒体/movie/流浪地球2 (2023)",
        (),
        title="流浪地球2",
        year="2023",
        category="movie",
    )
    outputs = ({"file_id": "p1", "file_name": "流浪地球2.2023.mkv", "path": request.root_path},)
    with (
        patch("app.services.direct_link_transfer.prepare_direct_library_request", return_value=request),
        patch("app.services.direct_link_transfer.is_allowed_save_path", return_value=True),
        patch("app.services.direct_link_transfer.infer_share_provider", return_value=("115", "p115")),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(91, False)),
        patch(
            "app.services.direct_link_transfer._transfer_p115_share_with_outputs",
            return_value=(1, ["流浪地球2.2023.mkv"], outputs),
        ),
        patch("app.services.direct_link_transfer._direct_openlist_sync_message", return_value=""),
        patch("app.services.direct_link_transfer.run_post_transfer_pipeline") as pipeline,
        patch("app.services.direct_link_transfer._trigger_targeted_cloud_organizer") as organizer,
        patch("app.services.direct_link_transfer.initialize_media_workflow"),
        patch("app.services.direct_link_transfer.complete_transfer_workflow_step"),
        patch("app.services.direct_link_transfer._finish_job"),
        patch("app.services.direct_link_transfer._add_direct_notification"),
    ):
        result = handle_direct_link_transfer(
            request.link,
            "Sunny",
            "/任意客户端路径",
            "browser-extension",
            title=request.title,
            year=request.year,
            category=request.category,
            destination_mode="library",
            apply_rename_plan=True,
        )

    assert result.ok
    organizer.assert_not_called()
    assert pipeline.call_args.kwargs["target_path"] == request.root_path
    assert pipeline.call_args.kwargs["target_files"] == outputs


def test_web_link_without_a_real_cloud_download_child_fails_closed():
    request = DirectLinkRequest(
        "https://pan.quark.cn/s/demo",
        "quark",
        "/夸克/云下载",
        (),
    )
    with patch("app.api.transfers.prepare_direct_link_request", return_value=request):
        with pytest.raises(HTTPException, match="暂无可用的直属子文件夹") as exc:
            create_direct_link_transfer(
                DirectLinkTransferCreate(link=request.link, save_path="/夸克/云下载"),
                Mock(),
            )

    assert exc.value.status_code == 422


def test_web_link_rejects_an_arbitrary_path_not_returned_by_current_options():
    request = DirectLinkRequest(
        "https://pan.quark.cn/s/demo",
        "quark",
        "/夸克/云下载",
        (DirectLinkTargetOption("quark", "/夸克/云下载/01电影", "01电影", "movie"),),
    )
    with patch("app.api.transfers.prepare_direct_link_request", return_value=request):
        with pytest.raises(HTTPException, match="请选择当前云下载路径") as exc:
            create_direct_link_transfer(
                DirectLinkTransferCreate(link=request.link, save_path="/夸克/云下载/任意目录"),
                Mock(),
            )

    assert exc.value.status_code == 422


def test_interactive_download_link_remains_available_with_legacy_toggle_disabled():
    settings = SimpleNamespace(
        direct_download_enabled=False,
        direct_download_provider="p115",
        direct_download_save_path="/strm/downloads",
        default_provider_key=lambda: "p115",
        provider_save_root=lambda provider: "/strm",
    )
    with patch("app.services.direct_link_transfer.get_settings", return_value=settings):
        request = prepare_direct_link_request("magnet:?xt=urn:btih:abcdef")
    assert request.provider == "p115"
    assert request.root_path == "/strm"


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


def test_link_types_use_their_provider_cloud_download_directories():
    settings = Settings(
        direct_download_provider="p115",
        p115_root_path="/115媒体",
        p115_cloud_download_path="/115媒体/云下载",
        quark_root_path="/夸克媒体",
        quark_cloud_download_path="/夸克媒体/云下载",
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer._provider_child_directories", return_value=[]),
    ):
        quark = prepare_direct_link_request("https://pan.quark.cn/s/demo")
        p115 = prepare_direct_link_request("https://115.com/s/demo")
        magnet = prepare_direct_link_request("magnet:?xt=urn:btih:abcdef")

    assert (quark.provider, quark.root_path) == ("quark", "/夸克媒体/云下载")
    assert (p115.provider, p115.root_path) == ("p115", "/115媒体/云下载")
    assert (magnet.provider, magnet.root_path) == ("p115", "/115媒体/云下载")


def test_download_child_category_prefers_unique_saved_provider_path():
    settings = Settings(quark_category_paths_json='{"tv":"/自定义连续剧"}')
    with patch("app.services.direct_link_transfer.get_settings", return_value=settings):
        assert infer_direct_link_category("quark", "自定义连续剧") == "tv"
        assert infer_direct_link_category("quark", "03电视剧") == "tv"


def test_direct_job_rename_metadata_has_a_distinct_normalized_execution_key():
    base = ("magnet:?xt=urn:btih:abc", "p115", "/115/云下载/03电视剧")
    plain = _direct_execution_key(*base)
    renamed = _direct_execution_key(*base, title="  黑夜告白  ", year="2026", category="tv")
    normalized = _direct_execution_key(*base, title="黑夜告白", year="2026", category="TV")

    assert plain != renamed
    assert renamed == normalized


def test_quark_numeric_choice_transfers_all_video_files_with_original_names():
    sources = (
        SourceFile("01.mkv", 10, "/01.mkv", "q1"),
        SourceFile("02.mp4", 20, "/02.mp4", "q2"),
        SourceFile("02.zh.srt", 2, "/02.zh.srt", "q3"),
    )
    provider = Mock()
    provider.configured.return_value = True
    provider.inspect_share.return_value = ShareInspection(True, "https://pan.quark.cn/s/demo", sources)
    provider.execute.return_value = ProviderExecutionResult(
        True,
        "provider_completed",
        "done",
        executed_items=3,
        confirmed=True,
        outputs=(
            {"file_id": "q1", "file_name": "01.mkv", "path": "/quark/云下载/03电视剧"},
            {"file_id": "q2", "file_name": "02.mp4", "path": "/quark/云下载/03电视剧"},
            {"file_id": "q3", "file_name": "02.zh.srt", "path": "/quark/云下载/03电视剧"},
        ),
    )
    with (
        patch(
            "app.services.direct_link_transfer.get_settings",
            return_value=Settings(quark_cloud_download_path="/quark/云下载"),
        ),
        patch("app.services.direct_link_transfer.QuarkClient"),
        patch("app.services.direct_link_transfer.QuarkTransferProvider", return_value=provider),
    ):
        count, names, _outputs = _transfer_quark_share_with_files(
            "https://pan.quark.cn/s/demo",
            "/quark/云下载/03电视剧",
            category="tv",
        )

    plan = provider.execute.call_args.args[0]
    assert (count, names) == (3, ["01.mkv", "02.mp4", "02.zh.srt"])
    assert [pair.replacement for pair in plan.resolution.rename_pairs] == ["01.mkv", "02.mp4", "02.zh.srt"]
    assert plan.save_path == "/quark/云下载/03电视剧"
    assert (plan.destination_scope, plan.cloud_download_child) == ("cloud_download", "03电视剧")


@pytest.mark.parametrize("category", ["movie", "concert", "documentary"])
def test_quark_named_film_categories_use_movie_naming(category):
    source = SourceFile("Source.2026.1080p.mkv", 100, "/Source.2026.1080p.mkv", "q1")
    provider = Mock()
    provider.configured.return_value = True
    provider.inspect_share.return_value = ShareInspection(True, "https://pan.quark.cn/s/demo", (source,))
    provider.execute.return_value = ProviderExecutionResult(
        True,
        "provider_completed",
        "done",
        executed_items=1,
        confirmed=True,
        outputs=({"file_id": "q1", "file_name": "黑夜告白.2026.mkv", "path": "/quark/云下载/影片"},),
    )
    with (
        patch(
            "app.services.direct_link_transfer.get_settings",
            return_value=Settings(quark_cloud_download_path="/quark/云下载"),
        ),
        patch("app.services.direct_link_transfer.QuarkClient"),
        patch("app.services.direct_link_transfer.QuarkTransferProvider", return_value=provider),
    ):
        count, names, _outputs = _transfer_quark_share_with_files(
            "https://pan.quark.cn/s/demo",
            "/quark/云下载/影片",
            title="黑夜告白",
            year="2026",
            category=category,
        )

    plan = provider.execute.call_args.args[0]
    assert (count, names) == (1, ["黑夜告白.2026.mkv"])
    assert plan.resolution.rename_pairs[0].replacement == "黑夜告白.2026.mkv"


def test_quark_named_episode_transfer_keeps_original_name_when_episode_is_unknown():
    provider = Mock()
    provider.configured.return_value = True
    provider.inspect_share.return_value = ShareInspection(
        True,
        "https://pan.quark.cn/s/demo",
        (
            SourceFile("random.mkv", 10, "/random.mkv", "q1"),
            SourceFile("random.zh.srt", 2, "/random.zh.srt", "q2"),
            SourceFile("readme.txt", 1, "/readme.txt", "q3"),
        ),
    )
    provider.execute.return_value = ProviderExecutionResult(
        True,
        "provider_completed",
        "done",
        executed_items=3,
        confirmed=True,
        outputs=(
            {"file_id": "q1", "file_name": "random.mkv", "path": "/quark/云下载/03电视剧"},
            {"file_id": "q2", "file_name": "random.zh.srt", "path": "/quark/云下载/03电视剧"},
            {"file_id": "q3", "file_name": "readme.txt", "path": "/quark/云下载/03电视剧"},
        ),
    )
    with (
        patch(
            "app.services.direct_link_transfer.get_settings",
            return_value=Settings(quark_cloud_download_path="/quark/云下载"),
        ),
        patch("app.services.direct_link_transfer.QuarkClient"),
        patch("app.services.direct_link_transfer.QuarkTransferProvider", return_value=provider),
    ):
        count, names, _outputs = _transfer_quark_share_with_files(
            "https://pan.quark.cn/s/demo",
            "/quark/云下载/03电视剧",
            title="黑夜告白",
            year="2026",
            category="tv",
        )

    assert (count, names) == (3, ["random.mkv", "random.zh.srt", "readme.txt"])
    plan = provider.execute.call_args.args[0]
    assert [pair.replacement for pair in plan.resolution.rename_pairs] == [
        "random.mkv",
        "random.zh.srt",
        "readme.txt",
    ]
    assert (plan.destination_scope, plan.cloud_download_child) == ("cloud_download", "03电视剧")


def test_115_named_episode_transfer_keeps_complete_share_when_episode_is_unknown():
    sources = (
        SourceFile("random.mkv", 10, "/random.mkv", "p1"),
        SourceFile("random.zh.srt", 2, "/random.zh.srt", "p2"),
        SourceFile("readme.txt", 1, "/readme.txt", "p3"),
    )
    provider = Mock()
    provider.inspect_share.return_value = ShareInspection(True, "https://115.com/s/demo", sources)
    provider.execute.return_value = ProviderExecutionResult(
        True,
        "provider_completed",
        "done",
        executed_items=3,
        confirmed=True,
        outputs=(
            {"file_id": "p1", "file_name": "random.mkv", "path": "/115/云下载/03电视剧"},
            {"file_id": "p2", "file_name": "random.zh.srt", "path": "/115/云下载/03电视剧"},
            {"file_id": "p3", "file_name": "readme.txt", "path": "/115/云下载/03电视剧"},
        ),
    )
    client = Mock()
    client.configured.return_value = True
    with (
        patch(
            "app.services.direct_link_transfer.get_settings",
            return_value=Settings(p115_cloud_download_path="/115/云下载"),
        ),
        patch("app.services.direct_link_transfer.P115Client", return_value=client),
        patch("app.services.direct_link_transfer.P115TransferProvider", return_value=provider),
    ):
        count, names = _transfer_p115_share_with_files(
            "https://115.com/s/demo",
            "/115/云下载/03电视剧",
            title="黑夜告白",
            year="2026",
            category="tv",
        )

    assert (count, names) == (3, ["random.mkv", "random.zh.srt", "readme.txt"])
    plan = provider.execute.call_args.args[0]
    assert [pair.replacement for pair in plan.resolution.rename_pairs] == [
        "random.mkv",
        "random.zh.srt",
        "readme.txt",
    ]
    assert (plan.destination_scope, plan.cloud_download_child) == ("cloud_download", "03电视剧")


def test_named_episode_renames_a_matching_subtitle_only_when_episode_is_proven():
    staging_path = "/quark/云下载/03电视剧/黑夜告白 (2026)"
    sources = (
        SourceFile("S01E01.mkv", 10, "/S01E01.mkv", "q1"),
        SourceFile("S01E01.zh.srt", 2, "/S01E01.zh.srt", "q2"),
    )
    provider = Mock()
    provider.configured.return_value = True
    provider.inspect_share.return_value = ShareInspection(True, "https://pan.quark.cn/s/demo", sources)
    provider.execute.return_value = ProviderExecutionResult(
        True,
        "provider_completed",
        "done",
        executed_items=2,
        confirmed=True,
        outputs=(
            {"file_id": "q1", "file_name": "黑夜告白.2026.S01E01.mkv", "path": staging_path},
            {"file_id": "q2", "file_name": "黑夜告白.2026.S01E01.zh.srt", "path": staging_path},
        ),
    )
    with (
        patch(
            "app.services.direct_link_transfer.get_settings",
            return_value=Settings(quark_cloud_download_path="/quark/云下载"),
        ),
        patch("app.services.direct_link_transfer.QuarkClient"),
        patch("app.services.direct_link_transfer.QuarkTransferProvider", return_value=provider),
    ):
        count, names, _outputs = _transfer_quark_share_with_files(
            "https://pan.quark.cn/s/demo",
            staging_path,
            title="黑夜告白",
            year="2026",
            category="tv",
        )

    assert (count, names) == (
        2,
        ["黑夜告白.2026.S01E01.mkv", "黑夜告白.2026.S01E01.zh.srt"],
    )
    plan = provider.execute.call_args.args[0]
    assert [pair.replacement for pair in plan.resolution.rename_pairs] == names
    assert plan.save_path == staging_path
    assert (plan.destination_scope, plan.cloud_download_child) == ("cloud_download", "03电视剧")


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
    submit.assert_called_once_with("magnet:?xt=urn:btih:abcdef", "/strm/链接-01126901a9")
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


def test_completed_115_task_passes_only_its_exact_name_to_the_organizer():
    completed = P115CloudDownloadResult(
        {"data": {"name": "示例电影.2026"}},
        "task-7",
        "done",
        "115 云下载已完成",
        task={"data": {"name": "示例电影.2026"}},
    )
    with (
        patch("app.services.direct_link_transfer._trigger_targeted_cloud_organizer", return_value="已完成定点整理") as trigger,
        patch("app.services.direct_link_transfer._finish_job"),
        patch("app.services.direct_link_transfer._add_direct_notification"),
    ):
        result = _finish_p115_cloud_download_job(7, completed, "/媒体/云下载/01电影")

    assert result.ok
    trigger.assert_called_once_with(
        7,
        "p115",
        "/媒体/云下载/01电影",
        ["示例电影.2026"],
        title="",
        year="",
    )
    assert "定点整理" in result.message


def test_completed_115_task_without_exact_name_refuses_directory_scan():
    completed = P115CloudDownloadResult({}, "target", "done", "115 云下载已完成", task={})
    with (
        patch("app.services.direct_link_transfer.try_targeted_cloud_download_organization") as organize,
        patch("app.services.direct_link_transfer._finish_job"),
        patch("app.services.direct_link_transfer._add_direct_notification"),
    ):
        result = _finish_p115_cloud_download_job(8, completed, "/媒体/云下载/01电影")

    assert result.ok
    assert "任务未返回精确目标" in result.message
    assert "未对原始文件生成 STRM" in result.message
    organize.assert_not_called()


def test_named_completed_115_download_remains_done_when_organizer_does_not_claim():
    completed = P115CloudDownloadResult(
        {},
        "target",
        "done",
        "115 云下载已完成",
        task={"name": "Raw.Release"},
    )
    with (
        patch("app.services.direct_link_transfer.try_targeted_cloud_download_organization", return_value=(False, "")),
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer._add_direct_notification"),
    ):
        result = _finish_p115_cloud_download_job(
            9,
            completed,
            "/媒体/云下载/03电视剧",
            title="黑夜告白",
            year="2026",
        )

    assert result.ok
    assert "等待后续整理" in result.message
    assert "未对原始文件生成 STRM" in result.message
    finish.assert_called_once_with(9, "done", "provider_completed", result.message)


def test_named_submitted_115_download_without_trackable_id_stays_submitted():
    submitted = P115CloudDownloadResult({}, "target", "submitted", "115 已接受任务")
    with (
        patch("app.services.direct_link_transfer._start_p115_cloud_download_monitor", return_value=False),
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer._add_direct_notification"),
    ):
        result = _finish_p115_cloud_download_job(
            11,
            submitted,
            "/媒体/云下载/03电视剧",
            title="黑夜告白",
            year="2026",
        )

    assert result.ok
    assert "名称和年份将作为后续整理提示" in result.message
    assert "未返回可跟踪任务标识" in result.message
    assert "未对原始文件生成 STRM" in result.message
    finish.assert_called_once_with(11, "done", "provider_submitted", result.message)


def test_plain_completed_115_download_waits_for_organizer_without_raw_strm():
    completed = P115CloudDownloadResult(
        {},
        "target",
        "done",
        "115 云下载已完成",
        task={"name": "Raw.Release"},
    )
    with (
        patch("app.services.direct_link_transfer.try_targeted_cloud_download_organization", return_value=(False, "")),
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer._add_direct_notification"),
    ):
        result = _finish_p115_cloud_download_job(10, completed, "/媒体/云下载/03电视剧")

    assert result.ok
    assert "等待后续整理" in result.message
    assert "未对原始文件生成 STRM" in result.message
    finish.assert_called_once_with(10, "done", "provider_completed", result.message)


def test_targeted_organizer_receives_exact_quark_names_without_a_scan_fallback():
    settings = Settings(
        quark_cloud_download_organizer_enabled=True,
        quark_cloud_download_path="/媒体/云下载",
        quark_cloud_download_organizer_directories_json='["/媒体/云下载/03电视剧"]',
    )
    with (
        patch("app.services.post_transfer_pipeline.get_settings", return_value=settings),
        patch("app.services.cloud_download_organizer.run_targeted_cloud_download_organizer", return_value={"accepted": True, "outcome": "organized"}) as organize,
    ):
        message = _trigger_targeted_cloud_organizer(
            17,
            "quark",
            "/媒体/云下载/03电视剧",
            ["示例剧.S01E01.mkv"],
        )

    organize.assert_called_once_with(
        "quark",
        "/媒体/云下载/03电视剧",
        expected_file_ids=[],
        expected_names=["示例剧.S01E01.mkv"],
        media_title="",
        media_year="",
        media_query_hint="",
        explicit_request=False,
    )
    assert "定点整理" in message


def test_exact_share_outputs_never_index_cloud_download_raw_files():
    targets = ({"file_id": "q1", "file_name": "黑夜告白.2026.mkv", "path": "/夸克/云下载/01电影"},)
    with (
        patch("app.services.direct_link_transfer.try_targeted_cloud_download_organization", return_value=(False, "")) as organize,
    ):
        message = _trigger_targeted_cloud_organizer(
            18,
            "quark",
            "/夸克/云下载/01电影",
            ["黑夜告白.2026.mkv"],
            exact_files=targets,
            title="黑夜告白",
            year="2026",
        )

    assert "等待后续整理" in message
    assert "未对原始文件生成 STRM" in message
    organize.assert_called_once_with(
        provider="quark",
        target_path="/夸克/云下载/01电影",
        target_files=targets,
        media_title="黑夜告白",
        media_year="2026",
        media_query_hint="",
        explicit_request=True,
    )


def test_targeted_organizer_surfaces_the_exact_not_started_reason():
    with patch(
        "app.services.direct_link_transfer.try_targeted_cloud_download_organization",
        return_value=(False, "夸克云下载整理未启用，未启动 115/OpenList 补齐"),
    ):
        message = _trigger_targeted_cloud_organizer(
            19,
            "quark",
            "/strm/download/03电视剧/秘令 (2020)",
            ["秘令.2020.S02E01.mkv"],
            title="秘令",
            year="2020",
        )
    assert message == "夸克云下载整理未启用，未启动 115/OpenList 补齐"


@pytest.mark.parametrize("category", ["movie", "concert", "documentary"])
def test_115_named_film_categories_use_movie_naming_in_selected_folder(category):
    source = SourceFile("Source.2026.1080p.mkv", 100, "Source.2026.1080p.mkv", "source-id")
    provider = Mock()
    provider.inspect_share.return_value = ShareInspection(True, "https://115.com/s/demo", (source,))
    provider.execute.return_value = ProviderExecutionResult(
        True,
        "provider_completed",
        "done",
        executed_items=1,
        confirmed=True,
        outputs=({"file_id": "received", "file_name": "黑夜告白.2026.mkv", "path": "/115/云下载/01电影"},),
    )
    client = Mock()
    client.configured.return_value = True
    with (
        patch("app.services.direct_link_transfer.P115Client", return_value=client),
        patch("app.services.direct_link_transfer.P115TransferProvider", return_value=provider),
    ):
        count, names = _transfer_p115_share_with_files(
            "https://115.com/s/demo",
            "/115/云下载/01电影",
            title="黑夜告白",
            year="2026",
            category=category,
        )

    assert (count, names) == (1, ["黑夜告白.2026.mkv"])
    plan = provider.execute.call_args.args[0]
    assert plan.save_path == "/115/云下载/01电影"
    assert plan.resolution.rename_pairs[0].replacement == "黑夜告白.2026.mkv"


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


def test_native_quark_direct_transfer_finishes_and_passes_exact_outputs_to_organizer():
    request = DirectLinkRequest(
        link="https://pan.quark.cn/s/demo",
        provider="quark",
        root_path="/夸克/云下载/03电视剧",
        options=(),
        title="黑夜告白",
        year="2026",
        category="tv",
    )
    with (
        patch("app.services.direct_link_transfer.prepare_direct_link_request", return_value=request),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(57, False)) as create_job,
        patch("app.services.direct_link_transfer._validate_provider_path"),
        patch(
            "app.services.direct_link_transfer._transfer_quark_share_with_files",
            return_value=(
                2,
                ["黑夜告白.2026.S01E01.mp4", "黑夜告白.2026.S01E02.mp4"],
                (
                    {"file_id": "q1", "file_name": "黑夜告白.2026.S01E01.mp4", "path": request.root_path},
                    {"file_id": "q2", "file_name": "黑夜告白.2026.S01E02.mp4", "path": request.root_path},
                ),
            ),
        ),
        patch("app.services.direct_link_transfer._direct_openlist_sync_message", return_value="") as openlist_completion,
        patch("app.services.direct_link_transfer._trigger_targeted_cloud_organizer", return_value="已完成定点整理") as organize,
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer._add_direct_notification"),
        patch("app.services.direct_link_transfer.infer_share_provider", return_value=("quark", "quark")),
    ):
        result = handle_direct_link_transfer(
            request.link,
            "Sunny",
            request.root_path,
            "web",
            title=request.title,
            year=request.year,
            category=request.category,
            preserve_save_path=True,
    )

    assert result.ok
    assert "原生夸克已完成验真、转存和云下载目录确认" in result.message
    staging_path = "/夸克/云下载/03电视剧/黑夜告白 (2026)"
    assert create_job.call_args.args[2] == staging_path
    assert organize.call_args.args[2] == staging_path
    organize.assert_called_once()
    assert organize.call_args.kwargs["exact_files"][0]["file_id"] == "q1"
    openlist_completion.assert_not_called()
    finish.assert_called_once_with(57, "done", "provider_completed", result.message)


def test_named_link_uses_one_media_folder_inside_selected_staging_scope():
    request = DirectLinkRequest(
        link="https://pan.quark.cn/s/demo-folder",
        provider="quark",
        root_path="/strm/download",
        options=(),
        title="秘令",
        year="2026",
        category="tv",
    )
    staging_path = "/strm/download/03电视剧/秘令 (2026)"
    outputs = (
        {"file_id": "q1", "file_name": "秘令.2026.S01E01.mp4", "path": staging_path},
    )
    with (
        patch("app.services.direct_link_transfer.prepare_direct_link_request", return_value=request),
        patch("app.services.direct_link_transfer._validate_provider_path"),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(157, False)) as create_job,
        patch(
            "app.services.direct_link_transfer._transfer_quark_share_with_files",
            return_value=(1, ["秘令.2026.S01E01.mp4"], outputs),
        ) as transfer,
        patch("app.services.direct_link_transfer._trigger_targeted_cloud_organizer", return_value="已完成定点整理") as organize,
        patch("app.services.direct_link_transfer._finish_job"),
        patch("app.services.direct_link_transfer._add_direct_notification"),
        patch("app.services.direct_link_transfer.infer_share_provider", return_value=("quark", "quark")),
    ):
        result = handle_direct_link_transfer(
            request.link,
            "Sunny",
            "/strm/download/03电视剧",
            "telegram",
            title=request.title,
            year=request.year,
            category=request.category,
            preserve_save_path=True,
        )

    assert result.ok
    assert create_job.call_args.args[2] == staging_path
    transfer.assert_called_once_with(
        request.link,
        staging_path,
        title="",
        year="",
        category="tv",
    )
    assert organize.call_args.args[2] == staging_path
    assert organize.call_args.kwargs["exact_files"] == outputs


def test_confirmed_detected_share_title_transfers_before_tmdb_organization():
    request = DirectLinkRequest(
        link="https://pan.quark.cn/s/demo-folder",
        provider="quark",
        root_path="/strm/download",
        options=(),
        category="tv",
    )
    staging_path = "/strm/download/03电视剧/秘令 第二季"
    outputs = ({"file_id": "q1", "file_name": "S02E01.mp4", "path": staging_path},)
    with (
        patch("app.services.direct_link_transfer.prepare_direct_link_request", return_value=request),
        patch("app.services.direct_link_transfer._validate_provider_path"),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(158, False)) as create_job,
        patch(
            "app.services.direct_link_transfer._transfer_quark_share_with_files",
            return_value=(1, ["S02E01.mp4"], outputs),
        ) as transfer,
        patch("app.services.direct_link_transfer._trigger_targeted_cloud_organizer", return_value="等待 TMDB 核对") as organize,
        patch("app.services.direct_link_transfer._finish_job"),
        patch("app.services.direct_link_transfer._add_direct_notification"),
        patch("app.services.direct_link_transfer.infer_share_provider", return_value=("quark", "quark")),
    ):
        result = handle_direct_link_transfer(
            request.link,
            "Sunny",
            "/strm/download/03电视剧",
            "telegram",
            staging_name="秘令 第二季",
            preserve_save_path=True,
        )

    assert result.ok
    assert create_job.call_args.args[2] == staging_path
    transfer.assert_called_once_with(
        request.link,
        staging_path,
        title="",
        year="",
        category="tv",
    )
    assert organize.call_args.kwargs["title"] == ""
    assert organize.call_args.kwargs["year"] == ""
    assert organize.call_args.kwargs["media_query_hint"] == "秘令 第二季"


def test_native_quark_direct_transfer_does_not_request_qas_reconciliation():
    request = DirectLinkRequest(
        link="https://pan.quark.cn/s/demo",
        provider="quark",
        root_path="/夸克/云下载/03电视剧",
        options=(),
        title="榛戝鍛婄櫧",
        year="2026",
        category="tv",
    )
    with (
        patch("app.services.direct_link_transfer.prepare_direct_link_request", return_value=request),
        patch("app.services.direct_link_transfer._create_direct_job", return_value=(58, False)),
        patch("app.services.direct_link_transfer._validate_provider_path"),
        patch(
            "app.services.direct_link_transfer._transfer_quark_share_with_files",
            return_value=(1, ["黑夜告白.2026.S01E01.mkv"], ({"file_id": "q1", "file_name": "黑夜告白.2026.S01E01.mkv"},)),
        ),
        patch("app.services.direct_link_transfer._direct_openlist_sync_message", return_value=""),
        patch("app.services.direct_link_transfer._trigger_targeted_cloud_organizer", return_value=""),
        patch("app.services.direct_link_transfer._finish_job"),
        patch("app.services.direct_link_transfer._add_direct_notification"),
        patch("app.services.direct_link_transfer.infer_share_provider", return_value=("quark", "quark")),
        patch("app.services.qas_reconciler.request_qas_reconciliation") as reconcile,
    ):
        result = handle_direct_link_transfer(
            request.link,
            "Sunny",
            request.root_path,
            "web",
            title=request.title,
            year=request.year,
            category=request.category,
            preserve_save_path=True,
        )

    assert result.ok
    reconcile.assert_not_called()


def test_offline_link_does_not_fall_back_to_openlist_when_native_115_fails():
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
        with pytest.raises(P115Error, match="TLS EOF"):
            _transfer_p115_cloud_download("magnet:?xt=urn:btih:abcdef", "/下载文件夹")

    openlist_client.assert_not_called()


def test_direct_link_subfolders_do_not_fall_back_to_openlist_when_115_path_is_unavailable():
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
        result = _provider_child_directories("p115", "/媒体库/下载文件夹")

    assert result == []
    openlist_client.assert_not_called()


def test_direct_link_target_prompt_uses_folder_names_not_full_paths():
    with patch("app.services.direct_link_transfer._provider_child_directories", return_value=["电影", "剧集"]):
        options = _direct_target_options("qas", "/夸克/下载链接")

    assert [item.label for item in options] == ["电影", "剧集"]
    assert [item.path for item in options] == ["/夸克/下载链接/电影", "/夸克/下载链接/剧集"]


def test_direct_link_target_options_use_saved_categories_without_reading_provider():
    settings = SimpleNamespace(
        provider_category_paths=lambda _provider: {
            "movie": "/01电影",
            "tv": "/03电视剧",
            "short_drama": "/13短剧",
        },
        provider_cloud_download_path=lambda _provider: "/strm/download",
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer._provider_child_directories") as provider_read,
    ):
        options = _direct_target_options("quark", "/strm/download")

    assert [(item.label, item.path) for item in options] == [
        ("01电影", "/strm/download/01电影"),
        ("03电视剧", "/strm/download/03电视剧"),
        ("13短剧", "/strm/download/13短剧"),
    ]
    provider_read.assert_not_called()


def test_interactive_link_reads_children_from_p115_configured_save_root():
    settings = SimpleNamespace(
        direct_download_provider="p115",
        direct_download_save_path="/媒体库/下载链接",
        default_provider_key=lambda: "p115",
        provider_save_root=lambda provider: "/媒体库",
    )
    with (
        patch("app.services.direct_link_transfer.get_settings", return_value=settings),
        patch("app.services.direct_link_transfer._provider_child_directories", return_value=["01电影", "03电视剧"]) as children,
    ):
        request = prepare_direct_link_request("magnet:?xt=urn:btih:abcdef")

    assert request.root_path == "/媒体库"
    assert [(item.label, item.path) for item in request.options] == [
        ("01电影", "/媒体库/01电影"),
        ("03电视剧", "/媒体库/03电视剧"),
    ]
    children.assert_called_once_with("p115", "/媒体库")


def test_direct_link_with_media_name_still_offers_cloud_download_children():
    settings = SimpleNamespace(
        provider_category_paths=lambda _provider: {"movie": "/01电影", "tv": "/03电视剧"},
        provider_cloud_download_path=lambda _provider: "/夸克/云下载",
    )
    with patch(
        "app.services.direct_link_transfer.get_settings",
        return_value=settings,
    ):
        options = _direct_target_options(
            "quark",
            "/夸克/云下载",
            title="黑夜告白",
            year="2026",
        )

    assert [item.category for item in options] == ["movie", "tv"]
    assert [item.label for item in options] == ["01电影", "03电视剧"]
    assert [item.path for item in options] == ["/夸克/云下载/01电影", "/夸克/云下载/03电视剧"]


def test_direct_link_target_must_be_cloud_download_root_or_direct_child():
    settings = Settings(
        p115_root_path="/正式媒体库",
        p115_cloud_download_path="/独立云下载",
    )
    with patch("app.services.direct_link_transfer.get_settings", return_value=settings):
        _validate_provider_path("p115", "/独立云下载")
        _validate_provider_path("p115", "/独立云下载/电影", require_child=True)
        with pytest.raises(ValueError, match="直属子文件夹"):
            _validate_provider_path("p115", "/独立云下载/电影/嵌套", require_child=True)
        with pytest.raises(ValueError, match="云下载路径内"):
            _validate_provider_path("p115", "/正式媒体库/电影", require_child=True)


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
    assert request.root_path == "/strm"
    tmdb.search.assert_called_once_with("黑夜告白", media_type="tv")


def test_direct_year_prefers_explicit_year_without_tmdb_lookup():
    with patch("app.services.direct_link_transfer.TmdbClient") as tmdb:
        assert _resolve_direct_year("黑夜告白", "2026", "tv") == "2026"
    tmdb.assert_not_called()
