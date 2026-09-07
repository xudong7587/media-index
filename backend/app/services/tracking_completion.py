"""Effective season membership and evidence-based tracking completion.

Storage-only ordinals and withdrawn metadata remain in history, but cannot
change the expected season. A caught-up ongoing season is never archived.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.db.database import db
from app.domain.media import MediaTarget, EpisodeTarget


def effective_episode_sql(alias: str = "tracking_episodes") -> str:
    return (
        f"{alias}.metadata_active=1 AND {alias}.episode_number<=COALESCE("
        f"(SELECT final_episode_override FROM tracking_tasks WHERE id={alias}.task_id),9999)"
    )


def effective_target(task_id: int, target: MediaTarget) -> MediaTarget:
    with db() as conn:
        row = conn.execute("SELECT final_episode_override FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
    final = row["final_episode_override"] if row else None
    return replace(target, episodes=tuple(ep for ep in target.episodes if final is None or ep.episode_number <= final))


def record_season_metadata(conn, task_id: int, target: MediaTarget) -> None:
    # No evidence is preferable to destroying the last useful snapshot.
    if not target.episodes:
        raise ValueError("TMDB 本季分集为空，已保留历史分集并等待元数据恢复")
    last = max(target.episodes, key=lambda ep: ep.episode_number)
    season_complete = target.status.casefold() in {"ended", "canceled", "cancelled"} or last.episode_type in {"finale", "season_finale"}
    numbers = tuple(ep.episode_number for ep in target.episodes)
    placeholders = ",".join("?" for _ in numbers)
    conn.execute(
        f"UPDATE tracking_episodes SET metadata_active=0 WHERE task_id=? AND episode_number NOT IN ({placeholders})",
        (task_id, *numbers),
    )
    conn.execute("UPDATE tracking_tasks SET season_complete=? WHERE id=?", (int(season_complete), task_id))


def reconcile_tracking_completion(task_id: int) -> str:
    today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return "unknown"
        rows = conn.execute(
            f"SELECT episode_number,air_date,status FROM tracking_episodes WHERE task_id=? AND {effective_episode_sql()}",
            (task_id,),
        ).fetchall()
        aired = []
        for row in rows:
            try:
                aired.append(date.fromisoformat(row["air_date"]) <= today)
            except (TypeError, ValueError):
                aired.append(False)
        all_saved = bool(rows) and all(row["status"] == "saved" for row in rows)
        caught_up = any(aired) and all(row["status"] == "saved" for row, released in zip(rows, aired) if released)
        final = task["final_episode_override"]
        # TV snapshots with holes cannot establish a complete season. Variety
        # metadata intentionally excludes derivative episodes and may be sparse.
        numbers = {row["episode_number"] for row in rows}
        contiguous = bool(numbers) and (task["media_type"] == "variety" or numbers == set(range(1, max(numbers) + 1)))
        complete = bool(
            all_saved and all(aired) and contiguous and task["storage_inventory_verified"]
            and (task["season_complete"] or final)
            and (final is None or final in numbers)
        )
        state = "complete" if complete else "caught_up" if caught_up else "airing" if rows else "unknown"
        active = conn.execute(
            "SELECT 1 FROM transfer_jobs WHERE task_id=? AND (status IN ('running','ready','triggered') "
            "OR external_provider_status IN ('post_processing_pending','post_processing_running')) LIMIT 1",
            (task_id,),
        ).fetchone()
        conn.execute("UPDATE tracking_tasks SET completion_state=? WHERE id=?", (state, task_id))
        if complete and not active and task["status"] == "active" and task["auto_archive"] and task["decision_state"] not in {"running", "paused", "needs_review", "awaiting_confirmation"}:
            conn.execute(
                "UPDATE tracking_tasks SET status='archived',decision_state='idle',retry_count=0,last_error='',archived_at=CURRENT_TIMESTAMP,next_check_at=NULL WHERE id=?",
                (task_id,),
            )
        return state


def set_final_episode(task_id: int, final: int | None) -> None:
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise LookupError("追更任务不存在")
        if task["decision_state"] == "running" or conn.execute("SELECT 1 FROM transfer_jobs WHERE task_id=? AND status IN ('running','ready','triggered')", (task_id,)).fetchone():
            raise ValueError("追更正在执行，请完成后再调整最终集数")
        if final is not None and not conn.execute(
            "SELECT 1 FROM tracking_episodes WHERE task_id=? AND metadata_active=1 AND episode_number=?", (task_id, final)
        ).fetchone():
            raise ValueError("最终集号必须来自当前 TMDB 本季分集")
        conn.execute(
            """UPDATE tracking_tasks SET final_episode_override=?,auto_archive=1,
               status=CASE WHEN status='archived' THEN 'active' ELSE status END,
               archived_at=NULL,completion_state='unknown',updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (final, task_id),
        )

        if task["status"] in {"active", "archived"}:
            # Keep the setting and schedule atomic with dispatch's reservation.
            from app.services.tracking_engine_v2 import compute_next_check
            rows = conn.execute(f"SELECT * FROM tracking_episodes WHERE task_id=? AND {effective_episode_sql()}", (task_id,)).fetchall()
            target = MediaTarget(task["tmdb_id"], task["media_type"], task["title"], season_number=task["season_number"],
                                 episodes=tuple(EpisodeTarget(row["season_number"], row["episode_number"], row["air_date"], row["title"]) for row in rows))
            next_check = compute_next_check(target, {row["episode_number"]: row["status"] for row in rows}, check_time=task["check_time"])
            conn.execute("UPDATE tracking_tasks SET decision_state='idle',next_check_at=? WHERE id=?", (next_check or datetime.now(timezone.utc).isoformat(timespec="seconds"), task_id))
