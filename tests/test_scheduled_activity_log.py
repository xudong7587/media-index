import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.db.database import db, init_db
from app.services.scheduler import _run_scheduled_activity


def test_recurring_scheduled_activity_updates_one_latest_log_row():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        with patch.dict(os.environ, {"DB_PATH": str(Path(temporary) / "scheduled.db")}):
            init_db()
            assert _run_scheduled_activity("tracking", "智能追更巡检", lambda: []) == []
            assert _run_scheduled_activity("tracking", "智能追更巡检", lambda: [{"id": 1}]) == [{"id": 1}]
            with db() as conn:
                rows = conn.execute(
                    "SELECT provider,status,stage,message,display_title,request_source FROM transfer_jobs WHERE execution_key='scheduled:tracking'"
                ).fetchall()

    assert len(rows) == 1
    assert tuple(rows[0]) == ("scheduler", "done", "scheduled_completed", "本轮巡检完成，处理 1 项", "智能追更巡检", "scheduler")
