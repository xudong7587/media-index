import io
import json
import os
import zipfile
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.diagnostics import router
from app.clients.p115 import P115CloudDownloadResult, P115File
from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.diagnostic_support import create_support_token
from app.services.diagnostics import (
    _LAST_PROBE, diagnostic_probe_download, diagnostic_task_timeline, diagnostic_tasks,
    export_diagnostic_bundle, recent_diagnostic_events, record_diagnostic_event,
)


@pytest.fixture
def runtime_db(tmp_path):
    with patch.dict(os.environ, {"DB_PATH": str(tmp_path / "test.db"), "DEVELOPER_REMOTE_DIAGNOSTICS_ENABLED": "true"}):
        get_settings.cache_clear()
        init_db()
        _LAST_PROBE.clear()
        with db() as conn:
            job_id = conn.execute(
                "INSERT INTO transfer_jobs(provider,target,status,stage,display_title,save_path,external_provider_status) "
                "VALUES('p115','cloud','triggered','provider_target_monitoring','群体','/downloads/Movies/群体',?)",
                (json.dumps({"kind": "p115_cloud_download_target", "task_id": "download-1", "info_hash": "a" * 40,
                             "cookie": "UID=private; CID=private", "last_result": {"status": "done", "url": "https://secret"}}),)
            ).lastrowid
        yield int(job_id)
        get_settings.cache_clear()


def test_latest_events_and_task_pagination_support_incremental_diagnosis(runtime_db):
    for number in range(8):
        record_diagnostic_event("test", f"poll-{number}", job_id=runtime_db)
    latest = recent_diagnostic_events(limit=3)
    assert [event["event"] for event in latest] == ["poll-5", "poll-6", "poll-7"]
    assert recent_diagnostic_events(after_id=latest[-1]["id"]) == []
    assert diagnostic_tasks(query="群体")["tasks"][0]["id"] == runtime_db
    assert diagnostic_tasks(query="%") == {"tasks": [], "next_before_id": None}


def test_provider_state_and_bundle_are_useful_without_credentials(runtime_db):
    record_diagnostic_event("test", "error", message="Cookie: UID=private; CID=private; SEID=private",
                            context={"signed_url": "https://115.com/path?sign=private", "authorization": "Bearer private"})
    timeline = diagnostic_task_timeline(runtime_db)
    assert timeline["task"]["external_provider_status"]["task_id"] == "download-1"
    bundle = export_diagnostic_bundle()
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        text = "\n".join(archive.read(name).decode() for name in archive.namelist())
        assert "private" not in text and "https://secret" not in text
        assert json.loads(archive.read("runtime.json"))["latest_event_id"] > 0


def test_live_probe_only_reads_persisted_task_and_bounded_target(runtime_db):
    client = Mock()
    client.cloud_download_task_status.return_value = P115CloudDownloadResult({}, "cid", "done", task={"status": 2, "percentDone": 100})
    client.directory_id.return_value = "cid"
    client.list_directory.return_value = (P115File("file", "cid", "群体.mkv", "", 2_000_000_000),)
    with (patch("app.clients.p115.P115Client", return_value=client),
          patch("app.services.paths.cloud_download_direct_child_scope", return_value="/downloads/Movies")):
        result = diagnostic_probe_download(runtime_db)
        repeated = diagnostic_probe_download(runtime_db)
    assert result["status"] == "done" and result["target_entries"][0]["file_id"] == "file"
    assert repeated["retry_after_seconds"] == 30
    client.cloud_download_task_status.assert_called_once_with("a" * 40, "download-1")
    assert [call[0] for call in client.mock_calls] == ["cloud_download_task_status", "directory_id", "list_directory"]
    with db() as conn:
        assert conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (runtime_db,)).fetchone()["status"] == "triggered"


def test_support_endpoints_require_token_and_disable_cache(runtime_db):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    token = create_support_token(30)["token"]
    for path in ("runtime", "tasks", f"tasks/{runtime_db}/timeline", "export"):
        assert client.get(f"/api/diagnostics/support/{path}").status_code == 401
        response = client.get(f"/api/diagnostics/support/{path}", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
    assert client.get(f"/api/diagnostics/support/tasks/{runtime_db}/probe").status_code == 401
