import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.scheduler import _run_scheduled_activity, run_scheduled_emby_cover_refresh


def test_recurring_scheduled_activity_updates_one_latest_log_row():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        with patch.dict(os.environ, {"DB_PATH": str(Path(temporary) / "scheduled.db")}):
            get_settings.cache_clear()
            init_db()
            assert _run_scheduled_activity("tracking", "智能追更巡检", lambda: []) == []
            assert _run_scheduled_activity("tracking", "智能追更巡检", lambda: [{"id": 1}]) == [{"id": 1}]
            with db() as conn:
                rows = conn.execute(
                    "SELECT provider,status,stage,message,display_title,request_source FROM transfer_jobs WHERE execution_key='scheduled:tracking'"
                ).fetchall()

    get_settings.cache_clear()
    assert len(rows) == 1
    assert tuple(rows[0]) == ("scheduler", "done", "scheduled_completed", "本轮巡检完成，处理 1 项", "智能追更巡检", "scheduler")


def test_scheduled_cover_partial_failure_is_recorded_in_the_activity_log():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        with patch.dict(os.environ, {"DB_PATH": str(Path(temporary) / "scheduled-cover.db")}):
            get_settings.cache_clear()
            init_db()
            with patch(
                "app.services.scheduler.refresh_all_library_covers",
                return_value={"updated": 3, "failed": 1, "results": []},
            ):
                result = run_scheduled_emby_cover_refresh()
            with db() as conn:
                row = conn.execute(
                    "SELECT provider,status,stage,message,display_title,request_source FROM transfer_jobs WHERE execution_key='scheduled:emby-covers'"
                ).fetchone()

    get_settings.cache_clear()
    assert result["updated"] == 3
    assert tuple(row) == ("scheduler", "failed", "scheduled_failed", "封面更新完成，成功 3 个，失败 1 个", "Emby 媒体库封面更新", "scheduler")
