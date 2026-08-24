from __future__ import annotations

from datetime import datetime, timezone

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
    ) or _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone=settings.tracking_timezone)
    if settings.tracking_scheduler_enabled:
        _scheduler.add_job(
            run_due_tracking_tasks,
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
            run_due_wishlist_items,
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
    _scheduler.start()
    return _scheduler


def run_scheduled_strm_scan(provider: str) -> None:
    settings = get_settings()
    normalized = "p115" if provider == "p115" else "quark"
    if not bool(getattr(settings, f"{normalized}_strm_enabled", False)):
        return
    source_root = settings.provider_strm_source_root(normalized)
    output_root = settings.strm_output_root.strip()
    if not source_root or not output_root:
        return
    job_id = create_strm_job(
        provider=normalized,
        mode="incremental",
        root_path=source_root,
        output_root=output_root,
        playback_base_url=settings.strm_playback_base_url or None,
        include_directories=settings.provider_strm_included_directories(normalized),
    )
    run_strm_job(
        job_id,
        provider=normalized,
        mode="incremental",
        root_path=source_root,
        output_root=output_root,
        playback_base_url=settings.strm_playback_base_url or None,
        include_directories=settings.provider_strm_included_directories(normalized),
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
