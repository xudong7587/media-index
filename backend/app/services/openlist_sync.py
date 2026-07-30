import os
import re
import sqlite3
import unicodedata

from app.clients.openlist import OpenListClient, OpenListError
from app.core.config import get_settings
from app.db.database import db
from app.services.episode_matcher import VIDEO_EXTENSIONS
from app.services.media_target import resolve_media_target
from app.services.saved_episode_scanner import refresh_saved_episodes
from pathlib import PurePosixPath


_EPISODE = re.compile(r"(?i)(?<![a-z0-9])S0*(\d{1,2})[ ._-]*E0*(\d{1,4})(?!\d)")


def sync_configured_openlist_library() -> dict:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return {"ok": False, "message": "OpenList 自动同步未启用"}
    return {"ok": False, "message": "自动同步只由智能追更按单集触发"}


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


def sync_transfer_outputs(source_provider: str, save_path: str, filenames: list[str]) -> list[dict]:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return []
    provider = str(source_provider or "").strip().lower()
    if provider not in {"qas", "p115"} or not save_path:
        return []
    unique_filenames = [name for name in dict.fromkeys(str(filename or "").strip() for filename in filenames) if name]
    if not unique_filenames:
        return []
    task = {"provider": provider, "save_path": save_path}
    targets = [
        target
        for target in settings.enabled_provider_keys()
        if target in {"qas", "p115"} and target != provider
    ]
    results = []
    for target in targets:
        for filename in unique_filenames:
            results.append(sync_tracking_episode(task, target, filename))
    return results


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
            )
        )
    return results


def sync_tracking_episode(task: dict, target_provider: str, filename: str) -> dict:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return {"ok": False, "message": "自动同步未启用"}
    source_provider = str(task.get("provider") or "")
    if source_provider not in {"qas", "p115"} or target_provider not in {"qas", "p115"} or source_provider == target_provider:
        return {"ok": False, "message": "provider 不支持自动同步"}
    source_root = settings.provider_save_root(source_provider).strip().rstrip("/")
    save_path = PurePosixPath(str(task.get("save_path") or "")).as_posix()
    relative = save_path[len(source_root):].lstrip("/") if source_root and save_path.startswith(source_root) else save_path.lstrip("/")
    source_library = settings.openlist_qas_library_path if source_provider == "qas" else settings.openlist_p115_library_path
    target_library = settings.openlist_qas_library_path if target_provider == "qas" else settings.openlist_p115_library_path
    source_dir = f"{source_library.rstrip('/')}/{relative}" if relative else source_library
    target_dir = f"{target_library.rstrip('/')}/{relative}" if relative else target_library
    try:
        client = OpenListClient()
        target_names = {item["name"] for item in client.list_entries(target_dir)}
        if filename in target_names:
            return {"ok": True, "skipped": True, "message": "目标网盘已存在该文件"}
        client.copy(source_dir, target_dir, [filename], overwrite=False)
    except OpenListError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "source_dir": source_dir, "target_dir": target_dir, "filename": filename}


def sync_tracking_storage_between_providers(task_id: int) -> dict:
    settings = get_settings()
    if not settings.openlist_enabled:
        return {"ok": False, "message": "请先启用 OpenList 功能"}
    with db() as conn:
        current = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not current:
            return {"ok": False, "message": "追更任务不存在"}
        task = dict(current)
        rows = conn.execute(
            """
            SELECT * FROM tracking_tasks
            WHERE tmdb_id=? AND media_type=? AND season_number=? AND provider IN ('qas','p115')
            """,
            (task["tmdb_id"], task["media_type"], task["season_number"]),
        ).fetchall()
    tasks = {str(row["provider"]): dict(row) for row in rows}
    if "qas" not in tasks or "p115" not in tasks:
        return {"ok": False, "message": "需要同时启用夸克和 115 追更后才能同步"}

    refreshed = []
    for provider_task in tasks.values():
        refreshed.append(refresh_saved_episodes(int(provider_task["id"])))

    qas_dir = _openlist_dir_for_task(tasks["qas"], "qas", settings)
    p115_dir = _openlist_dir_for_task(tasks["p115"], "p115", settings)
    execution_key = f"openlist:tracking:{task['tmdb_id']}:{task['media_type']}:{task['season_number']}"
    result = sync_openlist_episode_dirs(
        qas_dir,
        p115_dir,
        int(task.get("season_number") or 0),
        execution_key=execution_key,
        task_id=task_id,
        tmdb_id=task.get("tmdb_id"),
        media_type=str(task.get("media_type") or ""),
        display_title=str(task.get("title") or ""),
        folder_aliases=_folder_aliases_for_media(task.get("tmdb_id"), str(task.get("media_type") or ""), int(task.get("season_number") or 0)),
    )
    if not result.get("ok"):
        result["refreshed"] = refreshed
        return result

    for provider_task in tasks.values():
        refresh_saved_episodes(int(provider_task["id"]))

    result["refreshed"] = refreshed
    return result


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
        if qas_missing:
            names = [p115_files[number] for number in qas_missing]
            qas_dir = _resolve_or_prepare_openlist_dir(client, qas_dir, create=True, aliases=folder_aliases)
            client.copy(p115_dir, qas_dir, names, overwrite=False)
            copied += len(names)
            results.append({"from": "p115", "to": "qas", "episodes": qas_missing, "names": names})
        if p115_missing:
            names = [qas_files[number] for number in p115_missing]
            p115_dir = _resolve_or_prepare_openlist_dir(client, p115_dir, create=True, aliases=folder_aliases)
            client.copy(qas_dir, p115_dir, names, overwrite=False)
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
                    task_id,tmdb_id,media_type,season_number,target,provider,status,stage,message,display_title,execution_key
                ) VALUES(?,?,?,?,?,'openlist','running','openlist_sync',?,?,?)
                """,
                (
                    task_id,
                    tmdb_id,
                    media_type,
                    season_number,
                    "cloud",
                    message,
                    display_title,
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
    source_root = settings.provider_save_root(provider).strip().rstrip("/")
    save_path = PurePosixPath(str(task.get("save_path") or "")).as_posix()
    relative = save_path[len(source_root):].lstrip("/") if source_root and save_path.startswith(source_root) else save_path.lstrip("/")
    library = settings.openlist_qas_library_path if provider == "qas" else settings.openlist_p115_library_path
    return f"{library.rstrip('/')}/{relative}" if relative else library


def _openlist_dir_from_transfer(providers: dict[str, dict], provider: str, settings) -> str:
    current = providers.get(provider) or {}
    save_path = str(current.get("save_path") or "")
    if not save_path:
        other_provider = "p115" if provider == "qas" else "qas"
        other = providers.get(other_provider) or {}
        save_path = str(other.get("save_path") or "")
        source_root = settings.provider_save_root(other_provider).strip().rstrip("/")
    else:
        source_root = settings.provider_save_root(provider).strip().rstrip("/")
    if not save_path:
        return ""
    normalized_save = PurePosixPath(save_path).as_posix()
    relative = normalized_save[len(source_root):].lstrip("/") if source_root and normalized_save.startswith(source_root) else normalized_save.lstrip("/")
    library = settings.openlist_qas_library_path if provider == "qas" else settings.openlist_p115_library_path
    return f"{library.rstrip('/')}/{relative}" if relative else library


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
        for season, episode in _EPISODE.findall(name):
            if int(season) == season_number:
                files.setdefault(int(episode), name)
    return files
