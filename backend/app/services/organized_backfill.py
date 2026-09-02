from __future__ import annotations

import threading

from app.services.organized_media_followup import (
    mark_organized_backfill_decision,
    organized_backfill_confirmation,
)
from app.services.tracking_engine_v2 import run_tracking_task
from app.services.tracking_run_dispatch import enqueue_tracking_run


def decide_organized_backfill(organizer_job_id: int, *, start: bool) -> dict:
    """Resolve a post-ingestion choice and dispatch a separate tracking job."""
    confirmation = organized_backfill_confirmation(organizer_job_id)
    if confirmation.get("organizer_status") != "done" or confirmation.get("organizer_stage") != "organizer_completed":
        raise RuntimeError("正式媒体库入库尚未完成，不能启动补集")
    state = str(confirmation.get("state") or "pending")
    if state == "started":
        return {
            "ok": True,
            "status": "started",
            "id": int(confirmation.get("transfer_job_id") or 0),
            "message": str(confirmation.get("decision_message") or "补集任务已启动"),
            "duplicate": True,
        }
    if state == "skipped":
        return {
            "ok": True,
            "status": "skipped",
            "message": "本次已选择暂不补集；正式媒体库内容保持不变",
            "duplicate": True,
        }
    if not start:
        message = "已暂不补集；转存与入库结果保持完成，后续连载追更不受影响"
        mark_organized_backfill_decision(organizer_job_id, "skipped", message=message)
        return {"ok": True, "status": "skipped", "message": message, "duplicate": False}

    selected = _positive_episode_numbers(confirmation.get("missing_episode_numbers") or ())
    task_id = int(confirmation.get("tracking_task_id") or 0)
    if not task_id or not selected:
        raise RuntimeError("补集上下文不完整，请在智能追更中重新扫描缺集")
    response = enqueue_tracking_run(
        task_id,
        selected_episode_numbers=selected,
        request_source="organized_backfill",
    )
    preview = "、".join(f"E{number:02d}" for number in selected[:8])
    suffix = " 等" if len(selected) > 8 else ""
    message = f"已启动一次补集（{preview}{suffix}）；PanSou 命中后将直接写入正式媒体库，不经过云下载"
    mark_organized_backfill_decision(
        organizer_job_id,
        "started",
        transfer_job_id=int(response["id"]),
        message=message,
    )
    if not response["duplicate"]:
        threading.Thread(
            target=run_tracking_task,
            kwargs={
                "task_id": task_id,
                "force": True,
                "selected_episode_numbers": selected,
                "job_id": int(response["id"]),
            },
            name=f"media-index-organized-backfill-{organizer_job_id}",
            daemon=True,
        ).start()
    return {**response, "status": "started", "message": message}


def _positive_episode_numbers(values) -> tuple[int, ...]:
    result: set[int] = set()
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.add(number)
    return tuple(sorted(result))
