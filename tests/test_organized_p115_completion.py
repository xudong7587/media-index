import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.organized_p115_completion import (
    _run_completion,
    prepare_organized_quark_completion,
)
from app.services.p115_completion import P115CompletionResult


def test_organized_completion_uses_only_verified_final_names_and_path():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        env = {
            "DB_PATH": str(Path(temporary) / "organized-completion.db"),
            "OPENLIST_ENABLED": "true",
            "OPENLIST_AUTO_SYNC": "true",
            "OPENLIST_AUTO_SYNC_DIRECTION": "qas_to_p115",
        }
        with patch.dict(os.environ, env, clear=False):
            get_settings.cache_clear()
            init_db()
            with db() as conn:
                cursor = conn.execute(
                    """INSERT INTO transfer_jobs(provider,target,status,stage,display_title,external_provider_status)
                       VALUES('quark','cloud','running','organizer_post_processing','测试剧','{}')"""
                )
                job_id = int(cursor.lastrowid)
            prepared = prepare_organized_quark_completion(
                job_id,
                save_path="/媒体库/03电视剧/测试剧 (2026)/Season 01",
                target_files=(
                    {"name": "测试剧.2026.S01E01.mkv", "path": "/媒体库/03电视剧/测试剧 (2026)/Season 01"},
                ),
                tmdb_id=100,
                media_type="tv",
                season_number=1,
                title="测试剧",
                year="2026",
                category="tv",
            )
            assert prepared
            with db() as conn:
                state = json.loads(conn.execute(
                    "SELECT external_provider_status FROM transfer_jobs WHERE id=?", (job_id,)
                ).fetchone()[0])
                conn.execute(
                    "UPDATE transfer_jobs SET status='done',stage='organizer_completed' WHERE id=?", (job_id,)
                )
            assert state["p115_completion"]["state"] == "queued"
            assert state["p115_completion"]["filenames"] == ["测试剧.2026.S01E01.mkv"]

            completion = P115CompletionResult(True, True, True, (), (), "115 原生秒转完成", "done")
            with patch(
                "app.services.organized_p115_completion.complete_quark_to_p115", return_value=completion
            ) as complete:
                _run_completion(job_id)

            complete.assert_called_once()
            assert complete.call_args.kwargs["save_path"] == "/媒体库/03电视剧/测试剧 (2026)/Season 01"
            assert complete.call_args.kwargs["filenames"] == ("测试剧.2026.S01E01.mkv",)
            assert complete.call_args.kwargs["supplement_missing_episodes"] is True
            with db() as conn:
                finished = json.loads(conn.execute(
                    "SELECT external_provider_status FROM transfer_jobs WHERE id=?", (job_id,)
                ).fetchone()[0])
            assert finished["p115_completion"]["state"] == "done"
    get_settings.cache_clear()
