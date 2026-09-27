import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.organized_p115_completion import (
    _run_completion,
    prepare_organized_quark_completion,
    reconcile_submitted_organized_quark_completions,
    recover_organized_quark_completions,
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


@pytest.fixture
def recovery_db():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        with patch.dict(os.environ, {"DB_PATH": str(Path(temporary) / "recovery.db")}):
            get_settings.cache_clear()
            init_db()
            yield
    get_settings.cache_clear()


def insert_completion(state):
    with db() as conn:
        return conn.execute(
            "INSERT INTO transfer_jobs(provider,target,status,stage,external_provider_status) VALUES('quark','cloud','done','organizer_completed',?)",
            (json.dumps({"p115_completion": {"state": state, "filenames": ["Show.S01E01.mkv"]}}),),
        ).lastrowid


def test_interrupted_native_completion_is_visible_review_without_replaying_transfer(recovery_db):
    job_id = insert_completion("working")
    with patch("app.services.organized_p115_completion.complete_quark_to_p115") as transfer:
        _run_completion(job_id)
        _run_completion(job_id)
    transfer.assert_not_called()
    with db() as conn:
        result = json.loads(conn.execute("SELECT external_provider_status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()[0])
        step = conn.execute("SELECT status FROM media_workflow_steps WHERE job_id=? AND step_key='openlist_sync'", (job_id,)).fetchone()
    assert result["p115_completion"]["state"] == "needs_review"
    assert result["p115_completion"]["filenames"] == ["Show.S01E01.mkv"]
    assert step["status"] == "review"


def test_recovery_does_not_lose_queued_jobs_behind_recent_completed_history(recovery_db):
    oldest = insert_completion("queued")
    for _ in range(105):
        insert_completion("done")
    with patch("app.services.organized_p115_completion.request_organized_quark_completion", return_value=True) as request:
        assert recover_organized_quark_completions() == 1
    request.assert_called_once_with(oldest)


def test_uncertain_result_is_retained_as_review_and_cannot_be_replayed(recovery_db):
    job_id = insert_completion("queued")
    result = P115CompletionResult(True, True, False, ("Show.S01E01.mkv",), (), "提交结果需核验", "review")
    with patch("app.services.organized_p115_completion.complete_quark_to_p115", return_value=result) as transfer:
        _run_completion(job_id)
        _run_completion(job_id)
    transfer.assert_called_once()
    with db() as conn:
        state = json.loads(conn.execute("SELECT external_provider_status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()[0])
    assert state["p115_completion"]["state"] == "needs_review"


@pytest.mark.parametrize("child_status,child_stage,expected", [
    ("triggered", "openlist_copy_waiting", "submitted"),
    ("done", "openlist_sync_done", "submitted"),
    ("done", "openlist_post_processing_done", "done"),
    ("failed", "openlist_post_processing_failed", "failed"),
    ("needs_review", "openlist_copy_review", "failed"),
])
def test_submitted_parent_follows_exact_copy_child_without_resubmission(child_status, child_stage, expected):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        with patch.dict(os.environ, {"DB_PATH": str(Path(temporary) / "copy.db")}):
            get_settings.cache_clear()
            init_db()
            with db() as conn:
                child = conn.execute("INSERT INTO transfer_jobs(provider,target,status,stage) VALUES('openlist','cloud',?,?)", (child_status, child_stage)).lastrowid
                payload = {"p115_completion": {"state": "submitted", "copy_job_ids": [child], "filenames": ["Show.S01E01.mkv"]}}
                parent = conn.execute("INSERT INTO transfer_jobs(provider,target,status,stage,external_provider_status) VALUES('quark','cloud','done','organizer_completed',?)", (json.dumps(payload),)).lastrowid
                unrelated = conn.execute("INSERT INTO transfer_jobs(provider,target,status,stage,external_provider_status) VALUES('quark','cloud','done','organizer_completed',?)", (json.dumps({"p115_completion": {"state": "submitted"}}),)).lastrowid
            with patch("app.services.organized_p115_completion.complete_quark_to_p115") as transfer:
                _run_completion(parent)
                reconcile_submitted_organized_quark_completions()
                reconcile_submitted_organized_quark_completions()
            transfer.assert_not_called()
            with db() as conn:
                actual = json.loads(conn.execute("SELECT external_provider_status FROM transfer_jobs WHERE id=?", (parent,)).fetchone()[0])
                legacy = json.loads(conn.execute("SELECT external_provider_status FROM transfer_jobs WHERE id=?", (unrelated,)).fetchone()[0])
            assert actual["p115_completion"]["state"] == expected
            assert actual["p115_completion"]["filenames"] == ["Show.S01E01.mkv"]
            assert legacy["p115_completion"]["state"] == "needs_review"
    get_settings.cache_clear()
