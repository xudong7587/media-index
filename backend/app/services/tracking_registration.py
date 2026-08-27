from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.database import db
from app.providers.registry import resolve_provider_key
from app.services.media_target import resolve_media_target
from app.services.saved_episode_scanner import refresh_saved_episodes
from app.services.tracking_save_path import resolve_tracking_save_path
from app.services.tracking_engine_v2 import compute_auto_start_episode, compute_next_check, sync_tracking_episodes


class TrackingProviderResolutionError(ValueError):
    pass


class TrackingTargetResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrackingRegistration:
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
    check_time: str = ""
    backfill_existing: bool = False


def register_tracking_task(request: TrackingRegistration) -> dict:
    """Create or reactivate one provider-specific tracking task.

    This is the shared application entry used by both the HTTP route and
    interactive notification channels. Episode dates remain authoritative
    from TMDB through ``resolve_media_target``/``sync_tracking_episodes``.
    """

    try:
        provider = resolve_provider_key(request.save_target, request.provider)
    except ValueError as exc:
        raise TrackingProviderResolutionError(str(exc)) from exc
    try:
        target = resolve_media_target(
            request.tmdb_id,
            request.media_type,
            request.season_number,
            category=request.category,
        )
    except Exception as exc:
        raise TrackingTargetResolutionError(f"TMDB target resolution failed: {exc}") from exc

    settings = get_settings()
    configured_check_time = request.check_time.strip() or settings.tracking_check_time
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM tracking_tasks WHERE tmdb_id=? AND media_type=? AND season_number=? AND provider=?",
            (request.tmdb_id, request.media_type, request.season_number, provider),
        ).fetchone()
        preserve_execution_state = bool(
            existing
            and str(existing["decision_state"] or "") in {"running", "needs_review", "awaiting_confirmation"}
        )
        preserved_auto_start = int(existing["auto_start_episode"] or 0) if existing else 0
        preserved_next_check = str(existing["next_check_at"] or "") if existing else ""
        save_path = resolve_tracking_save_path(
            str(existing["save_path"] or "") if existing else "",
            save_target=request.save_target,
            media_type=target.category or request.media_type,
            title=target.title,
            year=target.series_year,
            season_number=request.season_number,
            provider=provider,
        )
        if existing:
            task_id = int(existing["id"])
            task_check_time = request.check_time.strip() or str(existing["check_time"] or configured_check_time)
            conn.execute(
                """
                UPDATE tracking_tasks SET title=?,year=?,poster_url=?,overview=?,category=?,save_target=?,provider=?,save_path=?,
                                          check_time=?,status='active',
                                          decision_state=CASE
                                            WHEN decision_state IN ('running','needs_review','awaiting_confirmation') THEN decision_state
                                            ELSE 'pending'
                                          END,
                                          updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    target.title,
                    target.series_year,
                    target.poster_url,
                    target.overview,
                    target.category,
                    request.save_target,
                    provider,
                    save_path,
                    task_check_time,
                    task_id,
                ),
            )
        else:
            task_check_time = configured_check_time
            task_id = int(
                conn.execute(
                    """
                    INSERT INTO tracking_tasks(
                        tmdb_id,media_type,category,title,year,poster_url,overview,season_number,
                        save_target,provider,save_path,check_time,status,decision_state
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'active','pending')
                    """,
                    (
                        request.tmdb_id,
                        request.media_type,
                        target.category,
                        target.title,
                        target.series_year,
                        target.poster_url,
                        target.overview,
                        request.season_number,
                        request.save_target,
                        provider,
                        save_path,
                        task_check_time,
                    ),
                ).lastrowid
            )

    sync_tracking_episodes(task_id, target, provider=provider)
    refresh_saved_episodes(task_id)
    with db() as conn:
        rows = conn.execute(
            "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
            (task_id,),
        ).fetchall()
        statuses = {row["episode_number"]: row["status"] for row in rows}
        # "加入智能追更" starts a linked native transfer immediately after
        # registration. That transfer may fail or cover only part of the
        # already-aired season, so those episodes must remain eligible for a
        # later tracking run instead of being hidden behind the registration
        # time floor.
        auto_start_episode = (
            preserved_auto_start
            if preserve_execution_state
            else 0
            if request.backfill_existing
            else compute_auto_start_episode(target, statuses, check_time=task_check_time)
        )
        next_check = (
            preserved_next_check
            if preserve_execution_state
            else compute_next_check(
                target,
                statuses,
                check_time=task_check_time,
                progress_floor=auto_start_episode,
            )
        )
        if request.backfill_existing and next_check and not preserve_execution_state:
            current = datetime.now(timezone.utc)
            scheduled = datetime.fromisoformat(next_check.replace("Z", "+00:00"))
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            # The linked first-transfer batch owns the immediate catch-up. Give
            # it one retry interval before the scheduler can enter the same
            # season; its task_id association still guards longer-running jobs.
            if scheduled <= current + timedelta(minutes=1):
                next_check = (
                    current + timedelta(minutes=max(1, settings.tracking_retry_interval_minutes))
                ).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE tracking_tasks SET auto_start_episode=?,next_check_at=? WHERE id=?",
            (auto_start_episode, next_check or None, task_id),
        )
    return {
        "ok": True,
        "id": task_id,
        "next_check_at": next_check,
        "provider": provider,
        "check_time": task_check_time,
    }
