import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.diagnostics import export_diagnostic_bundle, record_diagnostic_event


def test_diagnostics_retain_transitions_and_export_redacted_bundle():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        with patch.dict(os.environ, {"DB_PATH": str(Path(temporary) / "diagnostics.db")}, clear=False):
            get_settings.cache_clear()
            init_db()
            with db() as conn:
                cursor = conn.execute(
                    """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,request_source,execution_key)
                       VALUES('cloud','p115','running','provider_submitting','开始提交','测试任务','discover','diagnostic-test')"""
                )
                job_id = int(cursor.lastrowid)
                conn.execute(
                    "UPDATE transfer_jobs SET status='failed',stage='provider_failed',message='token=secret-value' WHERE id=?",
                    (job_id,),
                )
            record_diagnostic_event(
                "http",
                "request_failed",
                level="error",
                message="api_key=another-secret",
                context={"cookie": "private-cookie", "method": "POST"},
            )
            payload = export_diagnostic_bundle()

            with db() as conn:
                timeline = conn.execute(
                    "SELECT event,status,stage FROM diagnostic_events WHERE job_id=? ORDER BY id", (job_id,)
                ).fetchall()

    get_settings.cache_clear()
    assert [tuple(row) for row in timeline] == [
        ("job_created", "running", "provider_submitting"),
        ("job_transition", "failed", "provider_failed"),
    ]
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "summary.json",
            "diagnostic-events.jsonl",
            "tasks.json",
            "workflow-steps.json",
            "deletion-intents.json",
        }
        events = archive.read("diagnostic-events.jsonl").decode("utf-8")
        assert "secret-value" not in events
        assert "another-secret" not in events
        assert "private-cookie" not in events
        assert "[REDACTED]" in events
        assert json.loads(archive.read("manifest.json"))["format"] == "mediaindex-diagnostics/v1"
