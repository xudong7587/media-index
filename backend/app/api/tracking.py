from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
import sqlite3
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import require_user
from app.db.database import db
from app.domain.media import EpisodeTarget, MediaTarget
from app.services.media_target import resolve_media_target
from app.services.notifications import add_notification
from app.services.openlist_sync import sync_selected_tracking_episodes, sync_tracking_storage_between_providers
from app.services.paths import build_save_path, is_allowed_save_path
from app.services.saved_episode_scanner import refresh_saved_episodes
from app.services.tracking_engine_v2 import compute_auto_start_episode, compute_next_check, run_tracking_task, sync_tracking_episodes
from app.providers.registry import resolve_provider_key

router = APIRouter(prefix="/api/tracking", tags=["tracking"], dependencies=[Depends(require_user)])


class TrackingCreate(BaseModel):
    tmdb_id: int
    media_type: str
    category: str = ""
    title: str = ""
    year: str = ""
    poster_url: str = ""
    overview: str = ""
    season_number: int = 1
    save_target: str = "cloud"
    provider: str | None = None


class TrackingScheduleUpdate(BaseModel):
    check_time: str


class TrackingProviderUpdate(BaseModel):
    provider: str
    enabled: bool = True


class TrackingSavePathUpdate(BaseModel):
    save_path: str


class TrackingFillRequest(BaseModel):
    episode_numbers: list[int]


class TrackingShareFillRequest(TrackingFillRequest):
    share_url: str


class TrackingSyncSelectedRequest(BaseModel):
    episode_numbers: list[int]


def _normalize_check_time(value: str) -> str:
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="追更时间必须是 HH:MM") from None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise HTTPException(status_code=422, detail="追更时间必须是 HH:MM")
    return f"{hour:02d}:{minute:02d}"


def _normalize_tracking_save_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw.startswith("/"):
        raise HTTPException(status_code=422, detail="保存路径必须是绝对路径")
    parts = [part for part in raw.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=422, detail="保存路径不能包含 . 或 ..")
    return "/" + "/".join(parts)


def _tracking_storage_syncing(tmdb_id: int, media_type: str, season_number: int) -> bool:
    with db() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM transfer_jobs
            WHERE tmdb_id=? AND media_type=? AND season_number=?
              AND provider='openlist' AND status='running' AND stage='openlist_sync'
            LIMIT 1
            """,
            (tmdb_id, media_type, season_number),
        ).fetchone()
    return bool(row)


def _tracking_active_job(task_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT id,status,stage,message FROM transfer_jobs
            WHERE task_id=? AND status IN ('running','triggered')
            ORDER BY id DESC LIMIT 1
            """,
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


def _enqueue_tracking_run(
    task_id: int,
    *,
    selected_episode_numbers: tuple[int, ...] = (),
    request_source: str,
) -> dict:
    episode_key = ",".join(str(number) for number in selected_episode_numbers) or "due"
    execution_key = f"tracking-run:{task_id}:{episode_key}"
    with db() as conn:
        task = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="追更任务不存在")
        existing = conn.execute(
            "SELECT * FROM transfer_jobs WHERE execution_key=? AND status='running' ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if existing:
            return {"ok": True, "id": int(existing["id"]), "status": "running", "stage": existing["stage"], "message": existing["message"], "duplicate": True}
        try:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(
                    task_id,tmdb_id,media_type,display_title,season_number,target,provider,status,stage,message,
                    save_path,execution_key,request_source
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task["id"],
                    task["tmdb_id"],
                    task["media_type"],
                    task["title"],
                    task["season_number"],
                    task["save_target"],
                    task["provider"],
                    "running",
                    "checking_saved",
                    "正在准备追更任务",
                    task["save_path"],
                    execution_key,
                    request_source,
                ),
            ).lastrowid
        except sqlite3.IntegrityError:
            existing = conn.execute(
                "SELECT * FROM transfer_jobs WHERE execution_key=? AND status='running' ORDER BY id DESC LIMIT 1",
                (execution_key,),
            ).fetchone()
            if existing:
                return {"ok": True, "id": int(existing["id"]), "status": "running", "stage": existing["stage"], "message": existing["message"], "duplicate": True}
            raise
    return {
        "ok": True,
        "id": int(job_id),
        "status": "running",
        "stage": "checking_saved",
        "message": "正在准备追更任务",
        "duplicate": False,
    }


def _run_tracking_in_background(
    job_id: int,
    task_id: int,
    *,
    selected_episode_numbers: tuple[int, ...] = (),
    approved_share_url: str = "",
) -> None:
    result = run_tracking_task(
        task_id,
        force=True,
        approved_share_url=approved_share_url,
        selected_episode_numbers=selected_episode_numbers,
        job_id=job_id,
    )
    with db() as conn:
        job = conn.execute("SELECT request_source FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        task = conn.execute("SELECT title,poster_url FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
    if job and job["request_source"] == "tracking_manual":
        _notify_manual_run_result(dict(task) if task else None, result or {})


@router.get("")
def list_tracking():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT t.*,
                   SUM(CASE WHEN e.status='saved' THEN 1 ELSE 0 END) AS saved_count,
                   SUM(
                       CASE
                           WHEN e.status IN ('saved','triggered')
                                AND (COALESCE(e.source_file,'')!='' OR COALESCE(e.rename_to,'')!='')
                           THEN 1 ELSE 0
                       END
                   ) AS triggered_count,
                   COUNT(e.id) AS episode_count
            FROM tracking_tasks t
            LEFT JOIN tracking_episodes e ON e.task_id=t.id
            GROUP BY t.id
            ORDER BY t.created_at DESC
            """
        ).fetchall()
        grouped: dict[tuple[int, str, int], dict] = {}
        for raw in rows:
            row = dict(raw)
            key = (row["tmdb_id"], row["media_type"], row["season_number"])
            state = {
                "id": row["id"],
                "provider": row["provider"],
                "save_target": row["save_target"],
                "save_path": row["save_path"],
                "status": row["status"],
                "decision_state": row["decision_state"],
                "saved_count": row["saved_count"] or 0,
                "triggered_count": row["triggered_count"] or 0,
                "episode_count": row["episode_count"] or 0,
                "last_saved_episode": row["last_saved_episode"] or 0,
                "last_storage_check_at": row["last_storage_check_at"],
                "storage_check_message": row["storage_check_message"],
                "last_error": row["last_error"],
                "storage_syncing": _tracking_storage_syncing(row["tmdb_id"], row["media_type"], row["season_number"]),
                "active_job": _tracking_active_job(row["id"]),
            }
            if key not in grouped:
                row["provider_states"] = [state]
                grouped[key] = row
            else:
                grouped[key]["provider_states"].append(state)
        provider_order = {"qas": 0, "p115": 1}
        for task in grouped.values():
            legacy_qas = [
                state for state in task["provider_states"]
                if state["save_target"] == "local" and not state["provider"]
            ]
            qas_states = [state for state in task["provider_states"] if state["provider"] == "qas"]
            if legacy_qas and qas_states:
                # Legacy local QAS rows are only hidden when a real QAS
                # provider row exists. Progress must always come from the
                # provider's own storage scan, never from inherited history.
                task["provider_states"] = [
                    state for state in task["provider_states"] if state not in legacy_qas
                ]
            elif legacy_qas:
                # Legacy QAS tracking had no provider key. Keep it usable
                # through the new provider facade rather than showing it as a
                # second, anonymous storage row.
                legacy_qas[0]["provider"] = "qas"
                task["provider_states"] = [
                    state for state in task["provider_states"] if state not in legacy_qas[1:]
                ]
            for state in task["provider_states"]:
                state.pop("save_target", None)
            task["provider_states"].sort(key=lambda state: provider_order.get(str(state["provider"]), 99))
        return list(grouped.values())


@router.post("")
def create_tracking(payload: TrackingCreate):
    try:
        provider = resolve_provider_key(payload.save_target, payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        target = resolve_media_target(payload.tmdb_id, payload.media_type, payload.season_number, category=payload.category)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB target resolution failed: {exc}") from exc
    save_path = build_save_path(
        payload.save_target,
        target.category or payload.media_type,
        target.title,
        target.series_year,
        payload.season_number,
        provider,
    )
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM tracking_tasks WHERE tmdb_id=? AND media_type=? AND season_number=? AND provider=?",
            (payload.tmdb_id, payload.media_type, payload.season_number, provider),
        ).fetchone()
        if existing:
            task_id = int(existing["id"])
            conn.execute(
                """
                UPDATE tracking_tasks SET title=?,year=?,poster_url=?,overview=?,category=?,save_target=?,provider=?,save_path=?,
                                          status='active',decision_state='pending',updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    target.title,
                    target.series_year,
                    target.poster_url,
                    target.overview,
                    target.category,
                    payload.save_target,
                    provider,
                    save_path,
                    task_id,
                ),
            )
        else:
            default_check_time = get_settings().tracking_check_time
            cur = conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,category,title,year,poster_url,overview,season_number,
                    save_target,provider,save_path,check_time,status,decision_state
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'active','pending')
                """,
                (
                    payload.tmdb_id,
                    payload.media_type,
                    target.category,
                    target.title,
                    target.series_year,
                    target.poster_url,
                    target.overview,
                    payload.season_number,
                    payload.save_target,
                    provider,
                    save_path,
                    default_check_time,
                ),
            )
            task_id = int(cur.lastrowid)
    sync_tracking_episodes(task_id, target, provider=provider)
    refresh_saved_episodes(task_id)
    with db() as conn:
        rows = conn.execute(
            "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
            (task_id,),
        ).fetchall()
        statuses = {row["episode_number"]: row["status"] for row in rows}
        task = conn.execute("SELECT check_time FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        check_time = task["check_time"] if task else None
        auto_start_episode = compute_auto_start_episode(target, statuses, check_time=check_time)
        next_check = compute_next_check(target, statuses, check_time=check_time, progress_floor=auto_start_episode)
        conn.execute(
            "UPDATE tracking_tasks SET auto_start_episode=?,next_check_at=? WHERE id=?",
            (auto_start_episode, next_check or None, task_id),
        )
    return {"ok": True, "id": task_id, "next_check_at": next_check, "provider": provider}


@router.patch("/{task_id}/schedule")
def update_schedule(task_id: int, payload: TrackingScheduleUpdate):
    check_time = _normalize_check_time(payload.check_time)
    with db() as conn:
        task_row = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="追更任务不存在")
    task = dict(task_row)
    try:
        target = resolve_media_target(task["tmdb_id"], task["media_type"], task["season_number"])
        sync_tracking_episodes(task_id, target)
    except Exception:
        # Time settings remain editable even during a temporary TMDB outage.
        # Existing episode metadata is enough to recalculate the next check.
        with db() as conn:
            cached_episodes = conn.execute(
                "SELECT season_number,episode_number,air_date,title FROM tracking_episodes WHERE task_id=? ORDER BY episode_number",
                (task_id,),
            ).fetchall()
        target = MediaTarget(
            tmdb_id=task["tmdb_id"],
            media_type=task["media_type"],
            title=task["title"],
            season_number=task["season_number"],
            episodes=tuple(
                EpisodeTarget(row["season_number"], row["episode_number"], row["air_date"], row["title"])
                for row in cached_episodes
            ),
        )
    with db() as conn:
        rows = conn.execute(
            "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
            (task_id,),
        ).fetchall()
        statuses = {row["episode_number"]: row["status"] for row in rows}
        auto_start_episode = compute_auto_start_episode(target, statuses, check_time=check_time)
        progress_floor = max(auto_start_episode, int(task.get("last_saved_episode") or 0))
        next_check = compute_next_check(target, statuses, check_time=check_time, progress_floor=progress_floor)
        conn.execute(
            "UPDATE tracking_tasks SET check_time=?,auto_start_episode=?,next_check_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (check_time, auto_start_episode, next_check or None, task_id),
        )
    return {"ok": True, "check_time": check_time, "next_check_at": next_check}


@router.patch("/{task_id}/provider")
def update_provider(task_id: int, payload: TrackingProviderUpdate):
    try:
        provider = resolve_provider_key("cloud", payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with db() as conn:
        row = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="追更任务不存在")
        task = dict(row)
    with db() as conn:
        sibling = conn.execute(
            """
            SELECT id FROM tracking_tasks
            WHERE tmdb_id=? AND media_type=? AND season_number=?
              AND (provider=? OR (?='qas' AND save_target='local' AND COALESCE(provider,'')=''))
            ORDER BY CASE WHEN provider=? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (task["tmdb_id"], task["media_type"], task["season_number"], provider, provider, provider),
        ).fetchone()
        siblings = conn.execute(
            "SELECT COUNT(*) FROM tracking_tasks WHERE tmdb_id=? AND media_type=? AND season_number=?",
            (task["tmdb_id"], task["media_type"], task["season_number"]),
        ).fetchone()[0]
    if not payload.enabled:
        if not sibling:
            return {"ok": True, "provider": provider, "enabled": False}
        if siblings <= 1:
            raise HTTPException(status_code=422, detail="至少保留一个追更网盘")
        with db() as conn:
            conn.execute("DELETE FROM tracking_episodes WHERE task_id=?", (sibling["id"],))
            conn.execute("DELETE FROM tracking_tasks WHERE id=?", (sibling["id"],))
        return {"ok": True, "provider": provider, "enabled": False}
    if sibling:
        return {"ok": True, "provider": provider, "enabled": True, "id": int(sibling["id"])}

    save_path = build_save_path(
        "cloud", task.get("category") or task["media_type"], task["title"], task.get("year") or "", task["season_number"], provider
    )
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO tracking_tasks(
                tmdb_id,media_type,category,title,year,poster_url,overview,season_number,
                save_target,provider,save_path,status,decision_state,check_time
            ) VALUES(?,?,?,?,?,?,?,?,'cloud',?,?,'active','pending',?)
            """,
            (
                task["tmdb_id"], task["media_type"], task.get("category") or "", task["title"],
                task.get("year") or "", task.get("poster_url") or "", task.get("overview") or "",
                task["season_number"], provider, save_path, task.get("check_time") or "10:00",
            ),
        )
        new_id = int(cur.lastrowid)
    try:
        target = resolve_media_target(task["tmdb_id"], task["media_type"], task["season_number"], category=task.get("category") or "")
        sync_tracking_episodes(new_id, target, provider=provider)
        refresh_saved_episodes(new_id)
    except Exception:
        # The provider remains enabled; the scheduler can retry metadata/storage refresh.
        pass
    else:
        with db() as conn:
            rows = conn.execute(
                "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
                (new_id,),
            ).fetchall()
            statuses = {row["episode_number"]: row["status"] for row in rows}
            auto_start_episode = compute_auto_start_episode(target, statuses, check_time=task.get("check_time") or "10:00")
            next_check = compute_next_check(
                target,
                statuses,
                check_time=task.get("check_time") or "10:00",
                progress_floor=auto_start_episode,
            )
            conn.execute(
                "UPDATE tracking_tasks SET auto_start_episode=?,next_check_at=? WHERE id=?",
                (auto_start_episode, next_check or None, new_id),
            )
    return {"ok": True, "provider": provider, "enabled": True, "id": new_id, "save_path": save_path}


@router.patch("/{task_id}/save-path")
def update_tracking_save_path(task_id: int, payload: TrackingSavePathUpdate):
    with db() as conn:
        row = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="追更任务不存在")
    task = dict(row)
    provider = str(task.get("provider") or "").strip().lower()
    if provider not in {"qas", "p115"}:
        raise HTTPException(status_code=422, detail="仅支持修改夸克或 115 的追更保存路径")
    save_path = _normalize_tracking_save_path(payload.save_path)
    category = str(task.get("category") or task.get("media_type") or "")
    if not is_allowed_save_path(category, save_path, "cloud", provider):
        raise HTTPException(status_code=422, detail="保存路径必须位于该网盘对应的媒体分类目录内")
    with db() as conn:
        conn.execute(
            "UPDATE tracking_tasks SET save_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (save_path, task_id),
        )
    result = refresh_saved_episodes(task_id)
    return {
        "ok": True,
        "save_path": save_path,
        "storage_refreshed": bool(result.get("ok")),
        "message": str(result.get("message") or "保存路径已更新"),
    }


@router.get("/{task_id}/episodes")
def list_tracking_episodes(task_id: int):
    with db() as conn:
        task = conn.execute("SELECT id,provider,season_number,save_path FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="追更任务不存在")
        rows = conn.execute(
            "SELECT episode_number,air_date,title,status FROM tracking_episodes WHERE task_id=? ORDER BY episode_number",
            (task_id,),
        ).fetchall()
    try:
        today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date()
    except ZoneInfoNotFoundError:
        today = datetime.now(timezone.utc).date()
    episodes = []
    for row in rows:
        episode = dict(row)
        try:
            episode["aired"] = bool(episode["air_date"] and datetime.fromisoformat(episode["air_date"]).date() <= today)
        except (TypeError, ValueError):
            episode["aired"] = False
        episodes.append(episode)
    return {
        "provider": task["provider"],
        "season_number": task["season_number"],
        "save_path": task["save_path"],
        "episodes": episodes,
    }


@router.post("/{task_id}/fill")
def fill_missing_episodes(task_id: int, payload: TrackingFillRequest, background_tasks: BackgroundTasks):
    selected = tuple(sorted({number for number in payload.episode_numbers if number > 0}))
    if not selected:
        raise HTTPException(status_code=422, detail="请至少选择一集")
    response = _enqueue_tracking_run(task_id, selected_episode_numbers=selected, request_source="tracking_fill")
    if not response["duplicate"]:
        background_tasks.add_task(
            _run_tracking_in_background,
            int(response["id"]),
            task_id,
            selected_episode_numbers=selected,
        )
    return response


@router.post("/{task_id}/fill-from-share")
def fill_missing_episodes_from_share(task_id: int, payload: TrackingShareFillRequest, background_tasks: BackgroundTasks):
    selected = tuple(sorted({number for number in payload.episode_numbers if number > 0}))
    share_url = payload.share_url.strip()
    if not selected:
        raise HTTPException(status_code=422, detail="请至少选择一集")
    if not share_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="请填写完整分享链接")
    response = _enqueue_tracking_run(task_id, selected_episode_numbers=selected, request_source="tracking_share_fill")
    if not response["duplicate"]:
        background_tasks.add_task(
            _run_tracking_in_background,
            int(response["id"]),
            task_id,
            selected_episode_numbers=selected,
            approved_share_url=share_url,
        )
    return response


@router.post("/{task_id}/run")
def run_now(task_id: int, background_tasks: BackgroundTasks = None):
    response = _enqueue_tracking_run(task_id, request_source="tracking_manual")
    if not response["duplicate"]:
        if background_tasks is None:
            # Keep direct callers (CLI/tests) synchronous while the HTTP route
            # still returns immediately through FastAPI BackgroundTasks.
            _run_tracking_in_background(int(response["id"]), task_id)
        else:
            background_tasks.add_task(_run_tracking_in_background, int(response["id"]), task_id)
    return response


def _notify_manual_run_result(task: dict | None, result: dict) -> None:
    title = str((task or {}).get("title") or "追更任务")
    stage = str(result.get("stage") or "internal_error")
    message = str(result.get("message") or "")
    notification_type = "info"
    notification_title = f"{title} 手动追更检查完成"

    if stage == "not_due":
        message = "当前没有已播出且尚未保存的新内容。"
        if result.get("next_check_at"):
            message += f" 下次巡检：{_format_check_at(str(result['next_check_at']))}"
    elif stage == "not_runnable":
        notification_type = "warning"
        notification_title = f"{title} 暂时无法手动追更"
        message = message or "任务可能已暂停、正在运行或等待人工确认。"
    elif stage == "retry_wait":
        notification_type = "warning"
        notification_title = f"{title} 本次未找到可转存资源"
        message = message or "系统将按重试计划继续换源。"
    elif stage == "storage_check_failed":
        notification_type = "error"
        notification_title = f"{title} 网盘检查失败"
        message = message or "读取目标目录失败，请检查 QAS 连接与保存路径。"
    elif stage in {"not_found", "internal_error"} or not result.get("ok"):
        notification_type = "error"
        notification_title = f"{title} 手动追更失败"
        message = message or "执行过程中发生错误，请稍后重试。"

    add_notification(
        source_key=f"tracking:{(task or {}).get('id', 0)}:manual:{datetime.now(timezone.utc).isoformat(timespec='microseconds')}",
        notification_type=notification_type,
        title=notification_title,
        message=message,
        action_page="tracking",
        poster_url=str((task or {}).get("poster_url") or ""),
    )


def _format_check_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local = parsed.astimezone(ZoneInfo(get_settings().tracking_timezone))
        return local.strftime("%m月%d日 %H:%M")
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return value


@router.post("/{task_id}/refresh-storage")
def refresh_storage(task_id: int):
    result = refresh_saved_episodes(task_id)
    if not result.get("ok"):
        status_code = 404 if result.get("message") == "追更任务不存在" else 503
        raise HTTPException(status_code=status_code, detail=result.get("message", "storage check failed"))
    return result


@router.post("/{task_id}/sync-storage")
def sync_storage(task_id: int):
    result = sync_tracking_storage_between_providers(task_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "sync storage failed"))
    return result


@router.post("/{task_id}/sync-selected")
def sync_selected(task_id: int, payload: TrackingSyncSelectedRequest):
    result = sync_selected_tracking_episodes(task_id, payload.episode_numbers)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "sync selected failed"))
    return result


@router.post("/{task_id}/pause")
def pause_tracking(task_id: int):
    with db() as conn:
        conn.execute(
            "UPDATE tracking_tasks SET status='paused',decision_state='paused',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id,),
        )
    return {"ok": True}


@router.post("/{task_id}/resume")
def resume_tracking(task_id: int):
    with db() as conn:
        task_row = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="追更任务不存在")
    task = dict(task_row)
    try:
        target = resolve_media_target(task["tmdb_id"], task["media_type"], task["season_number"], category=task.get("category") or "")
        sync_tracking_episodes(task_id, target, provider=task.get("provider") or "")
    except Exception:
        with db() as conn:
            cached_episodes = conn.execute(
                "SELECT season_number,episode_number,air_date,title FROM tracking_episodes WHERE task_id=? ORDER BY episode_number",
                (task_id,),
            ).fetchall()
        target = MediaTarget(
            tmdb_id=task["tmdb_id"],
            media_type=task["media_type"],
            title=task["title"],
            season_number=task["season_number"],
            episodes=tuple(
                EpisodeTarget(row["season_number"], row["episode_number"], row["air_date"], row["title"])
                for row in cached_episodes
            ),
        )
    with db() as conn:
        rows = conn.execute(
            "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
            (task_id,),
        ).fetchall()
        statuses = {row["episode_number"]: row["status"] for row in rows}
        auto_start_episode = int(task.get("auto_start_episode") or 0)
        if not auto_start_episode:
            auto_start_episode = compute_auto_start_episode(target, statuses, check_time=task.get("check_time"))
        progress_floor = max(auto_start_episode, int(task.get("last_saved_episode") or 0))
        next_check = compute_next_check(target, statuses, check_time=task.get("check_time"), progress_floor=progress_floor)
        conn.execute(
            """
            UPDATE tracking_tasks SET status='active',decision_state='pending',auto_start_episode=?,
                                      next_check_at=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (auto_start_episode, next_check or None, task_id),
        )
    return {"ok": True}


@router.delete("/{task_id}")
def delete_tracking(task_id: int):
    with db() as conn:
        conn.execute("DELETE FROM tracking_episodes WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM tracking_tasks WHERE id=?", (task_id,))
    return {"ok": True}
