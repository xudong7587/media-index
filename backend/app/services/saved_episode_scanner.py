from __future__ import annotations

import re
import posixpath
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from app.clients.p115 import P115Error
from app.clients.qas import QasClient
from app.clients.quark import QuarkError
from app.db.database import db
from app.services.episode_matcher import VIDEO_EXTENSIONS, episode_numbers_from_name


@dataclass(frozen=True)
class SavePathProgress:
    path: str
    last_episode: int
    episodes: frozenset[int]
    episodes_reliable: bool
    exists: bool

    def __iter__(self):
        # Keep the long-standing two-value unpacking contract for callers and
        # tests while exposing the exact inventory to gap-aware transfers.
        yield self.path
        yield self.last_episode


def scan_save_path_last_episode(path: str, season_number: int, *, qas: QasClient | None = None) -> int:
    """Read the exact QAS destination and return its highest canonical episode number."""
    response = (qas or QasClient()).savepath_detail(path)
    if not isinstance(response, dict) or response.get("success") is False:
        raise RuntimeError("QAS save-path query failed")
    if not _response_matches_path(response, path):
        return 0
    return _last_episode_from_response(response, season_number)


def resolve_save_path_progress(path: str, season_number: int, *, qas: QasClient | None = None) -> SavePathProgress:
    """Use the canonical folder, or one unambiguous legacy spelling; never guess between duplicates."""
    client = qas or QasClient()
    response = client.savepath_detail(path)
    exact_readable = (
        isinstance(response, dict)
        and response.get("success") is not False
        and (response.get("data") or {}).get("exists") is not False
    )
    if exact_readable and _response_matches_path(response, path):
        actual, actual_response = _resolve_season_subdirectory(path, response, season_number, client)
        return _save_path_progress(actual, actual_response, season_number)

    normalized = str(path).replace("\\", "/").rstrip("/")
    parent, wanted = posixpath.split(normalized)
    wanted_season = _season_folder_number(wanted)
    if wanted_season == season_number:
        media_path, media_response = _resolve_media_folder(parent, client)
        if media_response is None:
            return _save_path_progress(path, None, season_number)
        actual, actual_response = _resolve_season_subdirectory(media_path, media_response, season_number, client)
        if actual == media_path:
            # Some libraries keep S01 files directly below the media folder.
            # Do not keep scanning a configured-but-missing Season folder.
            return _save_path_progress(media_path, actual_response, season_number)
        return _save_path_progress(actual, actual_response, season_number)

    actual, actual_response = _resolve_media_folder(path, client)
    if actual_response is None:
        return _save_path_progress(path, None, season_number)
    actual, actual_response = _resolve_season_subdirectory(actual, actual_response, season_number, client)
    return _save_path_progress(actual, actual_response, season_number)


def _save_path_progress(path: str, response: dict | None, season_number: int) -> SavePathProgress:
    if response is None:
        # The parent was read successfully and proved the requested directory
        # does not exist, so an empty episode set is authoritative.
        return SavePathProgress(path, 0, frozenset(), True, False)
    episodes, reliable = _episode_inventory(response, season_number)
    exists = (response.get("data") or {}).get("exists") is not False
    return SavePathProgress(path, max(episodes, default=0), frozenset(episodes), reliable, exists)


def _resolve_media_folder(path: str, client) -> tuple[str, dict | None]:
    response = client.savepath_detail(path)
    if (
        isinstance(response, dict)
        and response.get("success") is not False
        and (response.get("data") or {}).get("exists") is not False
        and _response_matches_path(response, path)
    ):
        return path, response

    normalized = str(path).replace("\\", "/").rstrip("/")
    parent, wanted = posixpath.split(normalized)
    parent_response = client.savepath_detail(parent)
    if (
        isinstance(parent_response, dict)
        and parent_response.get("success") is not False
        and (parent_response.get("data") or {}).get("exists") is False
        and _response_matches_path(parent_response, parent)
    ):
        return path, None
    if not isinstance(parent_response, dict) or parent_response.get("success") is False or not _response_matches_path(parent_response, parent):
        raise RuntimeError("QAS parent directory query failed")
    siblings = (parent_response.get("data") or {}).get("list") or []
    matches = [
        str(item.get("file_name") or item.get("name") or "")
        for item in siblings
        if isinstance(item, dict) and item.get("dir") is True and _legacy_folder_key(str(item.get("file_name") or item.get("name") or "")) == _legacy_folder_key(wanted)
    ]
    if not matches:
        return path, None
    if len(matches) > 1:
        raise RuntimeError("multiple compatible media folders")
    actual = f"{parent}/{matches[0]}"
    actual_response = client.savepath_detail(actual)
    if not _response_matches_path(actual_response, actual):
        raise RuntimeError("legacy media folder could not be verified")
    return actual, actual_response


def _resolve_season_subdirectory(path: str, response: dict, season_number: int, client) -> tuple[str, dict]:
    """Resolve a conventional organized season folder below a media folder.

    Existing libraries commonly store episodes in ``Season 1`` while older
    MediaIndex paths stopped at the title folder.  Only an exact conventional
    season label is accepted, and multiple compatible folders fail closed.
    """
    if season_number <= 0:
        return path, response
    children = (response.get("data") or {}).get("list") or []
    matches = [
        str(item.get("file_name") or item.get("name") or "")
        for item in children
        if isinstance(item, dict)
        and item.get("dir") is True
        and _season_folder_number(str(item.get("file_name") or item.get("name") or "")) == season_number
    ]
    if not matches:
        return path, response
    if len(matches) > 1:
        raise RuntimeError("multiple compatible season folders")
    child_path = f"{str(path).replace(chr(92), '/').rstrip('/')}/{matches[0]}"
    child_response = client.savepath_detail(child_path)
    if isinstance(child_response, dict) and (child_response.get("data") or {}).get("exists") is False:
        return path, response
    if not _response_matches_path(child_response, child_path):
        raise RuntimeError("season folder could not be verified")
    return child_path, child_response


def _season_folder_number(value: str) -> int | None:
    raw = str(value or "").strip().casefold()
    for pattern in (
        r"season[\s._-]*0*(\d+)",
        r"s[\s._-]*0*(\d+)",
        r"第\s*0*(\d+)\s*季",
    ):
        match = re.fullmatch(pattern, raw)
        if match:
            return int(match.group(1))
    return None


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
    client = qas
    if client is None:
        # Import lazily to keep the provider implementations independent from
        # the scanner while still selecting the task's real cloud backend.
        from app.providers.registry import get_transfer_provider

        client = get_transfer_provider(str(task.get("provider") or "qas"))
    recorded_last = max(int(task.get("last_saved_episode") or 0), int(saved_row["value"] or 0))
    provider_label = "115" if task.get("provider") == "p115" else "夸克"

    drive_last = 0
    drive_episodes: set[int] = set()
    drive_episodes_reliable = False
    message = f"{provider_label}目录中尚未发现标准命名的已存文件"
    scan_ok = True
    try:
        progress = resolve_save_path_progress(
            str(task.get("save_path") or ""), int(task.get("season_number") or 0), qas=client
        )
        actual_path, drive_last = progress
        drive_episodes = set(progress.episodes)
        drive_episodes_reliable = bool(progress.episodes_reliable)
        task["save_path"] = actual_path
        exists = bool(progress.exists)
        message = (
            f"{provider_label}目录已存至 S{int(task.get('season_number') or 0):02d}E{drive_last:02d}"
            if drive_last
            else "目标文件夹将在首次成功转存时自动创建，将按空目录补齐"
            if not exists
            else "目标文件夹暂无已存视频，将按空目录补齐"
            if drive_episodes_reliable
            else "目标文件夹中的视频命名无法可靠识别，保留历史已存进度"
        )
    except Exception as exc:
        scan_ok = False
        detail = _storage_error_detail(str(task.get("provider") or ""), exc)
        message = f"读取{provider_label}目录失败，保留历史已存进度：{detail}"

    # Exact inventories may be sparse (for example only E16/E17 exists), so
    # their set is authoritative even though the UI keeps a high-water value.
    # An unreadable or partly unparseable listing falls back to historical
    # progress to avoid replaying an unknown library.
    effective_last = (
        drive_last
        if scan_ok and drive_episodes_reliable
        else max(recorded_last, drive_last)
        if scan_ok
        else recorded_last
    )
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        if scan_ok and drive_episodes_reliable:
            if drive_episodes:
                placeholders = ",".join("?" for _ in drive_episodes)
                conn.execute(
                    f"""
                    UPDATE tracking_episodes
                    SET status='pending',saved_at=NULL,updated_at=CURRENT_TIMESTAMP
                    WHERE task_id=? AND status='saved' AND episode_number NOT IN ({placeholders})
                    """,
                    (task_id, *sorted(drive_episodes)),
                )
            else:
                conn.execute(
                    """
                    UPDATE tracking_episodes
                    SET status='pending',saved_at=NULL,updated_at=CURRENT_TIMESTAMP
                    WHERE task_id=? AND status='saved'
                    """,
                    (task_id,),
                )
        if scan_ok and drive_episodes_reliable and drive_episodes:
            conn.executemany(
                """
                INSERT OR IGNORE INTO tracking_episodes(task_id,season_number,episode_number,status,provider)
                VALUES(?,?,?,?,?)
                """,
                [
                    (
                        task_id,
                        int(task.get("season_number") or 0),
                        episode_number,
                        "pending",
                        str(task.get("provider") or ""),
                    )
                    for episode_number in sorted(drive_episodes)
                ],
            )
            placeholders = ",".join("?" for _ in drive_episodes)
            conn.execute(
                f"""
                UPDATE tracking_episodes
                SET status='saved',last_error='',saved_at=COALESCE(saved_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND episode_number IN ({placeholders})
                """,
                (task_id, *sorted(drive_episodes)),
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
        "drive_episodes": sorted(drive_episodes) if scan_ok else [],
        "drive_episodes_reliable": bool(scan_ok and drive_episodes_reliable),
        "save_path": task.get("save_path") or "",
        "message": message,
        "checked_at": checked_at,
    }


def record_confirmed_tracking_outputs(task_id: int, outputs) -> dict:
    """Apply exact confirmed filenames to one linked tracking lane.

    Initial generic batches and QAS/OpenList reconciliation run outside the
    tracking engine.  Their provider-confirmed filenames are nevertheless
    authoritative and may be sparse, so update only the episodes proven by
    those outputs instead of advancing every episode below a high-water mark.
    """
    with db() as conn:
        task_row = conn.execute(
            "SELECT id,season_number,provider,last_saved_episode FROM tracking_tasks WHERE id=?",
            (int(task_id),),
        ).fetchone()
    if not task_row:
        return {"ok": False, "message": "追更任务不存在", "saved_episodes": []}
    season_number = int(task_row["season_number"] or 0)
    confirmed: set[int] = set()
    for item in outputs or ():
        if isinstance(item, dict):
            value = str(item.get("file_name") or item.get("name") or item.get("path") or "")
        else:
            value = str(item or "")
        filename = posixpath.basename(value.replace("\\", "/"))
        if filename:
            confirmed.update(episode_numbers_from_name(filename, season_number))
    confirmed = {number for number in confirmed if number > 0}
    if not confirmed:
        return {"ok": True, "message": "未从已确认输出识别到集数", "saved_episodes": []}
    with db() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO tracking_episodes(
                task_id,season_number,episode_number,status,provider
            ) VALUES(?,?,?,'pending',?)
            """,
            [
                (int(task_id), season_number, number, str(task_row["provider"] or ""))
                for number in sorted(confirmed)
            ],
        )
        placeholders = ",".join("?" for _ in confirmed)
        conn.execute(
            f"""
            UPDATE tracking_episodes
            SET status='saved',last_error='',saved_at=COALESCE(saved_at,CURRENT_TIMESTAMP),
                updated_at=CURRENT_TIMESTAMP
            WHERE task_id=? AND episode_number IN ({placeholders})
            """,
            (int(task_id), *sorted(confirmed)),
        )
        conn.execute(
            """
            UPDATE tracking_tasks
            SET last_saved_episode=MAX(COALESCE(last_saved_episode,0),?),updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (max(confirmed), int(task_id)),
        )
    return {
        "ok": True,
        "message": f"已确认 {len(confirmed)} 集追更进度",
        "saved_episodes": sorted(confirmed),
    }


def _storage_error_detail(provider: str, exc: Exception) -> str:
    """Expose only provider-owned, already-redacted diagnostics to the UI."""
    provider_key = str(provider).strip().lower()
    if (provider_key == "p115" and isinstance(exc, P115Error)) or (
        provider_key == "quark" and isinstance(exc, QuarkError)
    ):
        detail = str(exc).strip()
        if detail:
            return detail[:240]
    return type(exc).__name__


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
    return max(_episodes_from_response(response, season_number), default=0)


def _episodes_from_response(response: dict, season_number: int) -> set[int]:
    return _episode_inventory(response, season_number)[0]


def _episode_inventory(response: dict, season_number: int) -> tuple[set[int], bool]:
    """Return exact episode numbers and whether every video was understood."""
    if not isinstance(response, dict) or response.get("success") is False:
        return set(), False
    data = response.get("data") or {}
    if not isinstance(data, dict):
        return set(), False
    if data.get("exists") is False:
        return set(), True
    files = data.get("list") or []
    if not isinstance(files, list):
        return set(), False
    episodes: set[int] = set()
    reliable = True
    for item in files:
        if not isinstance(item, dict) or item.get("dir") is True:
            continue
        name = str(item.get("file_name") or item.get("name") or "")
        if os.path.splitext(name)[1].casefold() not in VIDEO_EXTENSIONS:
            continue
        parsed = episode_numbers_from_name(name, season_number)
        if not parsed:
            reliable = False
            continue
        episodes.update(parsed)
    return episodes, reliable
