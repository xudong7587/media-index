from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.db.database import db
from app.services.tracking_engine_v2 import run_due_tracking_tasks
from app.services.wishlist_engine import run_due_wishlist_items
from app.services.notifications import deliver_pending_library_notifications, sync_transfer_notifications
from app.services.saved_episode_scanner import refresh_saved_episodes
from app.services.emby_library_covers import refresh_all_library_covers
from app.services.strm_jobs import create_strm_job, run_strm_job
from app.services.p115_life_monitor import poll_p115_life_events


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if not (
        settings.tracking_scheduler_enabled
        or settings.wishlist_scheduler_enabled
        or settings.notification_external_enabled
        or settings.emby_cover_refresh_enabled
        or bool(str(getattr(settings, "p115_strm_incremental_cron", "") or "").strip())
        or bool(str(getattr(settings, "quark_strm_incremental_cron", "") or "").strip())
        or bool(getattr(settings, "p115_strm_life_monitor_enabled", False))
        or bool(getattr(settings, "mdc_webhook_enabled", False))
    ) or _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone=settings.tracking_timezone)
    if settings.tracking_scheduler_enabled:
        _scheduler.add_job(
            run_scheduled_tracking_patrol,
            "interval",
            minutes=max(1, settings.tracking_poll_minutes),
            id="media-index-tracking",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            # Do not leave yesterday's overdue cards waiting for their first
            # interval after a restart or an enabled scheduler.
            next_run_time=datetime.now(timezone.utc),
        )
        _scheduler.add_job(
            refresh_tracking_storage,
            "interval",
            minutes=max(1, settings.tracking_poll_minutes),
            id="media-index-tracking-storage",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if settings.wishlist_scheduler_enabled:
        _scheduler.add_job(
            run_scheduled_wishlist_patrol,
            "interval",
            minutes=max(1, settings.wishlist_poll_minutes),
            id="media-index-wishlist",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if settings.notification_external_enabled:
        _scheduler.add_job(
            sync_transfer_notifications,
            "interval",
            minutes=1,
            id="media-index-notifications",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if settings.emby_cover_refresh_enabled:
        _scheduler.add_job(
            refresh_all_library_covers,
            "interval",
            hours=max(1, settings.emby_cover_refresh_hours),
            id="media-index-emby-covers",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.add_job(
            deliver_pending_library_notifications,
            "interval",
            minutes=1,
            id="media-index-library-notifications",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    for provider in ("p115", "quark"):
        cron = str(getattr(settings, f"{provider}_strm_incremental_cron", "") or "").strip()
        if not cron:
            continue
        _scheduler.add_job(
            run_scheduled_strm_scan,
            CronTrigger.from_crontab(cron, timezone=settings.tracking_timezone),
            args=[provider],
            id=f"media-index-{provider}-strm-incremental",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if getattr(settings, "p115_strm_life_monitor_enabled", False):
        _scheduler.add_job(
            run_scheduled_p115_life_monitor,
            "interval",
            seconds=max(30, min(int(settings.p115_strm_life_monitor_interval_seconds), 3600)),
            id="media-index-p115-life-monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if getattr(settings, "mdc_webhook_enabled", False):
        with db() as conn:
            pending = conn.execute(
                """SELECT id,execution_key,source_file FROM transfer_jobs
                   WHERE status='ready' AND stage IN ('webhook_waiting','mdc_webhook_waiting')
                     AND request_source IN ('webhook','mdc-ng')
                   ORDER BY id DESC LIMIT 20"""
            ).fetchall()
        for row in pending:
            parts = str(row["execution_key"] or "").split(":", 2)
            provider = parts[1] if len(parts) == 3 and parts[1] in {"p115", "quark"} else settings.mdc_webhook_provider
            _add_webhook_job(
                _scheduler,
                int(row["id"]),
                provider,
                str(row["source_file"] or "") or settings.provider_strm_source_root(provider),
                int(settings.mdc_webhook_debounce_seconds),
            )
    _scheduler.start()
    return _scheduler


def run_scheduled_tracking_patrol() -> Any:
    return _run_scheduled_activity("tracking", "智能追更巡检", run_due_tracking_tasks)


def run_scheduled_wishlist_patrol() -> Any:
    return _run_scheduled_activity("wishlist", "愿望单巡检", run_due_wishlist_items)


def run_scheduled_p115_life_monitor() -> Any:
    return _run_scheduled_activity("p115-life", "115 生活监控", poll_p115_life_events)


def _run_scheduled_activity(key: str, title: str, operation: Callable[[], Any]) -> Any:
    execution_key = f"scheduled:{key}"
    with db() as conn:
        row = conn.execute("SELECT id FROM transfer_jobs WHERE execution_key=? ORDER BY id DESC LIMIT 1", (execution_key,)).fetchone()
        if row:
            job_id = int(row["id"])
            conn.execute(
                """UPDATE transfer_jobs SET provider='scheduler',target='cloud',status='running',stage='scheduled_running',
                   message='计划任务正在执行',display_title=?,request_source='scheduler',created_at=CURRENT_TIMESTAMP,finished_at=NULL WHERE id=?""",
                (title, job_id),
            )
        else:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,request_source,execution_key)
                   VALUES('cloud','scheduler','running','scheduled_running','计划任务正在执行',?,'scheduler',?)""",
                (title, execution_key),
            )
            job_id = int(cursor.lastrowid)
    try:
        result = operation()
        message = _scheduled_result_message(result)
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET status='done',stage='scheduled_completed',message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (message, job_id),
            )
        return result
    except Exception as exc:
        message = f"计划任务失败：{type(exc).__name__}"
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET status='failed',stage='scheduled_failed',message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (message, job_id),
            )
        raise


def _scheduled_result_message(result: Any) -> str:
    if isinstance(result, list):
        return f"本轮巡检完成，处理 {len(result)} 项"
    if isinstance(result, dict):
        if result.get("triggered"):
            return "本轮监控发现变化并已触发 STRM 增量更新"
        reasons = {"baseline": "已建立监控基线", "unchanged": "未发现变化", "disabled": "监控已关闭", "incomplete": "监控配置不完整", "busy": "上一轮仍在执行", "error": "读取 115 生活事件失败"}
        return reasons.get(str(result.get("reason") or ""), "本轮计划任务已完成")
    return "本轮计划任务已完成"


def run_scheduled_strm_scan(provider: str) -> None:
    settings = get_settings()
    normalized = "p115" if provider == "p115" else "quark"
    if not bool(getattr(settings, f"{normalized}_strm_enabled", False)):
        return
    source_root = settings.provider_strm_source_root(normalized)
    output_root = settings.strm_output_root.strip()
    included_directories = settings.provider_strm_included_directories(normalized)
    if not source_root or not output_root or not included_directories:
        return
    job_id = create_strm_job(
        provider=normalized,
        mode="incremental",
        root_path=source_root,
        output_root=output_root,
        playback_base_url=settings.strm_playback_base_url or None,
        include_directories=included_directories,
    )
    run_strm_job(
        job_id,
        provider=normalized,
        mode="incremental",
        root_path=source_root,
        output_root=output_root,
        playback_base_url=settings.strm_playback_base_url or None,
        include_directories=included_directories,
    )


def schedule_interaction_strm_scans(mode: str) -> list[dict[str, Any]]:
    selected_mode = "full" if mode == "full" else "incremental"
    settings = get_settings()
    scheduler = start_scheduler()
    if scheduler is None:
        raise RuntimeError("STRM 调度器未启动")
    jobs: list[dict[str, Any]] = []
    for provider in ("p115", "quark"):
        if not bool(getattr(settings, f"{provider}_strm_enabled", False)):
            continue
        root_path = settings.provider_strm_source_root(provider)
        output_root = settings.strm_output_root.strip()
        included_directories = settings.provider_strm_included_directories(provider)
        if not root_path or not output_root or not included_directories:
            jobs.append({"provider": provider, "ok": False, "message": "未配置已勾选的扫描子目录"})
            continue
        job_id = create_strm_job(
            provider=provider,
            mode=selected_mode,
            root_path=root_path,
            output_root=output_root,
            playback_base_url=settings.strm_playback_base_url or None,
            include_directories=included_directories,
        )
        scheduler.add_job(
            run_strm_job,
            args=[job_id],
            kwargs={
                "provider": provider,
                "mode": selected_mode,
                "root_path": root_path,
                "output_root": output_root,
                "playback_base_url": settings.strm_playback_base_url or None,
                "include_directories": included_directories,
            },
            id=f"media-index-interaction-strm-{provider}-{job_id}",
            replace_existing=False,
        )
        jobs.append({"provider": provider, "ok": True, "job_id": job_id})
    return jobs


def schedule_webhook_incremental_sync(provider: str, root_path: str, debounce_seconds: int) -> dict[str, Any]:
    """Coalesce external completion events into one non-destructive incremental scan."""
    normalized = "p115" if provider == "p115" else "quark"
    root = str(root_path or "").strip()
    settings = get_settings()
    output_root = settings.strm_output_root.strip()
    included_directories = settings.provider_strm_included_directories(normalized)
    if not root or not output_root or not included_directories:
        raise ValueError("Webhook 增量同步目录、STRM 输出目录或已勾选的扫描子目录未配置")
    execution_key = f"strm-webhook:{normalized}:{hashlib.sha256(root.encode('utf-8')).hexdigest()[:16]}"
    with db() as conn:
        waiting = conn.execute(
            "SELECT id FROM transfer_jobs WHERE execution_key=? AND status='ready' AND stage='webhook_waiting' ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if waiting:
            job_id = int(waiting["id"])
            conn.execute(
                """UPDATE transfer_jobs SET message='已收到新的刮削完成事件，重新计算合并等待时间',
                   created_at=CURRENT_TIMESTAMP,finished_at=NULL WHERE id=?""",
                (job_id,),
            )
            coalesced = True
        else:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,save_path,source_file,
                       request_source,execution_key)
                   VALUES('local','strm','ready','webhook_waiting','等待合并同批次完成事件',
                          'Webhook 增量同步',?,?, 'webhook',?)""",
                (output_root, root, execution_key),
            )
            job_id = int(cursor.lastrowid)
            coalesced = False
    scheduler = start_scheduler()
    if scheduler is None:
        raise RuntimeError("Webhook 增量同步调度器未启动")
    _add_webhook_job(scheduler, job_id, normalized, root, debounce_seconds)
    return {"job_id": job_id, "coalesced": coalesced, "provider": normalized, "root_path": root}


def _add_webhook_job(scheduler: BackgroundScheduler, job_id: int, provider: str, root_path: str, debounce_seconds: int) -> None:
    execution_key = f"strm-webhook:{provider}:{hashlib.sha256(root_path.encode('utf-8')).hexdigest()[:16]}"
    scheduler.add_job(
        run_webhook_incremental_sync,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=max(5, min(int(debounce_seconds), 600))),
        args=[job_id, provider, root_path],
        id=f"media-index-{execution_key}",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )


def run_webhook_incremental_sync(job_id: int, provider: str, root_path: str) -> None:
    settings = get_settings()
    normalized = "p115" if provider == "p115" else "quark"
    included_directories = settings.provider_strm_included_directories(normalized)
    if not included_directories:
        with db() as conn:
            conn.execute(
                """UPDATE transfer_jobs
                   SET status='failed',stage='strm_scope_missing',
                       message='未配置已勾选的 STRM 扫描子目录，已拒绝回退为整盘扫描',
                       finished_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (int(job_id),),
            )
        return
    run_strm_job(
        int(job_id),
        provider=normalized,
        mode="incremental",
        root_path=root_path,
        output_root=settings.strm_output_root.strip(),
        playback_base_url=settings.strm_playback_base_url or None,
        include_directories=included_directories,
    )


def refresh_tracking_storage() -> list[dict]:
    """Refresh active tracking cards without triggering resource searches."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id FROM tracking_tasks WHERE status='active' ORDER BY id"
        ).fetchall()
    results = []
    for row in rows:
        try:
            results.append(refresh_saved_episodes(int(row["id"])))
        except Exception as exc:
            results.append({"ok": False, "task_id": int(row["id"]), "message": type(exc).__name__})
    return results


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
