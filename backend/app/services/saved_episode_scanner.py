from __future__ import annotations

import re
import posixpath
from datetime import datetime, timezone

from app.clients.qas import QasClient
from app.db.database import db


_EPISODE = re.compile(r"(?i)(?<![a-z0-9])S0*(\d{1,2})[ ._-]*E0*(\d{1,4})(?!\d)")


def scan_save_path_last_episode(path: str, season_number: int, *, qas: QasClient | None = None) -> int:
    """Read the exact QAS destination and return its highest canonical episode number."""
    response = (qas or QasClient()).savepath_detail(path)
    if not isinstance(response, dict) or response.get("success") is False:
        raise RuntimeError("QAS save-path query failed")
    if not _response_matches_path(response, path):
        return 0
    return _last_episode_from_response(response, season_number)


def resolve_save_path_progress(path: str, season_number: int, *, qas: QasClient | None = None) -> tuple[str, int]:
    """Use the canonical folder, or one unambiguous legacy spelling; never guess between duplicates."""
    client = qas or QasClient()
    response = client.savepath_detail(path)
    if not isinstance(response, dict) or response.get("success") is False:
        raise RuntimeError("QAS save-path query failed")
    if _response_matches_path(response, path):
        return path, _last_episode_from_response(response, season_number)

    normalized = str(path).replace("\\", "/").rstrip("/")
    parent, wanted = posixpath.split(normalized)
    parent_response = client.savepath_detail(parent)
    if not isinstance(parent_response, dict) or parent_response.get("success") is False or not _response_matches_path(parent_response, parent):
        raise RuntimeError("QAS parent directory query failed")
    siblings = (parent_response.get("data") or {}).get("list") or []
    matches = [
        str(item.get("file_name") or item.get("name") or "")
        for item in siblings
        if isinstance(item, dict) and item.get("dir") is True and _legacy_folder_key(str(item.get("file_name") or item.get("name") or "")) == _legacy_folder_key(wanted)
    ]
    if not matches:
        return path, 0
    if len(matches) > 1:
        raise RuntimeError("multiple compatible media folders")
    actual = f"{parent}/{matches[0]}"
    actual_response = client.savepath_detail(actual)
    if not _response_matches_path(actual_response, actual):
        raise RuntimeError("legacy media folder could not be verified")
    return actual, _last_episode_from_response(actual_response, season_number)


def _legacy_folder_key(value: str) -> str:
    return re.sub(r"[\s.()（）_-]+", "", value).casefold()


def refresh_saved_episodes(task_id: int, *, qas: QasClient | None = None) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return {"ok": False, "message": "追更任务不存在", "last_saved_episode": 0}
        task = dict(row)
        saved_row = conn.execute(
            "SELECT MAX(episode_number) AS value FROM tracking_episodes WHERE task_id=? AND status='saved'",
            (task_id,),
        ).fetchone()
    recorded_last = max(int(task.get("last_saved_episode") or 0), int(saved_row["value"] or 0))

    drive_last = 0
    message = "夸克目录中尚未发现标准命名的已存文件"
    scan_ok = True
    try:
        actual_path, drive_last = resolve_save_path_progress(
            str(task.get("save_path") or ""), int(task.get("season_number") or 0), qas=qas
        )
        task["save_path"] = actual_path
        message = f"夸克目录已存至 S{int(task.get('season_number') or 0):02d}E{drive_last:02d}" if drive_last else "目标文件夹尚不存在或为空，保留历史已存进度"
    except Exception as exc:
        scan_ok = False
        message = f"读取夸克目录失败，保留历史已存进度：{type(exc).__name__}"

    effective_last = max(recorded_last, drive_last)
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        if effective_last:
            conn.execute(
                """
                UPDATE tracking_episodes
                SET status='saved',last_error='',saved_at=COALESCE(saved_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND episode_number<=?
                """,
                (task_id, effective_last),
            )
        conn.execute(
            """
            UPDATE tracking_tasks
            SET last_saved_episode=?,last_storage_check_at=?,storage_check_message=?,save_path=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (effective_last, checked_at, message, task.get("save_path") or "", task_id),
        )
    return {
        "ok": scan_ok,
        "last_saved_episode": effective_last,
        "drive_last_episode": drive_last,
        "save_path": task.get("save_path") or "",
        "message": message,
        "checked_at": checked_at,
    }


def _response_matches_path(response: object, requested_path: str) -> bool:
    if not isinstance(response, dict) or response.get("success") is False:
        return False
    data = response.get("data")
    if not isinstance(data, dict):
        return False
    paths = data.get("paths")
    if not isinstance(paths, list):
        return False
    actual = "/" + "/".join(str(item.get("name") or "").strip(" /") for item in paths if isinstance(item, dict))
    expected = "/" + "/".join(part for part in str(requested_path).replace("\\", "/").split("/") if part)
    return actual == expected


def _last_episode_from_response(response: dict, season_number: int) -> int:
    data = response.get("data") or {}
    files = data.get("list") or []
    episodes: list[int] = []
    for item in files:
        if not isinstance(item, dict) or item.get("dir") is True:
            continue
        name = str(item.get("file_name") or item.get("name") or "")
        for season, episode in _EPISODE.findall(name):
            if int(season) == season_number:
                episodes.append(int(episode))
    return max(episodes, default=0)
