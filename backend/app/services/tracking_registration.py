from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.db.database import db
from app.providers.registry import resolve_provider_key
from app.services.media_target import resolve_media_target
from app.services.paths import build_save_path
from app.services.saved_episode_scanner import refresh_saved_episodes
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

    save_path = build_save_path(
        request.save_target,
        target.category or request.media_type,
        target.title,
        target.series_year,
        request.season_number,
        provider,
    )
    configured_check_time = request.check_time.strip() or get_settings().tracking_check_time
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM tracking_tasks WHERE tmdb_id=? AND media_type=? AND season_number=? AND provider=?",
            (request.tmdb_id, request.media_type, request.season_number, provider),
        ).fetchone()
        if existing:
            task_id = int(existing["id"])
            task_check_time = request.check_time.strip() or str(existing["check_time"] or configured_check_time)
            conn.execute(
                """
                UPDATE tracking_tasks SET title=?,year=?,poster_url=?,overview=?,category=?,save_target=?,provider=?,save_path=?,
                                          check_time=?,status='active',decision_state='pending',updated_at=CURRENT_TIMESTAMP
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
        auto_start_episode = compute_auto_start_episode(target, statuses, check_time=task_check_time)
        next_check = compute_next_check(
            target,
            statuses,
            check_time=task_check_time,
            progress_floor=auto_start_episode,
        )
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
