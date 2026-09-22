from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.clients.p115 import (
    P115CloudDownloadResult, P115Error, P115File,
    _normalize_cloud_download_task, _select_cloud_download_task,
)
from app.services.direct_link_transfer import (
    _confirmed_p115_download_name, _finish_p115_cloud_download_job,
    _monitor_p115_cloud_download, recover_p115_cloud_download_monitors,
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
def test_old_success_cannot_organize_missing_or_replaced_file(cid, entries, pending_download_jobs):
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


def test_stopped_download_is_not_finalized_or_organized(pending_download_jobs):
    pending_download_jobs.execute("UPDATE transfer_jobs SET status='stopped' WHERE id=1")
    result = P115CloudDownloadResult({}, "folder", "done", task={"name": "movie.mkv"})
    with (
        patch("app.services.direct_link_transfer._confirmed_p115_download_name") as verify,
        patch("app.services.direct_link_transfer._trigger_targeted_cloud_organizer") as organize,
        patch("app.services.direct_link_transfer._finish_job") as finish,
    ):
        outcome = _finish_p115_cloud_download_job(1, result, "/staging/movie")
    assert not outcome.ok
    assert pending_download_jobs.execute("SELECT status FROM transfer_jobs WHERE id=1").fetchone()[0] == "stopped"
    verify.assert_not_called()
    organize.assert_not_called()
    finish.assert_not_called()


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
            {"external_provider_status": state, "save_path": "/staging/movie"},
            {"status": "triggered"},
            {"external_provider_status": state},
            {"status": "done", "stage": "provider_completed"},
        ]
        client.return_value.cloud_download_task_status.return_value = result
        _monitor_p115_cloud_download(1)
    finish.assert_called_once_with(
        1,
        result,
        "/staging/movie",
        title="",
        year="",
        keep_monitoring_on_wait=True,
    )


def test_completed_download_keeps_monitoring_while_115_directory_settles(pending_download_jobs):
    result = P115CloudDownloadResult(
        {},
        "folder",
        "done",
        task_id="task-1",
        task={"name": "Dark.Matter.S01"},
    )
    with (
        patch("app.services.direct_link_transfer._confirmed_p115_download_name", return_value="Dark.Matter.S01"),
        patch(
            "app.services.direct_link_transfer._trigger_targeted_cloud_organizer",
            return_value="定点整理已受理，等待精确任务继续处理",
        ),
        patch("app.services.direct_link_transfer._finish_job") as finish,
        patch("app.services.direct_link_transfer._add_direct_notification") as notify,
    ):
        outcome = _finish_p115_cloud_download_job(
            1,
            result,
            "/staging/人生复本 (2024)",
            title="人生复本",
            year="2024",
            keep_monitoring_on_wait=True,
        )

    row = pending_download_jobs.execute(
        "SELECT status,stage,message FROM transfer_jobs WHERE id=1"
    ).fetchone()
    assert not outcome.ok
    assert tuple(row[:2]) == ("triggered", "provider_target_settling")
    assert "继续定点核验并自动重试整理" in row[2]
    finish.assert_not_called()
    notify.assert_not_called()


def test_immediate_completed_download_starts_settling_monitor(pending_download_jobs):
    result = P115CloudDownloadResult(
        {},
        "folder",
        "done",
        info_hash="hash-1",
        task={"name": "Dark.Matter.S01"},
    )
    with (
        patch("app.services.direct_link_transfer._confirmed_p115_download_name", return_value="Dark.Matter.S01"),
        patch(
            "app.services.direct_link_transfer._trigger_targeted_cloud_organizer",
            return_value="定点整理已受理，等待精确任务继续处理",
        ),
        patch("app.services.direct_link_transfer._start_p115_cloud_download_monitor", return_value=True) as start,
        patch("app.services.direct_link_transfer._finish_job") as finish,
    ):
        outcome = _finish_p115_cloud_download_job(
            1,
            result,
            "/staging/人生复本 (2024)",
            title="人生复本",
            year="2024",
        )

    assert outcome.ok
    assert "继续定点核验并自动重试整理" in outcome.message
    start.assert_called_once_with(
        1,
        result,
        "/staging/人生复本 (2024)",
        outcome.message,
        title="人生复本",
        year="2024",
    )
    finish.assert_not_called()


def test_recovery_resumes_settling_download_jobs(pending_download_jobs):
    pending_download_jobs.execute(
        "UPDATE transfer_jobs SET provider='p115',status='triggered',stage='provider_target_settling' WHERE id=1"
    )
    with patch(
        "app.services.direct_link_transfer.request_p115_cloud_download_monitor",
        return_value=True,
    ) as request:
        count = recover_p115_cloud_download_monitors()

    assert count == 1
    request.assert_called_once_with(1)


def test_recovery_reopens_legacy_completed_job_that_lost_its_settling_retry(pending_download_jobs):
    pending_download_jobs.execute(
        """UPDATE transfer_jobs SET provider='p115',status='done',stage='provider_completed',
           message='115 云下载已完成；定点整理已受理，等待精确任务继续处理',finished_at='2026-09-22 02:00:11'
           WHERE id=1"""
    )
    with patch(
        "app.services.direct_link_transfer.request_p115_cloud_download_monitor",
        return_value=True,
    ) as request:
        count = recover_p115_cloud_download_monitors()

    assert count == 1
    request.assert_called_once_with(1)
    row = pending_download_jobs.execute(
        "SELECT status,stage,finished_at,message FROM transfer_jobs WHERE id=1"
    ).fetchone()
    assert tuple(row[:3]) == ("triggered", "provider_target_settling", None)
    assert "服务升级后已恢复目标目录核验" in row[3]


def test_monitor_retries_done_download_until_target_contents_are_visible(pending_download_jobs):
    import json

    state = json.dumps(
        {
            "kind": "p115_cloud_download_target",
            "info_hash": "wanted",
            "save_path": "/staging/人生复本 (2024)",
            "title": "人生复本",
            "year": "2024",
        }
    )
    pending_download_jobs.execute(
        """UPDATE transfer_jobs SET provider='p115',status='triggered',stage='provider_target_monitoring',
           external_provider_status=?,save_path=? WHERE id=1""",
        (state, "/staging/人生复本 (2024)"),
    )
    result = P115CloudDownloadResult(
        {},
        "folder",
        "done",
        info_hash="wanted",
        task={"name": "Dark.Matter.S01"},
    )
    attempts = 0

    def finish(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            pending_download_jobs.execute(
                "UPDATE transfer_jobs SET status='triggered',stage='provider_target_settling' WHERE id=1"
            )
        else:
            pending_download_jobs.execute(
                "UPDATE transfer_jobs SET status='done',stage='provider_completed' WHERE id=1"
            )

    with (
        patch(
            "app.services.direct_link_transfer.get_settings",
            return_value=SimpleNamespace(qas_confirmation_timeout_minutes=5),
        ),
        patch("app.services.direct_link_transfer.P115Client") as client,
        patch("app.services.direct_link_transfer._finish_p115_cloud_download_job", side_effect=finish) as finalize,
        patch("app.services.direct_link_transfer.time.sleep"),
        patch("app.services.direct_link_transfer.time.monotonic", side_effect=[0, 1, 2]),
    ):
        client.return_value.cloud_download_task_status.return_value = result
        _monitor_p115_cloud_download(1)

    assert attempts == 2
    assert client.return_value.cloud_download_task_status.call_count == 2
    assert all(call.kwargs["keep_monitoring_on_wait"] for call in finalize.call_args_list)
    row = pending_download_jobs.execute(
        "SELECT status,stage FROM transfer_jobs WHERE id=1"
    ).fetchone()
    assert tuple(row) == ("done", "provider_completed")
