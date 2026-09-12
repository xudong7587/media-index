import json
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import grpc
import pytest
from google.protobuf.empty_pb2 import Empty

from app.clients import cd2_pb2 as wire
from app.clients.cd2 import Cd2Client, Cd2Error
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services import cross_copy, openlist_sync


@pytest.fixture
def sandbox(tmp_path):
    with patch.dict(os.environ, {
        "MEDIA_CONFIG_PATH": str(tmp_path / "runtime.env"), "DB_PATH": str(tmp_path / "test.db"),
        "CROSS_COPY_TRANSPORT": "cd2", "CD2_URL": "http://127.0.0.1:19798", "CD2_TOKEN": "test-token",
        "CD2_QAS_LIBRARY_PATH": "/quark/strm", "CD2_P115_LIBRARY_PATH": "/115/strm",
        "QUARK_ROOT_PATH": "/strm", "P115_ROOT_PATH": "/strm", "OPENLIST_ENABLED": "true",
        "OPENLIST_URL": "", "OPENLIST_TOKEN": "", "OPENLIST_AUTO_SYNC": "true",
    }):
        get_settings.cache_clear()
        init_db()
        yield tmp_path
        get_settings.cache_clear()


def test_native_grpc_stream_and_bearer_contract():
    observed = []
    def listing(request, context):
        observed.append((request.path, request.forceRefresh, dict(context.invocation_metadata())))
        yield wire.SubFilesReply(subFiles=[wire.CloudDriveFile(name="Season 1", isDirectory=True)])
        yield wire.SubFilesReply(subFiles=[wire.CloudDriveFile(name="Episode.mkv", fileType=1, size=123)])
    server = grpc.server(ThreadPoolExecutor(max_workers=1))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler("clouddrive.CloudDriveFileSrv", {
        "GetSubFiles": grpc.unary_stream_rpc_method_handler(listing, request_deserializer=wire.ListSubFileRequest.FromString,
                                                          response_serializer=lambda value: value.SerializeToString()),
    }),))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        client = Cd2Client(f"http://127.0.0.1:{port}", "local-test-token")
        entries = client.list_entries("/quark")
        assert [entry["name"] for entry in entries] == ["Season 1", "Episode.mkv"]
        assert entries[0]["is_dir"] and entries[1]["size"] == 123
        assert observed[0][:2] == ("/quark", True)
        assert observed[0][2]["authorization"] == "Bearer local-test-token"
    finally:
        server.stop(0).wait()


def task(source="/quark/Show.mkv", dest="/115", *, status=3, start=100, **kwargs):
    return wire.CopyTask(sourcePath=source, destPath=dest, status=status,
                         startTime={"seconds": start}, **kwargs)


def test_status_uses_completion_and_failure_counters_not_progress():
    client = Cd2Client("http://localhost:19798", "test")
    client._rpc = Mock(return_value=wire.GetCopyTaskResult(copyTasks=[
        task(status=2, totalBytes=100, uploadedBytes=100), task(status=3),
        task(status=3, failedFiles=1), task(status=3, cancelledFiles=1), task(status=0, paused=True),
    ]))
    rows = client.copy_tasks()
    assert [row["state"] for row in rows] == ["running", "running", "done", "failed", "failed"]
    assert rows[0]["progress"] == 99


def test_copy_records_intent_before_rpc_and_ignores_stale_completed_task():
    client = Cd2Client("http://localhost:19798", "test")
    client.list_entries = Mock(return_value=[])
    current = [task()]
    events = []
    def rpc(method, request, response_type, **kwargs):
        if method == "GetCopyTasks":
            return wire.GetCopyTaskResult(copyTasks=current)
        assert method == "CopyFile"
        assert events == ["persisted"]
        assert list(request.theFilePaths) == ["/quark/Show.mkv"]
        assert request.destPath == "/115" and request.conflictPolicy == wire.CopyFileRequest.Overwrite
        return wire.FileOperationResult(success=True)
    client._rpc = rpc
    client.on_copy_prepared = lambda *args: events.append("persisted")
    result = client.copy("/quark", "/115", ["Show.mkv"], overwrite=True)
    assert result["accepted"] is True
    assert not client.copies_complete(result["copy_receipts"])
    current[:] = [task(start=101, status=2)]
    assert not client.copies_complete(result["copy_receipts"])
    current[:] = [task(start=101)]
    assert client.copies_complete(result["copy_receipts"])
    current[:] = [task(start=101, failedFolders=1)]
    with pytest.raises(Cd2Error, match="需人工复核"):
        client.copies_complete(result["copy_receipts"])


def test_existing_active_request_is_resumed_without_second_submission():
    client = Cd2Client("http://localhost:19798", "test")
    # CD2 may already expose the destination entry while uploading it.
    client.list_entries = Mock(return_value=[{"name": "Show.mkv", "size": 0}])
    client._rpc = Mock(return_value=wire.GetCopyTaskResult(copyTasks=[task(status=1)]))
    receipt = client.copy("/quark", "/115", ["Show.mkv"])
    assert receipt["accepted"] is True
    assert len(receipt["copy_receipts"]) == 1
    assert [call.args[0] for call in client._rpc.call_args_list] == ["GetCopyTasks"]
    assert not client.copies_complete([], target_dir="/115", names=["Show.mkv"])


@pytest.mark.parametrize("names", [["../Show.mkv"], ["dir/Show.mkv"], [".."], ["bad\n.mkv"], []])
def test_copy_rejects_non_direct_names_without_rpc(names):
    client = Cd2Client("http://localhost:19798", "test")
    client._rpc = Mock()
    with pytest.raises(Cd2Error):
        client.copy("/quark", "/115", names)
    client._rpc.assert_not_called()


def test_copy_timeout_preserves_intent_and_does_not_retry_submission():
    client = Cd2Client("http://localhost:19798", "test")
    client.list_entries = Mock(return_value=[])
    client._rpc = Mock(side_effect=[wire.GetCopyTaskResult(), Cd2Error("CD2 通信未确认")])
    persisted = Mock()
    client.on_copy_prepared = persisted
    result = openlist_sync._copy_with_retry(client, "/quark", "/115", ["Show.mkv"])
    assert result["accepted"] is None and len(result["copy_receipts"]) == 1
    persisted.assert_called_once()
    assert sum(call.args[0] == "CopyFile" for call in client._rpc.call_args_list) == 1


def test_exclusive_selection_and_legacy_mount_contract(sandbox):
    settings = get_settings()
    with patch("app.clients.cd2.Cd2Client") as cd2, patch("app.clients.openlist.OpenListClient") as old:
        assert cross_copy.copy_client(settings, openlist_factory=old) is cd2.return_value
        old.assert_not_called()
    assert openlist_sync._openlist_dir_for_save_path("/strm/Show", "p115", cross_copy.copy_settings(settings)) == "/115/strm/Show"
    status = cross_copy.config_status()
    assert status["ready"] and status["has_cd2_token"]
    assert "cd2_token" not in status and "test-token" not in json.dumps(status)
    with patch.dict(os.environ, {"CROSS_COPY_TRANSPORT": "openlist"}):
        get_settings.cache_clear()
        old = Mock()
        assert cross_copy.copy_client(openlist_factory=old) is old.return_value


def test_route_switch_rejected_during_wait_and_does_not_write_config(sandbox):
    path = sandbox / "runtime.env"
    path.write_text("PRESERVED=user-value\n", encoding="utf-8")
    job = openlist_sync.start_selected_openlist_sync("/quark/strm", "/115/strm", ["Show.mkv"])
    openlist_sync._defer_openlist_landing(job["job_id"], "pending")
    with pytest.raises(RuntimeError, match="待落盘"):
        cross_copy.save_config({"cross_copy_transport": "openlist"})
    assert path.read_text(encoding="utf-8") == "PRESERVED=user-value\n"
    assert cross_copy.transport_name() == "cd2"
    with pytest.raises(RuntimeError):
        cross_copy.validate_imported_transport({"CROSS_COPY_TRANSPORT": "openlist"})


def test_config_preserves_unrelated_values_and_inactive_credentials(sandbox):
    path = sandbox / "runtime.env"
    path.write_text("PRESERVED=user-value\nOPENLIST_TOKEN=old-token\n", encoding="utf-8")
    with patch("app.services.cross_copy.copy_client") as client:
        client.return_value.copy_tasks.return_value = []
        result = cross_copy.save_config({"cross_copy_transport": "openlist", "cd2_token": ""})
    assert result["cross_copy_transport"] == "openlist"
    content = path.read_text(encoding="utf-8")
    assert "PRESERVED=user-value" in content and "OPENLIST_TOKEN=old-token" in content
    assert get_settings().cd2_token == "test-token"


def test_persisted_cd2_receipt_gates_native_landing_and_shared_pipeline(sandbox):
    started = openlist_sync.start_selected_openlist_sync("/quark/strm", "/115/strm", ["Show.mkv"])
    receipts = [{"source": "/quark/strm/Show.mkv", "target": "/115/strm", "previous_starts": []}]
    fake = Mock()
    fake.copy.return_value = {"accepted": True, "copy_receipts": receipts}
    fake.copies_complete.return_value = False
    landed = [{"file_id": "115-file", "file_name": "Show.mkv", "path": "/strm/Show.mkv", "size": 100}]
    with patch("app.services.openlist_sync._copy_client", return_value=fake), \
         patch("app.services.openlist_sync._probe_openlist_p115_landing", return_value=("/strm", landed)) as probe, \
         patch("app.services.openlist_sync.run_post_transfer_pipeline", return_value=True) as pipeline:
        result = openlist_sync.run_selected_openlist_sync(started["job_id"], "/quark/strm", "/115/strm", ["Show.mkv"])
        assert result["pending"]
        probe.assert_not_called()
        pipeline.assert_not_called()
        assert openlist_sync.reconcile_pending_openlist_landings() == 0
        fake.copies_complete.return_value = True
        assert openlist_sync.reconcile_pending_openlist_landings() == 1
        assert pipeline.call_args.kwargs["provider"] == "p115"
        assert pipeline.call_args.kwargs["target_files"] == landed
        assert openlist_sync.reconcile_pending_openlist_landings() == 0
        assert pipeline.call_count == 1
    with db() as conn:
        row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (started["job_id"],)).fetchone()
    assert row["status"] == "done"
    assert json.loads(row["external_provider_status"])["openlist_landing"]["copy_receipts"] == receipts


def test_failed_remote_copy_requires_review_without_pipeline(sandbox):
    started = openlist_sync.start_selected_openlist_sync("/quark/strm", "/115/strm", ["Show.mkv"])
    openlist_sync._save_openlist_landing_context(started["job_id"], "/115/strm", ["Show.mkv"], copy_receipts=[{"source": "a"}])
    assert openlist_sync.recover_interrupted_cross_copies() == 1
    with patch("app.services.openlist_sync._copy_client") as fake, patch("app.services.openlist_sync.run_post_transfer_pipeline") as pipeline:
        fake.return_value.copies_complete.side_effect = Cd2Error("CD2 复制失败，需人工复核")
        assert openlist_sync.reconcile_pending_openlist_landings() == 0
        pipeline.assert_not_called()
    with db() as conn:
        assert conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (started["job_id"],)).fetchone()[0] == "needs_review"


def test_tracking_cannot_claim_native_file_before_cd2_finishes(sandbox):
    from app.services.qas_reconciler import reconcile_triggered_jobs
    pairs = [{"replacement": "Show.mkv"}, {"_tracking_openlist_fallback": {
        "copy_transport": "cd2", "copy_receipts": [{"source": "/quark/strm/Show.mkv", "target": "/115/strm"}],
    }}]
    with db() as conn:
        conn.execute("""INSERT INTO transfer_jobs(target,provider,status,stage,save_path,rename_pairs_json)
                        VALUES('cloud','p115','triggered','openlist_sync_submitted','/strm',?)""", (json.dumps(pairs),))
    with patch("app.services.cross_copy.copy_client") as client, \
         patch("app.services.qas_reconciler.get_transfer_provider") as provider, \
         patch("app.services.qas_reconciler._confirmation_expired", return_value=False), \
         patch("app.services.qas_reconciler.sync_transfer_notifications"):
        client.return_value.copies_complete.return_value = False
        result = reconcile_triggered_jobs(qas=Mock(), p115=Mock())
        assert result and not result[0]["confirmed"]
        provider.return_value.reconcile.assert_not_called()
        client.return_value.copies_complete.assert_called_once()


def test_route_switch_blocked_by_inflight_operation_before_job_creation(sandbox):
    with cross_copy.copy_operation(), pytest.raises(RuntimeError, match="复制"):
        cross_copy.save_config({"cross_copy_transport": "openlist"})


def test_remote_activity_blocks_switch_even_after_local_submission_job_ends(sandbox):
    with patch("app.services.cross_copy.copy_client") as client:
        client.return_value.copy_tasks.return_value = [{"state": "running"}]
        with pytest.raises(RuntimeError, match="远端"):
            cross_copy.save_config({"cross_copy_transport": "openlist"})
    assert cross_copy.transport_name() == "cd2"
