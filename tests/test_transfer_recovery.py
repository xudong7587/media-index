from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.transfer_recovery import recover_untracked_provider_submissions
from app.services.transfer_service_v2 import _combine_executions


@pytest.fixture
def initialized_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    init_db()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_recovery_closes_only_untracked_external_provider_submissions(initialized_db):
    with db() as conn:
        p115_id = conn.execute(
            """
            INSERT INTO transfer_jobs(media_type,target,provider,status,stage,message)
            VALUES('direct','cloud','p115','triggered','provider_submitting','115 已接受任务')
            """
        ).lastrowid
        moviepilot_id = conn.execute(
            """
            INSERT INTO transfer_jobs(media_type,target,provider,status,stage,message)
            VALUES('movie','cloud','moviepilot_115','triggered','provider_triggered','MoviePilot 已接受任务')
            """
        ).lastrowid
        qas_id = conn.execute(
            """
            INSERT INTO transfer_jobs(media_type,target,provider,status,stage,message)
            VALUES('tv','cloud','qas','triggered','provider_triggered','等待 QAS 确认')
            """
        ).lastrowid

    assert recover_untracked_provider_submissions() == 2

    with db() as conn:
        p115 = conn.execute("SELECT status,stage,message,finished_at FROM transfer_jobs WHERE id=?", (p115_id,)).fetchone()
        moviepilot = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (moviepilot_id,)).fetchone()
        qas = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (qas_id,)).fetchone()

    assert (p115["status"], p115["stage"]) == ("done", "provider_submitted")
    assert "不再持续跟踪" in p115["message"]
    assert p115["finished_at"]
    assert tuple(moviepilot) == ("done", "provider_submitted")
    assert tuple(qas) == ("triggered", "provider_triggered")


def test_p115_pending_message_respects_qas_to_p115_direction():
    execution = SimpleNamespace(ok=True, confirmed=False, stage="provider_triggered", outputs=())
    resolution = SimpleNamespace(rename_pairs=())
    target = SimpleNamespace(media_type="tv", episodes=())
    settings = SimpleNamespace(
        openlist_enabled=True,
        openlist_auto_sync=True,
        openlist_auto_sync_direction="qas_to_p115",
    )

    with patch("app.services.transfer_service_v2.get_settings", return_value=settings):
        p115 = _combine_executions([execution], [resolution], resolution, target, provider="p115")
        qas = _combine_executions([execution], [resolution], resolution, target, provider="qas")

    assert "OpenList 复制" not in p115["message"]
    assert "确认后将发起 OpenList 复制" in qas["message"]


def test_movie_execution_failure_preserves_provider_error():
    execution = SimpleNamespace(
        ok=False,
        confirmed=False,
        stage="provider_failed",
        message="115 创建暂存目录失败（错误码 990002）",
        executed_items=0,
        outputs=(),
    )
    resolution = SimpleNamespace(rename_pairs=(SimpleNamespace(episode_numbers=(), episode_number=None),))
    target = SimpleNamespace(media_type="movie", episodes=())

    result = _combine_executions([execution], [resolution], resolution, target, provider="p115")

    assert not result["ok"]
    assert result["stage"] == "provider_failed"
    assert result["message"] == "链接 1：115 创建暂存目录失败（错误码 990002）"
    assert "0 集" not in result["message"]
