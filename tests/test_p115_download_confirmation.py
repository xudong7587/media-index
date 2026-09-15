from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.clients.p115 import (
    P115CloudDownloadResult, P115Error, P115File,
    _normalize_cloud_download_task, _select_cloud_download_task,
)
from app.services.direct_link_transfer import (
    _confirmed_p115_download_name, _finish_p115_cloud_download_job,
    _monitor_p115_cloud_download,
)


@pytest.mark.parametrize("fields", [
    {"status": 2, "percentDone": 100, "display_status": "finished", "status_text": "下载成功"},
    {"status": 2, "percentDone": 100},
    {"status": 2, "display_percent": 100},
    {"display_status": "finished"},
    {"status": 11},
    {"state": "done"},
])
def test_completed_download_response_variants(fields):
    assert _normalize_cloud_download_task({"state": True, **fields})[0] == "done"


def test_failure_wins_over_stale_completed_percentage():
    assert _normalize_cloud_download_task({"display_status": "failed", "percentDone": 100})[0] == "failed"
    assert _normalize_cloud_download_task({"state": True, "percentDone": 40})[0] == "submitted"


def test_unrelated_success_is_not_selected_as_requested_download():
    payload = {"state": True, "data": [{"info_hash": "other", "status": 11}]}
    assert _select_cloud_download_task(payload, "wanted", "") is None


@pytest.mark.parametrize("cid,entries", [
    ("0", []),
    ("folder", []),
    ("folder", [P115File("different-id", "folder", "movie.mkv", "", 10)]),
])
def test_old_success_cannot_organize_missing_or_replaced_file(cid, entries):
    result = P115CloudDownloadResult({}, "folder", "done", task={"name": "movie.mkv", "file_id": "expected"})
    with (
        patch("app.services.direct_link_transfer.P115Client") as client,
        patch("app.services.direct_link_transfer._trigger_targeted_cloud_organizer") as organize,
        patch("app.services.direct_link_transfer._finish_job") as finish,
    ):
        client.return_value.directory_id.return_value = cid
        client.return_value.list_directory_complete.return_value = entries
        outcome = _finish_p115_cloud_download_job(1, result, "/staging/movie", title="电影")
    assert not outcome.ok
    assert finish.call_args.args[1:3] == ("needs_review", "provider_target_unverified")
    organize.assert_not_called()
    if cid == "0":
        client.return_value.list_directory_complete.assert_not_called()


def test_verified_file_in_submitted_directory_can_continue():
    result = P115CloudDownloadResult({}, "folder", "done", task={"name": "movie.mkv", "file_id": "expected"})
    with patch("app.services.direct_link_transfer.P115Client") as client:
        client.return_value.directory_id.return_value = "folder"
        client.return_value.list_directory_complete.return_value = [P115File("expected", "folder", "movie.mkv", "", 10)]
        assert _confirmed_p115_download_name(result, "/staging/movie") == "movie.mkv"
        client.return_value.directory_id.assert_called_once_with("/staging/movie")


def test_monitor_uses_same_file_verification_as_immediate_completion():
    import json
    state = json.dumps({"kind": "p115_cloud_download_target", "info_hash": "wanted", "save_path": "/staging/movie"})
    result = P115CloudDownloadResult({}, "", "done", task={"name": "movie.mkv"})
    with (
        patch("app.services.direct_link_transfer.db") as db,
        patch("app.services.direct_link_transfer.get_settings", return_value=SimpleNamespace(qas_confirmation_timeout_minutes=5)),
        patch("app.services.direct_link_transfer.P115Client") as client,
        patch("app.services.direct_link_transfer._finish_p115_cloud_download_job") as finish,
    ):
        db.return_value.__enter__.return_value.execute.return_value.fetchone.side_effect = [
            {"external_provider_status": state, "save_path": "/staging/movie"}, {"status": "triggered"},
        ]
        client.return_value.cloud_download_task_status.return_value = result
        _monitor_p115_cloud_download(1)
    finish.assert_called_once_with(1, result, "/staging/movie", title="", year="")
