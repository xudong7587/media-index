from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.services.tracking_engine_v2 import run_due_tracking_tasks
from app.services.wishlist_engine import run_due_wishlist_items
from app.services.qas_reconciler import reconcile_triggered_jobs


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if not (settings.tracking_scheduler_enabled or settings.wishlist_scheduler_enabled) or _scheduler is not None:
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
    _scheduler.add_job(
        reconcile_triggered_jobs,
        "interval",
        minutes=max(1, min(settings.tracking_poll_minutes, settings.wishlist_poll_minutes)),
        id="media-index-qas-reconcile",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
