from types import SimpleNamespace
from unittest.mock import patch

from app.clients.p115 import P115CloudDownloadResult, P115Error
from app.services.direct_link_transfer import extract_download_link, handle_direct_link_transfer, looks_like_download_link


def test_extracts_direct_download_links():
    assert looks_like_download_link("转存 magnet:?xt=urn:btih:abcdef")
    assert extract_download_link("请保存 https://115cdn.com/s/demo?password=123") == "https://115cdn.com/s/demo?password=123"


def test_direct_download_disabled_does_not_fall_through_as_resource():
    settings = SimpleNamespace(direct_download_enabled=False)
    with patch("app.services.direct_link_transfer.get_settings", return_value=settings):
        result = handle_direct_link_transfer("magnet:?xt=urn:btih:abcdef", "Sunny")
    assert not result.ok
    assert "尚未启用" in result.message


def test_offline_link_requires_115_provider():
    settings = SimpleNamespace(
        direct_download_enabled=True,
        direct_download_provider="qas",
        direct_download_save_path="/strm/downloads",
        default_provider_key=lambda: "qas",
        provider_save_root=lambda provider: "/strm",
    )
    with patch("app.services.direct_link_transfer.get_settings", return_value=settings):
        result = handle_direct_link_transfer("magnet:?xt=urn:btih:abcdef", "Sunny")
    assert not result.ok
    assert result.unsupported
    assert "只支持关联网盘选择 115" in result.message


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
    assert "仍在处理中" in result.message
    submit.assert_called_once_with("magnet:?xt=urn:btih:abcdef", "/strm/downloads")
    finish.assert_called_once()


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
