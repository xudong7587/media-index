from types import SimpleNamespace
from unittest.mock import patch

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
        patch("app.services.direct_link_transfer._transfer_p115_cloud_download") as submit,
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer.add_notification"),
    ):
        result = handle_direct_link_transfer("magnet:?xt=urn:btih:abcdef", "Sunny")
    assert result.ok
    assert result.job_id == 42
    submit.assert_called_once_with("magnet:?xt=urn:btih:abcdef", "/strm/downloads")
    finish.assert_called_once()
