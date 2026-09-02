from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable

from app.db.database import db
from app.domain.media import MediaTarget
from app.services.diagnostics import record_diagnostic_event
from app.services.media_planning import target_episode_coverage
from app.services.notifications import add_notification
from app.services.tracking_registration import TrackingRegistration, register_tracking_task


_PLANNED_EPISODE = re.compile(r"(?i)(?<![a-z0-9])S(\d{1,2})E(\d{1,4})(?!\d)")
_ONGOING_STATUSES = {"Returning Series", "In Production", "Planned", "Pilot"}


@dataclass(frozen=True)
class OrganizedFollowup:
    state: str
    message: str
    tracking_task_id: int | None = None
    missing_episode_numbers: tuple[int, ...] = ()
    total_episode_count: int = 0
    available_episode_count: int = 0


def reconcile_organized_media_followup(
    job_id: int,
    *,
    provider: str,
    target: MediaTarget,
    final_names: Iterable[str],
) -> OrganizedFollowup:
    """Classify one verified formal-library landing without moving files.

    Historical gaps are deliberately not started here. The organizer owns
    transfer and library ingestion; a later explicit decision owns one exact
    PanSou backfill directly into the tracking task's formal-library path.
    """
    if target.media_type not in {"tv", "variety"} or target.season_number is None:
        return OrganizedFollowup("complete", "媒体已完成标准整理和入库流程")

    available = tuple(
        sorted(
            {
                int(match.group(2))
                for name in final_names
                if (match := _PLANNED_EPISODE.search(str(name or "")))
                and int(match.group(1)) == int(target.season_number)
            }
        )
    )
    coverage = target_episode_coverage(target, available=available)
    missing = coverage.missing_episode_numbers
    total_count = len(coverage.total_episode_numbers)
    available_count = len(set(coverage.available_episode_numbers))
    ongoing = str(target.status or "").strip() in _ONGOING_STATUSES
    if not ongoing and not missing:
        result = OrganizedFollowup(
            "complete",
            "已播内容完整，媒体已完成标准整理和入库流程",
            total_episode_count=total_count,
            available_episode_count=available_count,
        )
        _record_followup(job_id, result)
        return result

    try:
        registered = register_tracking_task(
            TrackingRegistration(
                tmdb_id=target.tmdb_id,
                media_type=target.media_type,
                category=target.category,
                title=target.title,
                year=target.series_year,
                poster_url=target.poster_url,
                overview=target.overview,
                season_number=int(target.season_number),
                save_target="cloud",
                provider=provider,
                # Existing gaps belong to the explicit confirmation below;
                # registration only establishes the formal-library task and
                # keeps future episodes eligible for ordinary tracking.
                backfill_existing=False,
            )
        )
        task_id = int(registered["id"])
    except Exception as exc:
        result = OrganizedFollowup(
            "followup_failed",
            f"标准整理和入库已完成，但追更/补集登记失败（{type(exc).__name__}）",
            missing_episode_numbers=missing,
            total_episode_count=total_count,
            available_episode_count=available_count,
        )
        _record_followup(job_id, result, level="warning")
        return result

    if missing:
        preview = "、".join(f"E{number:02d}" for number in missing[:8])
        suffix = " 等" if len(missing) > 8 else ""
        tracking_suffix = "；连载追更已登记" if ongoing else ""
        message = (
            f"已完成转存并入库；本季共 {total_count} 集，正式媒体库已有 {available_count} 集，"
            f"缺 {len(missing)} 集（{preview}{suffix}），是否启动一次补集？"
            f"补集将直接进入正式媒体库，不经过云下载{tracking_suffix}"
        )
        result = OrganizedFollowup(
            "awaiting_backfill_confirmation",
            message,
            task_id,
            missing,
            total_count,
            available_count,
        )
        _persist_backfill_confirmation(job_id, target, result)
    else:
        result = OrganizedFollowup(
            "tracking",
            "当前已播内容完整且仍在连载，已加入智能追更",
            task_id,
            total_episode_count=total_count,
            available_episode_count=available_count,
        )
    _record_followup(job_id, result)
    return result


def organized_backfill_confirmation(job_id: int) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT status,stage,external_provider_status FROM transfer_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()
    if not row:
        raise LookupError("整理任务不存在")
    state = _decode_state(row["external_provider_status"])
    confirmation = state.get("backfill_confirmation")
    if not isinstance(confirmation, dict):
        raise LookupError("该任务没有待处理的缺集确认")
    result = dict(confirmation)
    result["organizer_status"] = str(row["status"] or "")
    result["organizer_stage"] = str(row["stage"] or "")
    return result


def mark_organized_backfill_decision(
    job_id: int,
    decision: str,
    *,
    transfer_job_id: int | None = None,
    message: str = "",
) -> dict[str, Any]:
    if decision not in {"pending", "started", "skipped"}:
        raise ValueError("无效的补集决定")
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()
        if not row:
            raise LookupError("整理任务不存在")
        state = _decode_state(row["external_provider_status"])
        confirmation = state.get("backfill_confirmation")
        if not isinstance(confirmation, dict):
            raise LookupError("该任务没有待处理的缺集确认")
        confirmation["state"] = decision
        if transfer_job_id:
            confirmation["transfer_job_id"] = int(transfer_job_id)
        if message:
            confirmation["decision_message"] = message[:500]
        state["backfill_confirmation"] = confirmation
        conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=?",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )
    return dict(confirmation)


def deliver_organized_backfill_prompt(job_id: int) -> bool:
    """Publish one post-ingestion prompt to the task center and requester."""
    try:
        confirmation = organized_backfill_confirmation(job_id)
    except LookupError:
        return False
    if str(confirmation.get("state") or "") != "pending":
        return False
    title = str(confirmation.get("title") or "媒体")
    season = int(confirmation.get("season_number") or 1)
    message = str(confirmation.get("message") or "")
    add_notification(
        f"organized-backfill:{int(job_id)}",
        "tracking",
        f"{title} S{season:02d} 入库后发现缺集",
        message,
        "workspace/tasks",
        str(confirmation.get("poster_url") or ""),
        deliver=False,
    )

    requester = _organizer_requester(job_id)
    if not requester:
        return True
    request_source, request_user = requester
    options = [
        {"label": "启动一次补集", "decision": "start", "job_id": int(job_id)},
        {"label": "暂不补集", "decision": "skip", "job_id": int(job_id)},
    ]
    from app.services.wecom_callback import _choice_buttons, save_interaction

    save_interaction(request_user, "organizer_backfill", {"options": options})
    body = f"MediaIndex · {title} S{season:02d}\n\n{message}\n\n回复 1 启动补集，回复 2 暂不补集。"
    if request_source == "telegram":
        from app.services.notification_channels import send_telegram

        send_telegram(body, chat_id=request_user, reply_markup=_choice_buttons(options))
    elif request_source == "wecom":
        from app.services.notification_channels import send_wecom_app

        send_wecom_app(body, to_user=request_user)
    return True


def _persist_backfill_confirmation(
    job_id: int,
    target: MediaTarget,
    result: OrganizedFollowup,
) -> None:
    payload = {
        "state": "pending",
        "tracking_task_id": int(result.tracking_task_id or 0),
        "missing_episode_numbers": list(result.missing_episode_numbers),
        "total_episode_count": result.total_episode_count,
        "available_episode_count": result.available_episode_count,
        "tmdb_id": int(target.tmdb_id or 0),
        "media_type": target.media_type,
        "title": target.title,
        "season_number": int(target.season_number or 1),
        "poster_url": target.poster_url,
        "message": result.message,
    }
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()
        if not row:
            return
        state = _decode_state(row["external_provider_status"])
        existing = state.get("backfill_confirmation")
        if isinstance(existing, dict) and str(existing.get("state") or "") in {"started", "skipped"}:
            return
        state["backfill_confirmation"] = payload
        conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=?",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )


def _organizer_requester(job_id: int) -> tuple[str, str] | None:
    with db() as conn:
        organizer = conn.execute(
            "SELECT provider,source_file FROM transfer_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()
        if not organizer:
            return None
        parent = conn.execute(
            """SELECT request_source,request_user FROM transfer_jobs
               WHERE provider=? AND save_path=? AND request_source IN ('telegram','wecom')
                 AND COALESCE(request_user,'')!=''
               ORDER BY id DESC LIMIT 1""",
            (str(organizer["provider"] or ""), str(organizer["source_file"] or "")),
        ).fetchone()
    if not parent:
        return None
    return str(parent["request_source"] or ""), str(parent["request_user"] or "")


def _decode_state(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _record_followup(job_id: int, result: OrganizedFollowup, *, level: str = "info") -> None:
    record_diagnostic_event(
        "tracking",
        "organized_media_followup",
        job_id=int(job_id),
        level=level,
        status=result.state,
        stage="organized_landing_verified",
        message=result.message,
        context={
            "tracking_task_id": result.tracking_task_id,
            "missing_episode_numbers": list(result.missing_episode_numbers),
            "total_episode_count": result.total_episode_count,
            "available_episode_count": result.available_episode_count,
        },
    )
