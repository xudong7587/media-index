"""Read-only production-data smoke test for the 0.2 resolver.

This script deliberately stops before QAS execution. It reads one active tracking
task, resolves its TMDB identity, and checks whether the latest aired episode can
be found through the previous-link-first/PanSou fallback pipeline.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.previous_source import recover_previous_share_urls


def safe_error(value: str) -> str:
    without_urls = re.sub(r"https?://[^\s]+", "<url>", value)
    return without_urls[-160:]


def response_shape(value, depth: int = 0):
    if depth >= 5:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(key): response_shape(item, depth + 1) for key, item in list(value.items())[:30]}
    if isinstance(value, list):
        return {"type": "list", "length": len(value), "first": response_shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def main() -> None:
    settings = get_settings()
    connection = sqlite3.connect(f"file:{settings.db_path}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    task = connection.execute(
        """
        SELECT * FROM tracking_tasks
        WHERE status='active'
        ORDER BY COALESCE(last_checked_at, created_at) DESC
        LIMIT 1
        """
    ).fetchone()
    connection.close()
    if task is None:
        print(json.dumps({"ok": False, "stage": "no_active_task"}))
        return

    tmdb = TmdbClient()
    target = resolve_media_target(
        int(task["tmdb_id"]),
        str(task["media_type"]),
        int(task["season_number"]),
        tmdb,
    )
    today = datetime.now(ZoneInfo(settings.tracking_timezone)).date().isoformat()
    aired = [episode for episode in target.episodes if not episode.air_date or episode.air_date <= today]
    if not aired:
        print(json.dumps({"ok": True, "stage": "no_aired_episode"}))
        return

    episode = max(aired, key=lambda item: item.episode_number)
    previous_share_url = str(task["current_share_url"] or "") if "current_share_url" in task.keys() else ""
    previous_share_urls = (previous_share_url,) if previous_share_url else recover_previous_share_urls(target, QasClient())
    resolution = resolve_episode_source(
        replace(target, episodes=(episode,)),
        previous_share_urls,
        qas=QasClient(),
        max_queries=int(os.getenv("DRY_RUN_MAX_QUERIES", "4")),
        max_verify=int(os.getenv("DRY_RUN_MAX_VERIFY", "5")),
    )
    qas_shape = None
    if (
        os.getenv("DRY_RUN_RESPONSE_SHAPE") == "1"
        and resolution.reviewed_candidates
        and resolution.reviewed_candidates[0].share_url
    ):
        qas_shape = response_shape(QasClient().share_detail(resolution.reviewed_candidates[0].share_url))
    print(
        json.dumps(
            {
                "ok": resolution.ok,
                "stage": resolution.stage,
                "source": resolution.source,
                "episode": episode.episode_number,
                "recovered_previous_links": len(previous_share_urls) if not previous_share_url else 0,
                "matches": len(resolution.matches),
                "rename_pairs": len(resolution.rename_pairs),
                "reviewed_candidates": len(resolution.reviewed_candidates),
                "candidate_checks": [
                    {
                        "score": candidate.score,
                        "rejected": candidate.rejected,
                        "reasons": [safe_error(reason) for reason in candidate.reasons[-3:]],
                    }
                    for candidate in resolution.reviewed_candidates
                ],
                "errors": len(resolution.errors),
                "error_types": [safe_error(error) for error in resolution.errors],
                "qas_response_shape": qas_shape,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
