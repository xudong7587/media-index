import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime
from hashlib import sha1
from collections.abc import Iterable
from zoneinfo import ZoneInfo

from app.clients.openlist import OpenListClient, OpenListError
from app.core.config import get_settings
from app.db.database import db
from app.services.episode_matcher import VIDEO_EXTENSIONS, episode_numbers_from_name
from app.services.media_target import resolve_media_target
from app.services.saved_episode_scanner import refresh_saved_episodes
from app.providers.registry import get_transfer_provider
from pathlib import PurePosixPath


def automatic_sync_allowed(settings, source_provider: str, target_provider: str) -> bool:
    source = _openlist_provider_key(source_provider)
    target = _openlist_provider_key(target_provider)
    if source not in {"qas", "p115"} or target not in {"qas", "p115"} or source == target:
        return False
    direction = str(getattr(settings, "openlist_auto_sync_direction", "bidirectional") or "bidirectional").strip().lower()
    if direction == "bidirectional":
        return True
    return direction == f"{source}_to_{target}"


def _openlist_provider_key(provider: str) -> str:
    """OpenList keeps the legacy `qas` mount name for native Quark too."""
    value = str(provider or "").strip().lower()
    return "qas" if value == "quark" else value


def sync_configured_openlist_library() -> dict:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return {"ok": False, "message": "OpenList 自动同步未启用"}
    return sync_openlist_library_once()


def sync_openlist_library_once() -> dict:
    started = start_openlist_library_sync()
    if started.get("duplicate"):
        return started
    return run_openlist_library_sync(
        int(started["job_id"]),
        str(started["source_dir"]),
        str(started["target_dir"]),
    )


def start_openlist_library_sync() -> dict:
    settings = get_settings()
    if not settings.openlist_enabled:
        return {"ok": False, "message": "请先启用 OpenList 功能"}
    source_dir = _normalize_openlist_dir(settings.openlist_qas_library_path)
    target_dir = _normalize_openlist_dir(settings.openlist_p115_library_path)
    execution_key = f"openlist:library:{source_dir}:{target_dir}"
    job_id, duplicate = _start_openlist_sync_job(
        execution_key,
        message="正在同步 OpenList 媒体库",
        display_title="OpenList 媒体库同步",
    )
    if duplicate:
        return duplicate
    return {
        "ok": True,
        "running": True,
        "job_id": job_id,
        "source_dir": source_dir,
        "target_dir": target_dir,
        "message": "OpenList 媒体库同步已开始，可在右上角执行任务查看进度",
    }


def run_openlist_library_sync(job_id: int, source_dir: str, target_dir: str) -> dict:
    try:
        result = OpenListClient().sync_tree(source_dir, target_dir)
    except OpenListError as exc:
        _finish_openlist_sync_job(job_id, "failed", "openlist_sync_failed", str(exc))
        return {"ok": False, "message": str(exc), "job_id": job_id}
    message = f"已扫描 {result['scanned']} 项，提交 {result['copied']} 项同步"
    if result["limited"]:
        message += "，达到单次扫描上限"
    _finish_openlist_sync_job(job_id, "done", "openlist_sync_done", message)
    return {"ok": True, "message": message, "job_id": job_id, **result}


def sync_selected_openlist_once(source_dir: str, target_dir: str, names: list[str], *, overwrite: bool = False) -> dict:
    started = start_selected_openlist_sync(source_dir, target_dir, names, overwrite=overwrite)
    if not started.get("ok") or started.get("duplicate"):
        return started
    return run_selected_openlist_sync(
        int(started["job_id"]),
        str(started["source_dir"]),
        str(started["target_dir"]),
        list(started["names"]),
        overwrite=bool(started["overwrite"]),
    )


def start_selected_openlist_sync(source_dir: str, target_dir: str, names: list[str], *, overwrite: bool = False) -> dict:
    clean_names = [name for name in dict.fromkeys(str(name or "").strip() for name in names) if name]
    if not clean_names:
        return {"ok": False, "message": "请选择要同步的文件"}
    source = _normalize_openlist_dir(source_dir)
    target = _normalize_openlist_dir(target_dir)
    names_key = "\x1f".join(sorted(clean_names))
    execution_key = f"openlist:selected:{source}:{target}:{int(overwrite)}:{names_key}"
    job_id, duplicate = _start_openlist_sync_job(
        execution_key,
        message="正在同步选中的 OpenList 文件",
        display_title="OpenList 手动同步",
    )
    if duplicate:
        return duplicate
    return {
        "ok": True,
        "running": True,
        "job_id": job_id,
        "source_dir": source,
        "target_dir": target,
        "names": clean_names,
        "overwrite": overwrite,
        "message": f"已开始同步 {len(clean_names)} 项，可在右上角执行任务查看进度",
    }


def run_selected_openlist_sync(job_id: int, source_dir: str, target_dir: str, names: list[str], *, overwrite: bool = False) -> dict:
    try:
        result = OpenListClient().copy(source_dir, target_dir, names, overwrite=overwrite)
    except OpenListError as exc:
        _finish_openlist_sync_job(job_id, "failed", "openlist_sync_failed", str(exc))
        return {"ok": False, "message": str(exc), "job_id": job_id}
    action = "覆盖复制" if overwrite else "跳过已存在项并复制"
    message = f"已提交 {len(names)} 项，{action}"
    _finish_openlist_sync_job(job_id, "done", "openlist_sync_done", message)
    return {"ok": True, "message": message, "job_id": job_id, "result": result}


def sync_transfer_outputs(
    source_provider: str,
    save_path: str,
    filenames: list[str],
    *,
    tmdb_id: int | None = None,
    media_type: str = "",
    season_number: int | None = None,
    display_title: str = "",
    target_providers: Iterable[str] | None = None,
) -> list[dict]:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return []
    provider = str(source_provider or "").strip().lower()
    if provider not in {"qas", "quark", "p115"} or not save_path:
        return []
    targets = _openlist_sync_targets(settings, provider)
    if target_providers is not None:
        requested = {str(target or "").strip().lower() for target in target_providers}
        targets = [target for target in targets if target in requested]
    if not targets:
        return []
    unique_filenames = [name for name in dict.fromkeys(str(filename or "").strip() for filename in filenames) if name]
    if not unique_filenames:
        source_dir = _openlist_dir_for_save_path(save_path, provider, settings)
        try:
            unique_filenames = [
                str(item.get("name") or "").strip()
                for item in OpenListClient().list_entries(source_dir)
                if not item.get("is_dir") and str(item.get("name") or "").strip()
            ]
        except OpenListError:
            return []
    if not unique_filenames:
        return []
    task = {
        "provider": provider,
        "save_path": save_path,
        "tmdb_id": tmdb_id,
        "media_type": media_type,
        "season_number": season_number,
    }
    results = []
    for target in targets:
        target_save_path = _provider_save_path_for_transfer(save_path, provider, target, settings)
        execution_key = "openlist:auto-transfer:" + sha1(
            "\n".join([provider, target, save_path, *unique_filenames]).encode("utf-8")
        ).hexdigest()[:24]
        job_id, duplicate = _start_openlist_sync_job(
            execution_key,
            tmdb_id=tmdb_id,
            media_type=media_type,
            season_number=season_number,
            message=f"正在同步 {provider} 到 {target} 的文件",
            display_title=display_title,
            save_path=target_save_path,
        )
        if duplicate:
            results.append(duplicate)
            continue
        result = _run_transfer_output_sync_job(job_id, task, target, unique_filenames)
        results.append(result)
    return results


def sync_tracking_fallback_to_p115(
    *,
    target_task_id: int,
    episode_numbers: Iterable[int],
) -> dict:
    """Copy the requested missing episodes from Quark to one 115 task.

    This setting belongs to a tracking season, so it intentionally does not
    inherit the global OpenList auto-sync switch or its historical reverse
    direction.  The caller supplies the episodes that the matching native 115
    run explicitly reported as missing; the actual OpenList directories decide
    which of those episodes are present on Quark and still absent on 115.
    """
    settings = get_settings()
    if not (
        settings.openlist_enabled
        and str(settings.openlist_url or "").strip()
        and str(settings.openlist_token or "").strip()
        and str(settings.openlist_qas_library_path or "").strip()
        and str(settings.openlist_p115_library_path or "").strip()
    ):
        return {
            "ok": False,
            "message": "OpenList 或夸克、115 挂载目录尚未配置",
            "target_task_id": int(target_task_id),
            "copied": [],
            "skipped": [],
            "missing": sorted({int(number) for number in episode_numbers if int(number) > 0}),
        }
    result = _sync_selected_tracking_episodes(
        int(target_task_id),
        episode_numbers,
        automatic_fallback=True,
    )
    result["target_task_id"] = int(target_task_id)
    result.setdefault("copied", [])
    result.setdefault("skipped", [])
    result.setdefault("missing", [])
    return result


def _openlist_sync_targets(settings, source_provider: str) -> list[str]:
    """Resolve the opposite OpenList mount even when native transfer is disabled."""
    source_mount = _openlist_provider_key(source_provider)
    targets = [
        target
        for target in settings.enabled_provider_keys()
        if target in {"qas", "p115"} and target != source_mount
    ]
    mount_paths = {
        "qas": str(getattr(settings, "openlist_qas_library_path", "") or "").strip(),
        "p115": str(getattr(settings, "openlist_p115_library_path", "") or "").strip(),
    }
    opposite = "p115" if source_mount == "qas" else "qas"
    if mount_paths[opposite] and opposite not in targets:
        targets.append(opposite)
    return [target for target in targets if automatic_sync_allowed(settings, source_provider, target)]


def _run_transfer_output_sync_job(
    job_id: int,
    task: dict,
    target_provider: str,
    filenames: list[str],
) -> dict:
    result = sync_tracking_files(task, target_provider, filenames)
    copied = int(result.get("copied") or 0)
    skipped = int(result.get("skipped") or 0)
    errors = [] if result.get("ok") else [str(result.get("message") or "未知错误")]
    if errors and not (copied or skipped):
        message = errors[0]
        _finish_openlist_sync_job(job_id, "failed", "openlist_sync_failed", message)
        return {"ok": False, "job_id": job_id, "message": message}
    parts = []
    if copied:
        parts.append(f"已向 OpenList 提交 {copied} 个文件的复制任务")
    if skipped:
        parts.append(f"已跳过 {skipped} 个已存在文件")
    if errors:
        parts.append(f"{len(errors)} 个文件失败：{errors[0]}")
    message = "，".join(parts) or "没有需要同步的文件"
    status = "done" if not errors else "failed"
    _finish_openlist_sync_job(job_id, status, "openlist_sync_done" if status == "done" else "openlist_sync_failed", message)
    return {"ok": status == "done", "job_id": job_id, "message": message, "copied": copied, "skipped": skipped}


def sync_transfer_batch_storage(batch_id: int) -> list[dict]:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return []
    with db() as conn:
        rows = conn.execute(
            """
            SELECT provider,tmdb_id,media_type,season_number,display_title,status,save_path
            FROM transfer_jobs
            WHERE batch_id=? AND target='cloud' AND provider IN ('qas','p115')
            """,
            (batch_id,),
        ).fetchall()
    grouped: dict[int, dict[str, dict]] = {}
    for row in rows:
        grouped.setdefault(int(row["season_number"] or 0), {})[str(row["provider"])] = dict(row)
    results = []
    for season_number, providers in grouped.items():
        if "qas" not in providers or "p115" not in providers:
            continue
        if str((providers.get("qas") or providers.get("p115") or {}).get("media_type") or "") not in {"tv", "variety"}:
            continue
        if not any(item.get("status") in {"done", "triggered"} and item.get("save_path") for item in providers.values()):
            continue
        qas_dir = _openlist_dir_from_transfer(providers, "qas", settings)
        p115_dir = _openlist_dir_from_transfer(providers, "p115", settings)
        if not qas_dir or not p115_dir:
            continue
        sample = providers.get("qas") or providers.get("p115") or {}
        execution_key = f"openlist:transfer:{sample.get('tmdb_id')}:{sample.get('media_type')}:{season_number}"
        folder_aliases = _folder_aliases_for_media(sample.get("tmdb_id"), str(sample.get("media_type") or ""), season_number)
        results.append(
            sync_openlist_episode_dirs(
                qas_dir,
                p115_dir,
                season_number,
                execution_key=execution_key,
                tmdb_id=sample.get("tmdb_id"),
                media_type=str(sample.get("media_type") or ""),
                display_title=str(sample.get("display_title") or ""),
                folder_aliases=folder_aliases,
                respect_auto_direction=True,
            )
        )
    return results


def sync_tracking_episode(task: dict, target_provider: str, filename: str) -> dict:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return {"ok": False, "message": "自动同步未启用"}
    source_provider = str(task.get("provider") or "")
    if source_provider not in {"qas", "quark", "p115"} or target_provider not in {"qas", "p115"} or _openlist_provider_key(source_provider) == target_provider:
        return {"ok": False, "message": "provider 不支持自动同步"}
    if not automatic_sync_allowed(settings, source_provider, target_provider):
        return {"ok": False, "message": "automatic sync direction skipped this provider"}
    save_path = PurePosixPath(str(task.get("save_path") or "")).as_posix()
    source_dir = _openlist_dir_for_save_path(save_path, source_provider, settings)
    target_dir = _openlist_dir_for_save_path(
        save_path,
        target_provider,
        settings,
        source_provider=source_provider,
    )
    aliases = _folder_aliases_for_media(
        task.get("tmdb_id"),
        str(task.get("media_type") or ""),
        int(task.get("season_number") or 0),
    )
    try:
        client = OpenListClient()
        # The provider's saved path is canonical for MediaIndex, but an
        # OpenList mount can contain an older title spelling. Resolve the
        # actual directory before submitting the copy operation.
        source_dir = _resolve_or_prepare_openlist_dir(client, source_dir, create=False, aliases=aliases)
        target_dir = _resolve_or_prepare_openlist_dir(client, target_dir, create=True, aliases=aliases)
        target_names = {item["name"] for item in client.list_entries(target_dir)}
        if filename in target_names:
            return {"ok": True, "skipped": True, "message": "目标网盘已存在该文件"}
        _copy_with_retry(client, source_dir, target_dir, [filename])
    except OpenListError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "source_dir": source_dir, "target_dir": target_dir, "filename": filename}


def sync_tracking_files(task: dict, target_provider: str, filenames: list[str]) -> dict:
    """Submit one OpenList copy request for all files from one transfer output."""
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return {"ok": False, "message": "自动同步未启用"}
    source_provider = str(task.get("provider") or "")
    if source_provider not in {"qas", "quark", "p115"} or target_provider not in {"qas", "p115"} or _openlist_provider_key(source_provider) == target_provider:
        return {"ok": False, "message": "provider 不支持自动同步"}
    if not automatic_sync_allowed(settings, source_provider, target_provider):
        return {"ok": False, "message": "automatic sync direction skipped this provider"}
    save_path = PurePosixPath(str(task.get("save_path") or "")).as_posix()
    source_dir = _openlist_dir_for_save_path(save_path, source_provider, settings)
    target_dir = _openlist_dir_for_save_path(
        save_path,
        target_provider,
        settings,
        source_provider=source_provider,
    )
    aliases = _folder_aliases_for_media(
        task.get("tmdb_id"),
        str(task.get("media_type") or ""),
        int(task.get("season_number") or 0),
    )
    clean_names = [name for name in dict.fromkeys(str(filename or "").strip() for filename in filenames) if name]
    try:
        client = OpenListClient()
        source_dir = _resolve_or_prepare_openlist_dir(client, source_dir, create=False, aliases=aliases)
        try:
            source_entries = client.list_entries(source_dir)
        except OpenListError as exc:
            if _is_missing_directory_error(exc):
                return {"ok": False, "message": "OpenList 源媒体目录尚未出现"}
            raise
        if not clean_names:
            clean_names = [
                str(item.get("name") or "").strip()
                for item in source_entries
                if not item.get("is_dir") and str(item.get("name") or "").strip()
            ]
        if not clean_names:
            return {"ok": False, "message": "OpenList 源媒体目录中尚未出现文件"}
        target_dir = _resolve_or_prepare_openlist_dir(client, target_dir, create=False, aliases=aliases)
        target_exists = True
        try:
            target_entries = client.list_entries(target_dir)
        except OpenListError as exc:
            if not _is_missing_directory_error(exc):
                raise
            target_exists = False
            target_entries = []

        if not target_exists:
            # A missing destination is common on the first 115 transfer.  Build
            # the exact directory, then copy only the files proven by this
            # operation; copying the source season folder would silently widen
            # the request to unrelated files and subdirectories.
            target_dir = _resolve_or_prepare_openlist_dir(
                client,
                target_dir,
                create=True,
                aliases=aliases,
            )
            target_entries = []

        target_names = {item["name"] for item in target_entries}
        pending = [name for name in clean_names if name not in target_names]
        if pending:
            _copy_with_retry(client, source_dir, target_dir, pending)
    except OpenListError as exc:
        return {"ok": False, "message": str(exc)}
    return {
        "ok": True,
        "source_dir": source_dir,
        "target_dir": target_dir,
        "copied": len(pending),
        "skipped": len(clean_names) - len(pending),
        "submitted": len(pending),
    }


def _copy_with_retry(client: OpenListClient, source_dir: str, target_dir: str, names: list[str], *, overwrite: bool = False) -> dict:
    last_error: OpenListError | None = None
    for attempt in range(3):
        try:
            return client.copy(source_dir, target_dir, names, overwrite=overwrite)
        except OpenListError as exc:
            last_error = exc
            if attempt >= 2 or "请求失败" not in str(exc):
                raise
            time.sleep(1.5 * (attempt + 1))
    raise last_error or OpenListError("OpenList 复制失败")


def sync_tracking_storage_between_providers(task_id: int) -> dict:
    """Manually copy every known episode from Quark to the 115 tracking path."""
    settings = get_settings()
    if not settings.openlist_enabled:
        return {"ok": False, "message": "请先启用 OpenList 功能"}
    with db() as conn:
        current = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not current:
            return {"ok": False, "message": "追更任务不存在"}
        task = dict(current)
        target = conn.execute(
            """
            SELECT * FROM tracking_tasks
            WHERE tmdb_id=? AND media_type=? AND season_number=? AND provider='p115'
            LIMIT 1
            """,
            (task["tmdb_id"], task["media_type"], task["season_number"]),
        ).fetchone()
        if not target:
            return {"ok": False, "message": "请先启用本季的 115 追更并设置目标路径"}
        today = datetime.now(ZoneInfo(settings.tracking_timezone)).date().isoformat()
        episodes = conn.execute(
            """
            SELECT episode_number FROM tracking_episodes
            WHERE task_id=? AND status!='saved'
              AND (air_date IS NULL OR air_date='' OR air_date<=?)
            ORDER BY episode_number
            """,
            (int(target["id"]), today),
        ).fetchall()
    numbers = [int(row["episode_number"]) for row in episodes if int(row["episode_number"] or 0) > 0]
    if not numbers:
        return {"ok": False, "message": "本季尚无可同步的集数"}
    result = sync_selected_tracking_episodes(int(target["id"]), numbers)
    if not result.get("ok"):
        return result
    copied_episodes = result.get("copied") if isinstance(result.get("copied"), list) else []
    skipped_episodes = result.get("skipped") if isinstance(result.get("skipped"), list) else []
    missing_episodes = result.get("missing") if isinstance(result.get("missing"), list) else []
    # Keep the long-standing sync-storage response contract for older clients;
    # expose episode detail under additive keys while sync-selected keeps its
    # list-based response.
    return {
        **result,
        "copied": len(copied_episodes),
        "scanned": 0 if result.get("duplicate") else len(numbers),
        "copied_episodes": copied_episodes,
        "skipped_episodes": skipped_episodes,
        "missing_episodes": missing_episodes,
    }


def sync_selected_tracking_episodes(task_id: int, episode_numbers: list[int]) -> dict:
    """Copy selected Quark episode files to 115 via OpenList."""
    return _sync_selected_tracking_episodes(task_id, episode_numbers, automatic_fallback=False)


def _sync_selected_tracking_episodes(
    task_id: int,
    episode_numbers: Iterable[int],
    *,
    automatic_fallback: bool,
) -> dict:
    settings = get_settings()
    if not settings.openlist_enabled:
        return {"ok": False, "message": "请先启用 OpenList 功能"}
    selected = sorted({int(number) for number in episode_numbers if int(number) > 0})
    if not selected:
        return {"ok": False, "message": "请至少选择一集"}
    with db() as conn:
        current = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not current:
            return {"ok": False, "message": "追更任务不存在"}
        task = dict(current)
        target_provider = str(task.get("provider") or "")
        if target_provider != "p115":
            return {"ok": False, "message": "暂不支持从 115 同步到夸克"}
        sibling = conn.execute(
            """
            SELECT * FROM tracking_tasks
            WHERE tmdb_id=? AND media_type=? AND season_number=? AND provider IN ('quark','qas')
            ORDER BY CASE provider WHEN 'quark' THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (task["tmdb_id"], task["media_type"], task["season_number"]),
        ).fetchone()
    if automatic_fallback and not sibling:
        return {
            "ok": False,
            "message": "本季没有可核验的夸克追更链路",
            "copied": [],
            "skipped": [],
            "missing": selected,
        }
    source_task = dict(sibling) if sibling else dict(task)
    source_provider = str(source_task.get("provider") or "quark") if sibling else "quark"
    episode_key = ",".join(map(str, selected))
    execution_key = (
        f"openlist:tracking-fallback:{int(task_id)}:{episode_key}"
        if automatic_fallback
        else f"openlist:selected-tracking:{task['tmdb_id']}:{task['media_type']}:{task['season_number']}:{target_provider}:{episode_key}"
    )
    job_id, duplicate = _start_openlist_sync_job(
        execution_key,
        task_id=task_id,
        tmdb_id=task.get("tmdb_id"),
        media_type=str(task.get("media_type") or ""),
        season_number=int(task.get("season_number") or 0),
        message=(
            "115 原生检索无资源，正在按本季设置从夸克自动补齐"
            if automatic_fallback
            else "正在同步所选追更集数"
        ),
        display_title=(
            f"{task.get('title') or ''} · 夸克→115 自动补齐"
            if automatic_fallback
            else f"{task.get('title') or ''} · {target_provider} 单集同步"
        ),
    )
    if duplicate:
        if automatic_fallback:
            duplicate.update({"copied": [], "skipped": [], "missing": selected})
        return duplicate

    source_dir = (
        _openlist_dir_for_task(source_task, source_provider, settings)
        if sibling
        else _openlist_dir_for_save_path(
            str(task.get("save_path") or ""),
            source_provider,
            settings,
            source_provider=target_provider,
        )
    )
    target_dir = _openlist_dir_for_task(task, target_provider, settings)
    aliases = _folder_aliases_for_media(task.get("tmdb_id"), str(task.get("media_type") or ""), int(task.get("season_number") or 0))
    copied: list[int] = []
    skipped: list[int] = []
    missing: list[int] = []
    confirmed_files: list[dict[str, object]] = []
    try:
        client = OpenListClient()
        source_dir = _resolve_or_prepare_openlist_dir(client, source_dir, create=False, aliases=aliases)
        target_dir = _resolve_or_prepare_openlist_dir(client, target_dir, create=True, aliases=aliases)
        source_files = _episode_file_map(_list_entries_or_empty(client, source_dir), int(task.get("season_number") or 0))
        target_files = _episode_file_map(_list_entries_or_empty(client, target_dir), int(task.get("season_number") or 0))
        missing_from_openlist = set(selected) - set(source_files)
        if missing_from_openlist and sibling:
            # Native provider scans are authoritative for the tracking card.
            # OpenList listings can lag behind a just-saved QAS/115 file, so
            # use the native filename as the copy source when available.
            source_files.update(
                {
                    episode: filename
                    for episode, filename in _native_episode_file_map(
                        source_provider,
                        str(source_task.get("save_path") or ""),
                        int(task.get("season_number") or 0),
                    ).items()
                    if episode in missing_from_openlist
                }
            )
        pending_episodes: list[int] = []
        pending_names: list[str] = []
        for episode_number in selected:
            filename = source_files.get(episode_number)
            if not filename:
                missing.append(episode_number)
            elif episode_number in target_files:
                skipped.append(episode_number)
                confirmed_files.append({"episode_number": episode_number, "file_name": target_files[episode_number]})
            else:
                pending_episodes.append(episode_number)
                pending_names.append(filename)
                confirmed_files.append({"episode_number": episode_number, "file_name": filename})
        if pending_names:
            _copy_with_retry(client, source_dir, target_dir, pending_names)
            copied.extend(pending_episodes)
    except OpenListError as exc:
        _finish_openlist_sync_job(job_id, "failed", "openlist_sync_failed", str(exc))
        return {"ok": False, "message": str(exc), "job_id": job_id}

    parts = []
    if copied:
        parts.append(f"已同步 {len(copied)} 集")
    if skipped:
        parts.append(f"已跳过目标已有的 {len(skipped)} 集")
    if missing:
        parts.append(f"源网盘未找到 {len(missing)} 集")
    message = "，".join(parts) or "没有需要同步的集数"
    status = "done" if copied or skipped else "failed"
    _finish_openlist_sync_job(job_id, status, "openlist_sync_done" if status == "done" else "openlist_sync_failed", message)
    return {
        "ok": status == "done",
        "message": message,
        "job_id": job_id,
        "copied": copied,
        "skipped": skipped,
        "missing": missing,
        # OpenList only confirms that the copy request was accepted.  Keep the
        # exact episode-to-filename evidence so the native 115 reconciler can
        # verify the destination before STRM/Emby and the batch notification.
        "files": confirmed_files,
    }


def sync_openlist_episode_dirs(
    qas_dir: str,
    p115_dir: str,
    season_number: int,
    *,
    execution_key: str,
    task_id: int | None = None,
    tmdb_id: int | None = None,
    media_type: str = "",
    display_title: str = "",
    folder_aliases: tuple[str, ...] = (),
    respect_auto_direction: bool = False,
) -> dict:
    qas_dir = _normalize_openlist_dir(qas_dir)
    p115_dir = _normalize_openlist_dir(p115_dir)
    job_id, duplicate = _start_openlist_sync_job(
        execution_key,
        task_id=task_id,
        tmdb_id=tmdb_id,
        media_type=media_type,
        season_number=season_number,
        message="正在同步两边网盘缺失集",
        display_title=display_title,
    )
    if duplicate:
        return duplicate
    try:
        client = OpenListClient()
        qas_dir = _resolve_or_prepare_openlist_dir(client, qas_dir, create=False, aliases=folder_aliases)
        p115_dir = _resolve_or_prepare_openlist_dir(client, p115_dir, create=False, aliases=folder_aliases)
        qas_entries = _list_entries_or_empty(client, qas_dir)
        p115_entries = _list_entries_or_empty(client, p115_dir)
        qas_files = _episode_file_map(qas_entries, int(season_number or 0))
        p115_files = _episode_file_map(p115_entries, int(season_number or 0))
        qas_missing = sorted(set(p115_files) - set(qas_files))
        p115_missing = sorted(set(qas_files) - set(p115_files))
        copied = 0
        results = []
        if qas_missing and (not respect_auto_direction or automatic_sync_allowed(get_settings(), "p115", "qas")):
            names = [p115_files[number] for number in qas_missing]
            qas_dir = _resolve_or_prepare_openlist_dir(client, qas_dir, create=True, aliases=folder_aliases)
            _copy_with_retry(client, p115_dir, qas_dir, names)
            copied += len(names)
            results.append({"from": "p115", "to": "qas", "episodes": qas_missing, "names": names})
        if p115_missing and (not respect_auto_direction or automatic_sync_allowed(get_settings(), "qas", "p115")):
            names = [qas_files[number] for number in p115_missing]
            p115_dir = _resolve_or_prepare_openlist_dir(client, p115_dir, create=True, aliases=folder_aliases)
            _copy_with_retry(client, qas_dir, p115_dir, names)
            copied += len(names)
            results.append({"from": "qas", "to": "p115", "episodes": p115_missing, "names": names})
    except OpenListError as exc:
        _finish_openlist_sync_job(job_id, "failed", "openlist_sync_failed", str(exc))
        return {"ok": False, "message": str(exc), "job_id": job_id}

    scanned = len(qas_files) + len(p115_files)
    if copied:
        message = f"已扫描两边目录，提交 {copied} 个缺失文件同步"
    else:
        message = "已扫描两边目录，未发现需要同步的缺失集"
    _finish_openlist_sync_job(job_id, "done", "openlist_sync_done", message)
    return {
        "ok": True,
        "message": message,
        "copied": copied,
        "scanned": scanned,
        "qas_dir": qas_dir,
        "p115_dir": p115_dir,
        "results": results,
        "job_id": job_id,
    }


def _start_openlist_sync_job(
    execution_key: str,
    *,
    task_id: int | None = None,
    tmdb_id: int | None = None,
    media_type: str = "",
    season_number: int | None = None,
    message: str,
    display_title: str = "",
    save_path: str = "",
) -> tuple[int, dict | None]:
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM transfer_jobs WHERE execution_key=? AND status='running' ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if existing:
            return int(existing["id"]), {
                "ok": True,
                "duplicate": True,
                "running": True,
                "job_id": int(existing["id"]),
                "copied": 0,
                "scanned": 0,
                "message": "相同的 OpenList 同步任务正在运行，已复用当前任务",
            }
        try:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(
                    task_id,tmdb_id,media_type,season_number,target,provider,status,stage,message,display_title,save_path,execution_key
                ) VALUES(?,?,?,?,?,'openlist','running','openlist_sync',?,?,?,?)
                """,
                (
                    task_id,
                    tmdb_id,
                    media_type,
                    season_number,
                    "cloud",
                    message,
                    display_title,
                    save_path,
                    execution_key,
                ),
            ).lastrowid
        except sqlite3.IntegrityError:
            existing = conn.execute(
                "SELECT * FROM transfer_jobs WHERE execution_key=? AND status='running' ORDER BY id DESC LIMIT 1",
                (execution_key,),
            ).fetchone()
            if existing:
                return int(existing["id"]), {
                    "ok": True,
                    "duplicate": True,
                    "running": True,
                    "job_id": int(existing["id"]),
                    "copied": 0,
                    "scanned": 0,
                    "message": "相同的 OpenList 同步任务正在运行，已复用当前任务",
                }
            raise
    return int(job_id), None


def _finish_openlist_sync_job(job_id: int, status: str, stage: str, message: str) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs
            SET status=?,stage=?,message=?,finished_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='running'
            """,
            (status, stage, message, job_id),
        )


def _openlist_dir_for_task(task: dict, provider: str, settings) -> str:
    save_path = PurePosixPath(str(task.get("save_path") or "")).as_posix()
    return _openlist_dir_for_save_path(save_path, provider, settings)


def _openlist_dir_for_save_path(
    save_path: str,
    provider: str,
    settings,
    *,
    source_provider: str | None = None,
) -> str:
    target_save_path = _provider_save_path_for_transfer(save_path, source_provider or provider, provider, settings)
    target_root = PurePosixPath(str(settings.provider_save_root(provider) or "/")).as_posix().rstrip("/") or "/"
    library = settings.openlist_p115_library_path if provider == "p115" else settings.openlist_qas_library_path
    normalized_library = PurePosixPath(str(library or "/")).as_posix().rstrip("/") or "/"
    if target_root != "/" and (normalized_library == target_root or normalized_library.endswith(f"/{target_root.lstrip('/')}")):
        relative = target_save_path[len(target_root):].lstrip("/") if target_save_path.startswith(target_root) else target_save_path.lstrip("/")
    else:
        relative = target_save_path.lstrip("/")
    return f"{normalized_library.rstrip('/')}/{relative}" if relative else normalized_library


def _provider_save_path_for_transfer(save_path: str, source_provider: str, target_provider: str, settings) -> str:
    source_root = PurePosixPath(str(settings.provider_save_root(source_provider) or "/")).as_posix().rstrip("/") or "/"
    target_root = PurePosixPath(str(settings.provider_save_root(target_provider) or "/")).as_posix().rstrip("/") or "/"
    normalized_save_path = PurePosixPath(str(save_path or "/")).as_posix()
    if source_root != "/" and (normalized_save_path == source_root or normalized_save_path.startswith(f"{source_root}/")):
        relative = normalized_save_path[len(source_root):].lstrip("/")
    else:
        relative = normalized_save_path.lstrip("/")
    if relative and target_root != "/":
        return f"{target_root.rstrip('/')}/{relative}"
    return f"/{relative}" if relative else target_root


def _openlist_dir_from_transfer(providers: dict[str, dict], provider: str, settings) -> str:
    current = providers.get(provider) or {}
    save_path = str(current.get("save_path") or "")
    if not save_path:
        other_provider = "p115" if provider == "qas" else "qas"
        other = providers.get(other_provider) or {}
        save_path = str(other.get("save_path") or "")
    if not save_path:
        return ""
    normalized_save = PurePosixPath(save_path).as_posix()
    return _openlist_dir_for_save_path(normalized_save, provider, settings)


def _normalize_openlist_dir(path: str) -> str:
    normalized = "/" + "/".join(part for part in str(path or "").replace("\\", "/").split("/") if part)
    return normalized if normalized != "/" else "/"


def _folder_aliases_for_media(tmdb_id, media_type: str, season_number: int) -> tuple[str, ...]:
    try:
        target = resolve_media_target(int(tmdb_id), media_type, season_number)
    except Exception:
        return ()
    year = target.series_year or target.season_year
    aliases: list[str] = []
    for title in target.search_titles:
        clean = str(title or "").strip()
        if not clean:
            continue
        aliases.append(clean)
        if year:
            aliases.extend((f"{clean}({year})", f"{clean} ({year})", f"{clean}.{year}"))
    if season_number > 0:
        aliases.extend((f"Season {season_number}", f"S{season_number:02d}", f"S{season_number}"))
    return tuple(dict.fromkeys(aliases))


def _list_entries_or_empty(client: OpenListClient, path: str) -> list[dict]:
    try:
        return client.list_entries(path)
    except OpenListError as exc:
        if _is_missing_directory_error(exc):
            return []
        raise


def _resolve_or_prepare_openlist_dir(client: OpenListClient, path: str, *, create: bool, aliases: tuple[str, ...] = ()) -> str:
    normalized = _normalize_openlist_dir(path)
    try:
        client.list_entries(normalized)
        return normalized
    except OpenListError as exc:
        if not _is_missing_directory_error(exc):
            raise

    parent = _normalize_openlist_dir(str(PurePosixPath(normalized).parent))
    if parent and parent != "/" and parent != normalized:
        parent = _resolve_or_prepare_openlist_dir(client, parent, create=create, aliases=aliases)
    wanted = PurePosixPath(normalized).name
    try:
        candidates = client.list_entries(parent)
    except OpenListError as exc:
        if not _is_missing_directory_error(exc):
            raise
        if not create:
            return normalized
        parent = _resolve_or_prepare_openlist_dir(client, parent, create=True, aliases=aliases)
        candidates = []
    acceptable_keys = {_folder_equivalence_key(wanted), *(_folder_equivalence_key(alias) for alias in aliases)}
    matches = [
        str(item.get("name") or "").strip()
        for item in candidates
        if item.get("is_dir") and _folder_equivalence_key(str(item.get("name") or "")) in acceptable_keys
    ]
    if len(matches) == 1:
        return f"{parent.rstrip('/')}/{matches[0]}"
    if not create:
        return normalized
    _ensure_openlist_directory(client, normalized)
    return normalized


def _ensure_openlist_directory(client: OpenListClient, path: str) -> None:
    normalized = "/" + "/".join(part for part in str(path or "").replace("\\", "/").split("/") if part)
    if normalized == "/":
        return
    try:
        client.list_entries(normalized)
        return
    except OpenListError as exc:
        if not _is_missing_directory_error(exc):
            raise
    parent = str(PurePosixPath(normalized).parent)
    if parent and parent != normalized:
        _ensure_openlist_directory(client, parent)
    try:
        client.mkdir(normalized)
    except OpenListError as exc:
        if not _is_missing_directory_error(exc) and "exist" not in str(exc).lower() and "already" not in str(exc).lower():
            raise


def _is_missing_directory_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return "object not found" in message or "not found" in message or "failed get dir" in message


def _folder_equivalence_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    season = _season_folder_number(normalized)
    if season is not None:
        return f"season:{season}"
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)


def _season_folder_number(value: str) -> int | None:
    match = re.fullmatch(r"\s*(?:season|s)\s*0*(\d{1,2})\s*", value, flags=re.I)
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"\s*第\s*0*(\d{1,2})\s*季\s*", value)
    if match:
        return int(match.group(1))
    chinese = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    match = re.fullmatch(r"\s*第\s*([一二三四五六七八九十])\s*季\s*", value)
    return chinese.get(match.group(1)) if match else None


def _episode_file_map(entries: list[dict], season_number: int) -> dict[int, str]:
    files: dict[int, str] = {}
    for item in entries:
        if item.get("is_dir"):
            continue
        name = str(item.get("name") or "").strip()
        if os.path.splitext(name)[1].casefold() not in VIDEO_EXTENSIONS:
            continue
        for episode in episode_numbers_from_name(name, season_number):
            files.setdefault(episode, name)
    return files


def _native_episode_file_map(provider: str, save_path: str, season_number: int) -> dict[int, str]:
    if provider not in {"qas", "p115"} or not save_path:
        return {}
    try:
        response = get_transfer_provider(provider).inspect_save_path(save_path)
    except Exception:
        return {}
    data = response.get("data") if isinstance(response, dict) else {}
    raw_entries = data.get("list") if isinstance(data, dict) else []
    entries = [
        {
            "name": str(item.get("file_name") or item.get("name") or "").strip(),
            "is_dir": bool(item.get("dir") is True or item.get("is_dir")),
        }
        for item in raw_entries
        if isinstance(item, dict)
    ]
    return _episode_file_map(entries, season_number)
