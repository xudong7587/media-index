from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from typing import Any, Iterable

from app.clients.tmdb import TmdbClient
from app.core.config import Settings, get_settings
from app.db.database import db
from app.domain.media import MediaTarget, RenamePair, SourceFile
from app.providers.cloud_download_organizer import (
    ORGANIZER_PROVIDER_ERRORS,
    OrganizerProvider,
    RemoteEntry,
    organizer_provider,
)
from app.services.episode_matcher import build_rename_pair, is_video, match_episode_files
from app.services.media_target import resolve_media_target
from app.services.media_workflow import (
    complete_transfer_workflow_step,
    initialize_media_workflow,
    update_media_workflow_progress,
    update_media_workflow_step,
)
from app.services.movie_matcher import build_movie_rename_pair, choose_movie_file, choose_movie_files
from app.services.paths import build_media_folder_name, build_season_folder_name, normalize_save_root
from app.services.post_transfer_pipeline import run_post_transfer_pipeline


MAX_MEDIA_FOLDERS_PER_SCOPE = 500
MAX_FILES_PER_MEDIA_FOLDER = 5000
MAX_TREE_DEPTH = 12
REMOTE_MUTATION_BATCH_SIZE = 100
POTENTIAL_VIDEO_SIZE_BYTES = 200 * 1024 * 1024
_RUN_LOCK = threading.Lock()
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_SEASON = re.compile(
    r"(?i)(?<![A-Za-z0-9])S(\d{1,2})(?:E\d{1,4})?"
    r"|(?<![A-Za-z0-9])Season[ ._-]*(\d{1,2})(?!\d)"
    r"|第\s*(\d{1,2})\s*季"
)
_RELEASE_NOISE = re.compile(
    r"(?i)(?:2160p|1080p|720p|576p|480p|4k|8k|uhd|fhd|hdr10\+?|hdr|dv|dolby[ ._-]*vision|"
    r"web[-_. ]?dl|web[-_. ]?rip|bluray|blu[-_. ]?ray|bdrip|remux|x26[45]|h\.?26[45]|hevc|avc|"
    r"10bit|8bit|aac|ac3|eac3|dts(?:-hd)?|atmos|truehd|ddp?\d*|中字|国语|粤语|双语|原盘|"
    r"complete|全集|全季)"
)
_COMPANION_EXTENSIONS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".sup", ".vtt", ".nfo"}
_POTENTIAL_VIDEO_EXTENSIONS = {
    ".3gp", ".asf", ".divx", ".f4v", ".flv", ".iso", ".m2ts", ".m4v",
    ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mts", ".ogv", ".rm",
    ".rmvb", ".ts", ".vob", ".webm", ".wmv",
}
_GENERIC_MOVIE_FILE_WORDS = re.compile(
    r"(?i)(?:part|pt|cd|disc|disk|movie|video|feature|main|正片|上|下|上集|下集)[ ._-]*\d*"
)
_EPISODIC_MARKERS = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:S\d{1,2}[ ._-]*E(?:P|X)?\d{1,4}"
    r"|E(?:P|X)?\d{1,4}|EP(?:ISODE)?[ ._-]*\d{1,4})(?!\d)"
    r"|第\s*\d{1,4}\s*(?:集|期)"
    r"|(?<!\d)\s+-\s*(?:E(?:P)?[ ._-]*)?\d{1,4}(?=(?:\s|[._\-\[\(]|$))"
)
_EPISODIC_GENERIC_WORDS = re.compile(r"(?i)(?:episode|ep|part|pt|集|期)[ ._-]*\d*")
_DASH_EPISODE_NUMBER = re.compile(
    r"(?i)(?<!\d)\s+-\s*(?:E(?:P)?[ ._-]*)?(\d{1,4})(?=(?:\s|[._\-\[\(]|$))"
)
_RELEASE_GROUP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._]{1,24}")
_LEADING_RELEASE_TAGS = re.compile(r"^(?:\s*[\[【][^\]】]{1,40}[\]】]\s*)+")
_FULL_DATE = re.compile(
    r"(?<!\d)(?:19\d{2}|20\d{2})[-_.](?:0[1-9]|1[0-2])[-_.](?:0[1-9]|[12]\d|3[01])(?!\d)"
)
_MOVIE_PART_NUMBER = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:part|pt|cd|disc|disk)[ ._-]*(\d{1,2})(?!\d)"
)
_CHINESE_MOVIE_PART = re.compile(r"(?:上集|下集|上|下)(?![一-鿿])")
ORGANIZER_RECOVERABLE_ERRORS = ORGANIZER_PROVIDER_ERRORS + (RuntimeError, ValueError)


class OrganizerReview(RuntimeError):
    """A safe ambiguity or conflict that must not cause a provider mutation."""


class OrganizerStopped(RuntimeError):
    """The user stopped the task before the next safe mutation boundary."""


@dataclass(frozen=True)
class PlannedFile:
    source: SourceFile
    replacement: str
    destination_path: str
    season_number: int | None = None
    confidence: str = "high"
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrganizePlan:
    target: MediaTarget
    source_folder: RemoteEntry
    source_path: str
    media_path: str
    category: str
    files: tuple[PlannedFile, ...]
    source_scope_path: str = ""
    loose_group_key: str = ""


def run_cloud_download_organizer(provider: str | None = None) -> dict[str, Any]:
    """Scan configured direct-child scopes and organize only stable media folders."""
    if not _RUN_LOCK.acquire(blocking=False):
        return {
            "reason": "busy",
            "scanned": 0,
            "waiting": 0,
            "organized": 0,
            "review": 0,
            "failed": 0,
            "jobs": [],
        }
    try:
        settings = get_settings()
        selected_provider = str(provider or "").strip().lower()
        providers = (selected_provider,) if selected_provider else ("p115", "quark")
        if any(value not in {"p115", "quark"} for value in providers):
            raise ValueError("云下载整理只支持 115 或夸克")
        providers = tuple(
            value for value in providers
            if settings.provider_cloud_download_organizer_enabled(value)
        )
        if not providers:
            return {
                "reason": "disabled",
                "scanned": 0,
                "waiting": 0,
                "organized": 0,
                "review": 0,
                "failed": 0,
                "jobs": [],
            }
        result: dict[str, Any] = {
            "scanned": 0,
            "waiting": 0,
            "organized": 0,
            "review": 0,
            "failed": 0,
            "jobs": [],
        }
        for provider_key in providers:
            scopes = settings.provider_cloud_download_organizer_directories(provider_key)
            if not scopes:
                continue
            provider_result = _run_provider(settings, provider_key, scopes)
            for key in ("scanned", "waiting", "organized", "review", "failed"):
                result[key] += int(provider_result.get(key) or 0)
            result["jobs"].append(provider_result)
        return result
    finally:
        _RUN_LOCK.release()


def run_targeted_cloud_download_organizer(
    provider: str,
    source_path: str,
    *,
    expected_file_ids: Iterable[str] = (),
    expected_names: Iterable[str] = (),
) -> dict[str, Any]:
    """Organize the one media unit identified by a completed MediaIndex action.

    The source path must resolve into one explicitly selected cloud-download
    child.  No sibling scope or unrelated media folder is listed.
    """
    with _RUN_LOCK:
        return _run_targeted_cloud_download_organizer(
            provider,
            source_path,
            expected_file_ids=expected_file_ids,
            expected_names=expected_names,
        )


def _run_targeted_cloud_download_organizer(
    provider: str,
    source_path: str,
    *,
    expected_file_ids: Iterable[str] = (),
    expected_names: Iterable[str] = (),
) -> dict[str, Any]:
    settings = get_settings()
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider not in {"p115", "quark"}:
        raise ValueError("云下载整理只支持 115 或夸克")
    if not settings.provider_cloud_download_organizer_enabled(normalized_provider):
        return {"provider": normalized_provider, "accepted": False, "reason": "disabled"}

    candidate = normalize_save_root(source_path)
    scopes = tuple(
        normalize_save_root(value)
        for value in settings.provider_cloud_download_organizer_directories(normalized_provider)
    )
    scope = next(
        (
            value for value in scopes
            if candidate == value or candidate.startswith(f"{value.rstrip('/')}/")
        ),
        "",
    )
    if not scope:
        return {"provider": normalized_provider, "accepted": False, "reason": "outside_selected_scope"}

    adapter = _provider_adapter(settings, normalized_provider)
    if not adapter.configured():
        raise RuntimeError(f"{'115' if normalized_provider == 'p115' else '夸克'}连接未配置")
    tmdb = TmdbClient()
    if not tmdb.configured():
        raise RuntimeError("TMDB API Key 未配置")
    scope_id = adapter.directory_id(scope)
    if not scope_id:
        raise RuntimeError(f"已选云下载目录不存在：{scope}")

    download_root = normalize_save_root(settings.provider_cloud_download_path(normalized_provider))
    library_root = normalize_save_root(settings.provider_save_root(normalized_provider))
    child_name = _direct_child_name(download_root, scope)
    target_category = normalize_save_root(f"{library_root.rstrip('/')}/{child_name}")
    category = _category_for_scope(settings, normalized_provider, child_name)
    scope_entries = tuple(adapter.list_directory(scope_id))

    relative = candidate[len(scope):].strip("/")
    if relative:
        media_name = relative.split("/", 1)[0]
        matches = [entry for entry in scope_entries if entry.is_dir and entry.name == media_name]
        if len(matches) != 1:
            raise OrganizerReview("前序动作指向的媒体目录未唯一确认")
        folder = matches[0]
        outcome = _process_media_folder(
            settings,
            adapter,
            tmdb,
            folder,
            f"{scope.rstrip('/')}/{folder.name}",
            target_category,
            category,
            trusted_complete=True,
        )
    else:
        ids = {str(value).strip() for value in expected_file_ids if str(value).strip()}
        names = {str(value).strip() for value in expected_names if str(value).strip()}
        if not ids and not names:
            raise OrganizerReview("前序动作未提供精确文件，已拒绝扫描云下载目录")
        exact = tuple(
            entry for entry in scope_entries
            if (entry.file_id in ids or entry.name in names)
        )
        if not exact or any(name not in {entry.name for entry in exact} for name in names):
            raise OrganizerReview("前序动作的目标文件未在云下载目录中唯一确认")
        directories = [entry for entry in exact if entry.is_dir]
        loose_files = tuple(entry for entry in exact if not entry.is_dir)
        if directories and loose_files or len(directories) > 1:
            raise OrganizerReview("一次定点事件包含多个媒体单元，请拆分后重试")
        if directories:
            folder = directories[0]
            outcome = _process_media_folder(
                settings,
                adapter,
                tmdb,
                folder,
                f"{scope.rstrip('/')}/{folder.name}",
                target_category,
                category,
                trusted_complete=True,
            )
        else:
            groups = _loose_media_groups(loose_files, category)
            exact_ids = {entry.file_id for entry in loose_files}
            if len(groups) != 1 or {entry.file_id for entry in groups[0][2]} != exact_ids:
                raise OrganizerReview("一次定点事件包含多个或无法识别的媒体单元，请拆分后重试")
            _group_key, display_name, loose_files = groups[0]
            digest = hashlib.sha256(
                f"{scope_id}\0{'|'.join(sorted(entry.file_id for entry in loose_files))}".encode("utf-8")
            ).hexdigest()[:20]
            anchor = RemoteEntry(scope_id, "", display_name, is_dir=True)
            outcome = _process_media_folder(
                settings,
                adapter,
                tmdb,
                anchor,
                f"{scope.rstrip('/')}/{display_name}",
                target_category,
                category,
                initial_entries=loose_files,
                execution_identity=f"targeted:{digest}",
                source_scope_path=scope,
                loose_group_key=f"targeted:{digest}",
                trusted_complete=True,
            )
    return {
        "provider": normalized_provider,
        "accepted": True,
        "source_path": candidate,
        "outcome": outcome,
    }


def _run_provider(settings: Settings, provider: str, scopes: tuple[str, ...]) -> dict[str, Any]:
    adapter = _provider_adapter(settings, provider)
    run_job_id = _start_run_job(provider, settings.provider_cloud_download_path(provider), settings.provider_save_root(provider))
    counts = {"scanned": 0, "waiting": 0, "organized": 0, "review": 0, "failed": 0}
    scope_errors: list[str] = []
    try:
        if not adapter.configured():
            raise RuntimeError(f"{'115' if provider == 'p115' else '夸克'}连接未配置")
        tmdb = TmdbClient()
        if not tmdb.configured():
            raise RuntimeError("TMDB API Key 未配置")
        download_root = settings.provider_cloud_download_path(provider)
        library_root = settings.provider_save_root(provider)
        for scope in scopes:
            try:
                _ensure_job_active(run_job_id)
                child_name = _direct_child_name(download_root, scope)
                target_category = f"{library_root.rstrip('/')}/{child_name}"
                if target_category == download_root or target_category.startswith(f"{download_root.rstrip('/')}/"):
                    raise RuntimeError("整理目标等于或位于云下载目录内")
                scope_id = adapter.directory_id(scope)
                if not scope_id:
                    raise RuntimeError(f"已选云下载目录不存在：{scope}")
                category = _category_for_scope(settings, provider, child_name)
                recovered_loose = _recover_started_loose_jobs(settings, adapter, scope)
                for outcome in recovered_loose.values():
                    counts["scanned"] += 1
                    counts[outcome] += 1
                # Recovery may rename or move direct files.  Re-list after it
                # so stale pre-recovery entries cannot create ghost jobs.
                scope_entries = tuple(adapter.list_directory(scope_id))
                media_folders = [item for item in scope_entries if item.is_dir]
                loose_groups = _loose_media_groups(scope_entries, category)
                if len(media_folders) + len(loose_groups) > MAX_MEDIA_FOLDERS_PER_SCOPE:
                    raise RuntimeError(f"{scope} 的一级媒体单元超过安全上限")
            except OrganizerStopped:
                raise
            except Exception as exc:
                # A missing or temporarily unreadable selected scope must not
                # prevent other independently authorized scopes from running.
                counts["failed"] += 1
                detail = str(exc) if isinstance(exc, ORGANIZER_PROVIDER_ERRORS + (RuntimeError, ValueError)) else type(exc).__name__
                scope_errors.append(f"{scope}: {detail}"[:240])
                continue
            for folder in media_folders:
                _ensure_job_active(run_job_id)
                counts["scanned"] += 1
                try:
                    outcome = _process_media_folder(
                        settings,
                        adapter,
                        tmdb,
                        folder,
                        f"{scope.rstrip('/')}/{folder.name}",
                        target_category,
                        category,
                    )
                except OrganizerStopped:
                    raise
                except Exception:
                    # One malformed or temporarily unreadable media folder must
                    # not prevent the other selected folders from being scanned.
                    outcome = "failed"
                counts[outcome] += 1
            for group_key, display_name, group_entries in loose_groups:
                _ensure_job_active(run_job_id)
                digest = hashlib.sha256(f"{scope_id}\0{group_key}".encode("utf-8")).hexdigest()[:20]
                execution_identity = f"loose:{digest}"
                mode = "move" if settings.cloud_download_organizer_mode == "move" else "copy"
                execution_key = f"organizer:{adapter.provider}:{execution_identity}:{mode}"
                if execution_key in recovered_loose:
                    continue
                counts["scanned"] += 1
                anchor = RemoteEntry(scope_id, "", display_name, is_dir=True)
                try:
                    outcome = _process_media_folder(
                        settings,
                        adapter,
                        tmdb,
                        anchor,
                        f"{scope.rstrip('/')}/{display_name}",
                        target_category,
                        category,
                        initial_entries=group_entries,
                        execution_identity=execution_identity,
                        source_scope_path=scope,
                        loose_group_key=group_key,
                    )
                except OrganizerStopped:
                    raise
                except Exception:
                    outcome = "failed"
                counts[outcome] += 1
        message = _counts_message(counts)
        if scope_errors:
            message = f"{message}；范围失败：{' | '.join(scope_errors[:3])}"
        _finish_run_job(run_job_id, "failed" if counts["failed"] else "done", message)
    except OrganizerStopped as exc:
        # Preserve an explicit stop on the run row; if a child task or a live
        # authorization check stopped the scan, close the run row as well.
        _finish_run_job(run_job_id, "stopped", str(exc)[:500])
    except Exception as exc:
        counts["failed"] += 1
        message = str(exc) if isinstance(exc, ORGANIZER_PROVIDER_ERRORS + (RuntimeError,)) else f"云下载目录扫描失败（{type(exc).__name__}）"
        _finish_run_job(run_job_id, "failed", message)
    return {"provider": provider, "job_id": run_job_id, **counts}


def _process_media_folder(
    settings: Settings,
    adapter: OrganizerProvider,
    tmdb: TmdbClient,
    folder: RemoteEntry,
    source_path: str,
    target_category: str,
    category: str,
    *,
    initial_entries: tuple[RemoteEntry, ...] | None = None,
    execution_identity: str = "",
    source_scope_path: str = "",
    loose_group_key: str = "",
    trusted_complete: bool = False,
) -> str:
    entries = initial_entries if initial_entries is not None else _read_media_tree(adapter, folder)
    if len(entries) > MAX_FILES_PER_MEDIA_FOLDER:
        raise OrganizerReview("媒体整理单元的文件数量超过安全上限")
    fingerprint = _inventory_fingerprint(folder, entries)
    mode = "move" if settings.cloud_download_organizer_mode == "move" else "copy"
    execution_key = f"organizer:{adapter.provider}:{execution_identity or folder.file_id}:{mode}"
    recovered = _recover_started_job(settings, adapter, folder, source_path, entries, execution_key)
    if recovered is not None:
        return recovered
    videos = [entry for entry in entries if not entry.is_dir and _entry_is_video(entry)]
    if not videos:
        return "waiting"
    job = _stable_job(execution_key, adapter.provider, source_path, folder.name, fingerprint, mode)
    job_id = int(job["id"])
    status = str(job["status"])
    if status in {"done", "needs_review", "running", "stopped"}:
        return "organized" if status == "done" else "review" if status == "needs_review" else "waiting"
    created_at = _parse_db_time(str(job["created_at"] or ""))
    stable_seconds = max(1, int(settings.cloud_download_organizer_stable_minutes)) * 60
    if not trusted_complete and (datetime.now(timezone.utc) - created_at).total_seconds() < stable_seconds:
        return "waiting"
    _update_job(job_id, "running", "organizer_tmdb_resolving", "正在核对 TMDB 信息并生成整理计划")
    update_media_workflow_progress(job_id, "tmdb_resolving", "正在根据云下载目录名核对 TMDB 信息")
    try:
        plan = _build_plan(
            settings,
            adapter.provider,
            folder,
            source_path,
            target_category,
            category,
            entries,
            tmdb,
            source_scope_path=source_scope_path,
            loose_group_key=loose_group_key,
        )
        serialized = [
            {
                **asdict(item),
                "source": asdict(item.source),
            }
            for item in plan.files
        ]
        _update_job_plan(job_id, plan, serialized, fingerprint, mode, source_entries=entries)
        reusable_targets = {
            **_write_receipt_bindings(job_id),
            **_verified_target_bindings(job_id),
        }
        _preflight_destinations(adapter, plan, reusable_targets=reusable_targets)
        _verify_source_folder_scope(adapter, plan)
        _verify_source_snapshot(adapter, plan, fingerprint)
        _ensure_job_active(job_id)
        _mark_job_write_started(job_id)
        _update_job(job_id, "running", "organizer_transferring", f"正在以{_mode_label(mode)}模式整理 {len(plan.files)} 个媒体文件")
        update_media_workflow_progress(job_id, "provider_submitting", "整理计划已核对，正在执行云端文件操作")
        if mode == "copy":
            _execute_copy(
                settings,
                adapter,
                plan,
                fingerprint,
                job_id=job_id,
                reusable_targets=reusable_targets,
                source_entries=entries,
            )
            completion = "已复制到正式媒体库并完成目标核验；云下载来源已保留"
        else:
            _execute_move(
                adapter,
                plan,
                job_id=job_id,
                reusable_targets=reusable_targets,
                source_entries=entries,
            )
            completion = "已移动到正式媒体库并完成目标核验；已精确清理残留文件并保留源目录壳"
        _ensure_job_active(job_id)
        complete_transfer_workflow_step(job_id, "done", "provider_completed", completion)
        if not _update_job(job_id, "running", "organizer_post_processing", "目标已核验，正在生成 STRM 并通知入库"):
            raise OrganizerStopped("任务已由用户停止；目标核验已完成，未触发入库后处理")
        _ensure_job_active(job_id)
        run_post_transfer_pipeline(
            job_id,
            provider=adapter.provider,
            title=plan.target.title,
            poster_url=plan.target.poster_url,
            target_path=plan.media_path,
            target_files=tuple(_verified_target_bindings(job_id).values()),
        )
        if not _update_job(job_id, "done", "organizer_completed", completion, finished=True):
            raise OrganizerStopped("任务已由用户停止；目标核验已完成，未继续更新任务状态")
        return "organized"
    except OrganizerReview as exc:
        message = str(exc)[:500]
        _update_job(job_id, "needs_review", "organizer_needs_review", message, finished=True, review_state="pending")
        complete_transfer_workflow_step(job_id, "needs_review", "needs_review", message)
        return "review"
    except OrganizerStopped as exc:
        message = str(exc)[:500]
        _update_job(job_id, "stopped", "organizer_stopped", message, finished=True)
        complete_transfer_workflow_step(job_id, "failed", "provider_failed", message)
        return "failed"
    except ORGANIZER_RECOVERABLE_ERRORS as exc:
        message = str(exc)[:500]
        _update_job(job_id, "failed", "organizer_failed", message, finished=True)
        complete_transfer_workflow_step(job_id, "failed", "provider_failed", message)
        return "failed"
    except Exception as exc:
        message = f"云下载整理失败（{type(exc).__name__}）"
        _update_job(job_id, "failed", "organizer_failed", message, finished=True)
        complete_transfer_workflow_step(job_id, "failed", "provider_failed", message)
        return "failed"


def _provider_adapter(settings: Settings, provider: str) -> OrganizerProvider:
    return organizer_provider(settings, provider)


def _read_media_tree(adapter: OrganizerProvider, root: RemoteEntry) -> tuple[RemoteEntry, ...]:
    queue: list[tuple[RemoteEntry, str, int]] = [(root, "", 0)]
    result: list[RemoteEntry] = []
    while queue:
        directory, prefix, depth = queue.pop(0)
        if depth > MAX_TREE_DEPTH:
            raise OrganizerReview("媒体目录层级过深，已停止自动整理")
        children = adapter.list_directory(directory.file_id)
        for child in children:
            relative = f"{prefix}/{child.name}".strip("/")
            normalized = RemoteEntry(
                child.file_id,
                child.parent_id,
                child.name,
                child.size,
                child.is_dir,
                relative,
            )
            result.append(normalized)
            if len(result) > MAX_FILES_PER_MEDIA_FOLDER:
                raise OrganizerReview("媒体目录文件数量超过安全上限，已停止自动整理")
            if child.is_dir:
                queue.append((child, relative, depth + 1))
    return tuple(result)


def _read_plan_source_tree(
    adapter: OrganizerProvider,
    plan: OrganizePlan,
    *,
    expected_entries: tuple[RemoteEntry, ...] = (),
) -> tuple[RemoteEntry, ...]:
    if not plan.loose_group_key:
        return _read_media_tree(adapter, plan.source_folder)
    scope_id = adapter.directory_id(_plan_scope_path(plan))
    if not scope_id or scope_id != plan.source_folder.file_id:
        raise OrganizerReview("已选云下载子目录身份已变化")
    direct_files = tuple(
        RemoteEntry(item.file_id, item.parent_id, item.name, item.size, False, item.name)
        for item in adapter.list_directory(scope_id)
        if not item.is_dir
    )
    expected_ids = {item.file_id for item in expected_entries}
    selected: dict[str, RemoteEntry] = {
        item.file_id: item for item in direct_files if item.file_id in expected_ids
    }
    for group_key, _display_name, entries in _loose_media_groups(direct_files, plan.category):
        if group_key == plan.loose_group_key:
            selected.update((item.file_id, item) for item in entries)
    if len(selected) > MAX_FILES_PER_MEDIA_FOLDER:
        raise OrganizerReview("直接媒体文件分组超过安全上限")
    return tuple(sorted(selected.values(), key=lambda item: (item.relative_path.casefold(), item.file_id)))


def _entry_is_video(entry: RemoteEntry) -> bool:
    extension = os.path.splitext(entry.name)[1].casefold()
    configured: set[str] = set()
    try:
        values = json.loads(get_settings().strm_video_extensions_json or "[]")
        if isinstance(values, list):
            configured = {
                value if value.startswith(".") else f".{value}"
                for raw in values
                if (value := str(raw or "").strip().casefold())
            }
    except (TypeError, ValueError, json.JSONDecodeError):
        configured = set()
    # Cleanup is intentionally more conservative than episode matching.  A
    # configured/excluded video, or a large file with an unknown suffix, must
    # block residual cleanup instead of being mistaken for disposable debris.
    return (
        is_video(entry.name)
        or extension in configured
        or extension in _POTENTIAL_VIDEO_EXTENSIONS
        or int(entry.size or 0) >= POTENTIAL_VIDEO_SIZE_BYTES
    )


def _build_plan(
    settings: Settings,
    provider: str,
    folder: RemoteEntry,
    source_path: str,
    target_category: str,
    category: str,
    entries: tuple[RemoteEntry, ...],
    tmdb: TmdbClient,
    *,
    source_scope_path: str = "",
    loose_group_key: str = "",
) -> OrganizePlan:
    if loose_group_key.startswith("unknown:"):
        raise OrganizerReview("直接媒体文件名缺少可与 TMDB 核对的文本标题")
    sources = [
        SourceFile(entry.name, entry.size, entry.relative_path, entry.file_id, entry.parent_id)
        for entry in entries
        if not entry.is_dir and _entry_is_video(entry)
    ]
    query, year = _folder_query(folder.name)
    if not query:
        raise OrganizerReview("无法从目录名提取可核对的媒体名称")
    season_hint = _season_number(f"{folder.name} {' '.join(source.path for source in sources)}")
    tmdb_id, media_type = _match_tmdb(tmdb, query, year, category, season_hint is not None)
    if media_type == "movie":
        target = resolve_media_target(tmdb_id, "movie", client=tmdb, category=category or "movie")
        best, score, reasons, ambiguous = choose_movie_file(target, sources, folder.name)
        selected, _selected_score, _selected_reasons = choose_movie_files(target, sources, folder.name)
        if best is None or score < 35 or not selected:
            raise OrganizerReview("电影文件无法高置信度唯一匹配，请人工核对")
        if {item.provider_file_id for item in selected} != {item.provider_file_id for item in sources}:
            raise OrganizerReview("目录内存在未纳入计划的其他视频，未执行移动或复制")
        if any(not _movie_source_identity_is_safe(target, item) for item in selected):
            raise OrganizerReview("电影目录内存在无法证明属于同一影片的视频，未执行移动或复制")
        part_numbers = [_movie_part_number(item.name) for item in selected]
        has_part_markers = any(number is not None for number in part_numbers)
        valid_part_sequence = (
            bool(selected)
            and all(number is not None for number in part_numbers)
            and sorted(int(number) for number in part_numbers if number is not None)
            == list(range(1, len(selected) + 1))
        )
        if (len(selected) > 1 or has_part_markers) and not valid_part_sequence:
            raise OrganizerReview("电影多段文件必须使用唯一且连续的 CD/Part 1..N 标记")
        if ambiguous and not (len(selected) > 1 and valid_part_sequence):
            raise OrganizerReview("电影文件无法高置信度唯一匹配，请人工核对")
        if any(number is not None for number in part_numbers):
            selected = tuple(
                item for _number, item in sorted(
                    zip(part_numbers, selected),
                    key=lambda pair: int(pair[0] or 0),
                )
            )
        media_path = f"{target_category.rstrip('/')}/{build_media_folder_name(target.title, target.series_year)}"
        planned: list[PlannedFile] = []
        for index, source in enumerate(selected, start=1):
            pair = build_movie_rename_pair(target, source, reasons, index if len(selected) > 1 else None)
            planned.append(PlannedFile(source, pair.replacement, media_path, None, pair.confidence, pair.reasons))
    else:
        grouped: dict[int, list[SourceFile]] = {}
        source_seasons = {_season_number(source.path or source.name) for source in sources}
        explicit_seasons = {number for number in source_seasons if number is not None}
        if None in source_seasons and len(explicit_seasons) > 1:
            raise OrganizerReview("多季度目录中存在未标明季度的视频，无法安全分配 Season")
        if season_hint is None and not explicit_seasons:
            detail = tmdb.details("variety" if media_type == "variety" else "tv", tmdb_id)
            regular_seasons = {
                int(item.get("season_number"))
                for item in detail.get("seasons") or []
                if isinstance(item, dict) and int(item.get("season_number") or 0) > 0
            } if isinstance(detail, dict) else set()
            if len(regular_seasons) != 1:
                raise OrganizerReview("剧集目录和文件名均未标明季度，无法安全推断 Season")
            default_season = next(iter(regular_seasons))
        else:
            default_season = season_hint or (next(iter(explicit_seasons)) if len(explicit_seasons) == 1 else 1)
        for source in sources:
            grouped.setdefault(_season_number(source.path or source.name) or default_season, []).append(source)
        if len(grouped) > 20:
            raise OrganizerReview("同一下载目录包含过多季度，已停止自动整理")
        planned = []
        target = None
        media_path = ""
        for season_number, season_sources in sorted(grouped.items()):
            current = resolve_media_target(
                tmdb_id,
                "variety" if media_type == "variety" else "tv",
                season_number,
                client=tmdb,
                category=category or media_type,
            )
            target = target or current
            if any(not _episodic_source_identity_is_safe(current, source) for source in season_sources):
                raise OrganizerReview(
                    f"第 {season_number} 季存在无法证明属于同一剧集的视频，未执行整理"
                )
            matcher_sources = [_matcher_source_with_dash_episode(source) for source in season_sources]
            matches, ambiguities = match_episode_files(current, matcher_sources)
            originals = {source.provider_file_id: source for source in season_sources}
            matches = [
                replace(match, source=originals.get(match.source.provider_file_id, match.source))
                for match in matches
            ]
            if ambiguities or not matches or any(match.confidence != "high" for match in matches):
                raise OrganizerReview(f"第 {season_number} 季存在低置信度或歧义集数，未执行整理")
            matched_ids = {match.source.provider_file_id for match in matches}
            if matched_ids != {source.provider_file_id for source in season_sources}:
                raise OrganizerReview(f"第 {season_number} 季存在未匹配视频，未执行整理")
            media_path = f"{target_category.rstrip('/')}/{build_media_folder_name(current.title, current.series_year)}"
            destination = f"{media_path}/{build_season_folder_name(season_number)}"
            for match in matches:
                pair = build_rename_pair(current, match)
                planned.append(
                    PlannedFile(
                        match.source,
                        pair.replacement,
                        destination,
                        season_number,
                        pair.confidence,
                        pair.reasons,
                    )
                )
        if target is None:
            raise OrganizerReview("没有可整理的剧集文件")
    planned.extend(_companion_files(planned, entries))
    _validate_plan_names(planned)
    return OrganizePlan(
        target,
        folder,
        source_path,
        media_path,
        category,
        tuple(planned),
        source_scope_path or normalize_save_root(source_path.rsplit("/", 1)[0]),
        loose_group_key,
    )


def _movie_source_identity_is_safe(target: MediaTarget, source: SourceFile) -> bool:
    """Reject a second feature-sized file that carries a different title.

    Multi-disc files named only ``CD1``/``Part 2`` remain valid, while a file
    with another textual identity must be reviewed even if it is large enough
    for the existing movie matcher to select it.
    """
    stem = os.path.splitext(unicodedata.normalize("NFKC", source.name))[0].casefold()
    years = set(_YEAR.findall(stem))
    if target.series_year and years and years != {str(target.series_year)}:
        return False
    residue = _YEAR.sub(" ", stem)
    residue = _SEASON.sub(" ", residue)
    residue = _strip_release_group(residue)
    residue = _RELEASE_NOISE.sub(" ", residue)
    residue = _GENERIC_MOVIE_FILE_WORDS.sub(" ", residue)
    residue = re.sub(r"(?i)(?:proper|repack|extended|uncut|directors?[ ._-]*cut|theatrical)", " ", residue)
    residue_key = _identity(residue)
    title_keys = {_identity(title) for title in target.search_titles if _identity(title)}
    return (
        residue_key in title_keys
        or not residue_key
        or residue_key.isdigit()
        or bool(re.fullmatch(r"[ivxlcdm]+", residue_key, re.I))
    )


def _episodic_source_identity_is_safe(target: MediaTarget, source: SourceFile) -> bool:
    """Reject an explicitly numbered episode that carries another show's title."""
    stem = os.path.splitext(unicodedata.normalize("NFKC", source.name))[0].casefold()
    stem = _strip_leading_release_tags(stem)
    residue = _strip_release_group(stem)
    residue = _FULL_DATE.sub(" ", residue)
    residue = _EPISODIC_MARKERS.sub(" ", residue)
    residue = _SEASON.sub(" ", residue)
    residue = _YEAR.sub(" ", residue)
    residue = _RELEASE_NOISE.sub(" ", residue)
    residue = _EPISODIC_GENERIC_WORDS.sub(" ", residue)
    residue = re.sub(r"(?i)(?:proper|repack|complete|final)", " ", residue)
    residue_key = _identity(residue)
    title_keys = {_identity(title) for title in target.search_titles if _identity(title)}
    return (
        residue_key in title_keys
        or not residue_key
        or residue_key.isdigit()
        or bool(re.fullmatch(r"[ivxlcdm]+", residue_key, re.I))
    )


def _matcher_source_with_dash_episode(source: SourceFile) -> SourceFile:
    """Expose anime-style ``Title - 01`` to the matcher without changing shared semantics."""
    def explicit(match: re.Match[str]) -> str:
        return f" E{int(match.group(1)):02d} "

    return replace(
        source,
        name=_DASH_EPISODE_NUMBER.sub(explicit, source.name),
        path=_DASH_EPISODE_NUMBER.sub(explicit, source.path),
    )


def _folder_query(value: str) -> tuple[str, str]:
    normalized = _strip_release_group(unicodedata.normalize("NFKC", str(value or "")))
    year_match = _YEAR.search(normalized)
    year = year_match.group(1) if year_match else ""
    cleaned = re.sub(r"[\[【（(][^\]】）)]*(?:2160|1080|720|4k|hdr|dv|web|bluray|remux|x26|hevc|中字|国语)[^\]】）)]*[\]】）)]", " ", normalized, flags=re.I)
    cleaned = _YEAR.sub(" ", cleaned)
    cleaned = re.sub(r"[\[【（(]\s*[\]】）)]", " ", cleaned)
    cleaned = re.sub(r"(?i)(?:S\d{1,2}(?:E\d{1,4})?|Season[ ._-]*\d{1,2}|第\s*\d{1,2}\s*季)", " ", cleaned)
    cleaned = _RELEASE_NOISE.sub(" ", cleaned)
    cleaned = re.sub(r"[._]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_.")
    return cleaned, year


def _loose_media_groups(
    entries: tuple[RemoteEntry, ...],
    category: str,
) -> list[tuple[str, str, tuple[RemoteEntry, ...]]]:
    """Group only direct files whose title identity can be derived safely."""
    direct_files = [
        RemoteEntry(item.file_id, item.parent_id, item.name, item.size, False, item.relative_path or item.name)
        for item in entries
        if not item.is_dir
    ]
    videos = sorted(
        (item for item in direct_files if _entry_is_video(item)),
        key=lambda item: (item.name.casefold(), item.file_id),
    )
    groups: dict[str, dict[str, Any]] = {}
    video_keys: dict[str, str] = {}
    for video in videos:
        key, display_name = _loose_group_identity(video, category)
        if not key:
            key = f"unknown:{video.file_id}"
            display_name = os.path.splitext(video.name)[0]
        bucket = groups.setdefault(key, {"display_name": display_name, "entries": []})
        bucket["entries"].append(video)
        video_keys[video.file_id] = key
    for companion in direct_files:
        if companion.file_id in video_keys or os.path.splitext(companion.name)[1].casefold() not in _COMPANION_EXTENSIONS:
            continue
        candidates: list[tuple[int, str]] = []
        for video in videos:
            stem = os.path.splitext(video.name)[0]
            if companion.name.casefold().startswith(f"{stem}.".casefold()):
                candidates.append((len(stem), video_keys[video.file_id]))
        candidates.sort(reverse=True)
        if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
            groups[candidates[0][1]]["entries"].append(companion)
    result: list[tuple[str, str, tuple[RemoteEntry, ...]]] = []
    for key, value in groups.items():
        grouped_entries = tuple(
            sorted(value["entries"], key=lambda item: (item.name.casefold(), item.file_id))
        )
        result.append((key, str(value["display_name"]), grouped_entries))
    return sorted(result, key=lambda item: (item[1].casefold(), item[0]))


def _loose_group_identity(entry: RemoteEntry, category: str) -> tuple[str, str]:
    stem = os.path.splitext(unicodedata.normalize("NFKC", entry.name))[0]
    episodic = category in {"tv", "anime", "variety"} or bool(
        _SEASON.search(stem) or _EPISODIC_MARKERS.search(stem)
    )
    if episodic:
        residue = _strip_release_group(stem)
        residue = _strip_leading_release_tags(residue)
        residue = _FULL_DATE.sub(" ", residue)
        year_match = _YEAR.search(residue)
        year = year_match.group(1) if year_match else ""
        residue = _EPISODIC_MARKERS.sub(" ", residue)
        residue = _SEASON.sub(" ", residue)
        residue = _YEAR.sub(" ", residue)
        residue = _RELEASE_NOISE.sub(" ", residue)
        residue = _EPISODIC_GENERIC_WORDS.sub(" ", residue)
        residue = re.sub(r"[\[【（(]\s*[\]】）)]", " ", residue)
        title = re.sub(r"\s+", " ", re.sub(r"[._]+", " ", residue)).strip(" -_.")
        if not title:
            return "", stem
        season = _season_number(stem)
        display = ".".join(value for value in (title, year, f"S{season:02d}" if season else "") if value)
        return f"episodic:{_identity(title)}:{year}", display
    query, query_year = _folder_query(stem)
    query = _GENERIC_MOVIE_FILE_WORDS.sub(" ", query)
    query = re.sub(r"\s+", " ", query).strip(" -_.")
    if not query:
        return "", stem
    display = ".".join(value for value in (query, query_year) if value)
    return f"movie:{_identity(query)}:{query_year}", display


def _match_tmdb(
    tmdb: TmdbClient,
    query: str,
    year: str,
    category: str,
    episodic_hint: bool,
) -> tuple[int, str]:
    search_type = (
        "movie"
        if category in {"movie", "concert", "documentary"}
        else "variety"
        if category == "variety"
        else "tv"
        if category in {"tv", "anime"}
        else "all"
    )
    response = tmdb.search(query, search_type)
    if response.get("error"):
        raise RuntimeError(f"TMDB 查询失败：{response['error']}")
    raw_results = [item for item in (response.get("results") or []) if isinstance(item, dict)]
    if search_type == "all":
        if episodic_hint:
            candidates = [item for item in raw_results if item.get("media_type") != "movie"][:8]
        else:
            movies = [item for item in raw_results if item.get("media_type") == "movie"]
            episodic = [item for item in raw_results if item.get("media_type") != "movie"]
            candidates = [*movies[:4], *episodic[:4]]
            selected_ids = {id(item) for item in candidates}
            candidates.extend(item for item in raw_results if id(item) not in selected_ids and len(candidates) < 8)
    else:
        candidates = raw_results[:8]
    scored: list[tuple[float, dict[str, Any]]] = []
    query_key = _identity(query)
    for item in candidates:
        if not item.get("tmdb_id"):
            continue
        item_type = "movie" if item.get("media_type") == "movie" else "variety" if item.get("media_type") == "variety" else "tv"
        if episodic_hint and item_type == "movie":
            continue
        titles = [str(item.get("title") or "")]
        detail: dict[str, Any] = {}
        try:
            resolved = tmdb.details(item_type, int(item["tmdb_id"]))
            detail = resolved if isinstance(resolved, dict) and not resolved.get("error") else {}
        except Exception:
            detail = {}
        if category == "anime" and not _is_animation_detail(detail):
            continue
        titles.extend(
            str(value or "")
            for value in (detail.get("title"), detail.get("original_title"), *(detail.get("aliases") or ()))
        )
        title_keys = [_identity(title) for title in titles if _identity(title)]
        if not title_keys:
            continue
        score = max(_title_match_score(query_key, title_key) for title_key in title_keys)
        item_year = str(item.get("year") or detail.get("year") or "")[:4]
        if year and item_year:
            score += 20 if year == item_year else -45
        if category in {"movie", "concert", "documentary"} and item_type == "movie":
            score += 12
        elif category in {"tv", "anime"} and item_type == "tv":
            score += 12
        elif category == "variety" and item_type == "variety":
            score += 12
        scored.append((score, item))
    scored.sort(key=lambda value: value[0], reverse=True)
    if not scored or scored[0][0] < 100:
        raise OrganizerReview("TMDB 未找到高置信度匹配，未执行任何文件操作")
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 12:
        raise OrganizerReview("TMDB 存在多个接近结果，未执行任何文件操作")
    item = scored[0][1]
    media_type = "movie" if item.get("media_type") == "movie" else "variety" if item.get("media_type") == "variety" else "tv"
    return int(item["tmdb_id"]), media_type


def _is_animation_detail(detail: dict[str, Any]) -> bool:
    for raw in detail.get("genres") or ():
        if isinstance(raw, dict):
            if int(raw.get("id") or 0) == 16:
                return True
            value = str(raw.get("name") or "")
        else:
            value = str(raw or "")
        if _identity(value) in {"16", "animation", "anime", "动画", "動畫", "アニメーション"}:
            return True
    return False


def _title_match_score(query_key: str, title_key: str) -> float:
    if title_key == query_key:
        return 100.0
    if title_key in query_key or query_key in title_key:
        return 84.0
    return 80.0 * SequenceMatcher(None, query_key, title_key).ratio()


def _identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _strip_release_group(value: str) -> str:
    """Strip ``-GROUP`` only when it follows real release/episode evidence."""
    normalized = str(value or "")
    evidence = [
        *(match.end() for match in _RELEASE_NOISE.finditer(normalized)),
        *(match.end() for match in _EPISODIC_MARKERS.finditer(normalized)),
        *(match.end() for match in _SEASON.finditer(normalized)),
        *(match.end() for match in _YEAR.finditer(normalized)),
    ]
    separator = normalized.rfind("-")
    if not evidence or separator < max(evidence):
        return normalized
    suffix = normalized[separator + 1:].strip()
    if not _RELEASE_GROUP_NAME.fullmatch(suffix):
        return normalized
    return normalized[:separator].rstrip()


def _strip_leading_release_tags(value: str) -> str:
    """Drop anime release tags only when a textual title still follows them."""
    normalized = str(value or "")
    candidate = _LEADING_RELEASE_TAGS.sub("", normalized, count=1).strip()
    if not candidate or candidate == normalized:
        return normalized
    probe = _FULL_DATE.sub(" ", candidate)
    probe = _EPISODIC_MARKERS.sub(" ", probe)
    probe = _SEASON.sub(" ", probe)
    probe = _YEAR.sub(" ", probe)
    probe = _RELEASE_NOISE.sub(" ", probe)
    probe = _EPISODIC_GENERIC_WORDS.sub(" ", probe)
    return candidate if _identity(probe) else normalized


def _season_number(value: str) -> int | None:
    match = _SEASON.search(unicodedata.normalize("NFKC", str(value or "")))
    if not match:
        return None
    number = int(next(group for group in match.groups() if group is not None))
    return number if 0 < number <= 99 else None


def _movie_part_number(value: str) -> int | None:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    match = _MOVIE_PART_NUMBER.search(normalized)
    if match:
        number = int(match.group(1))
        return number if 0 < number <= 99 else None
    chinese = _CHINESE_MOVIE_PART.search(normalized)
    if not chinese:
        return None
    return 1 if chinese.group(0).startswith("上") else 2


def _category_for_scope(settings: Settings, provider: str, child_name: str) -> str:
    matches = [
        key
        for key, value in settings.provider_category_paths(provider).items()
        if str(value or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] == child_name
    ]
    return matches[0] if len(matches) == 1 else ""


def _direct_child_name(root: str, path: str) -> str:
    source_root = normalize_save_root(root)
    selected = normalize_save_root(path)
    prefix = f"{source_root.rstrip('/')}/"
    if not selected.startswith(prefix):
        raise RuntimeError("已选整理目录不属于云下载根目录")
    relative = selected[len(prefix):]
    if not relative or "/" in relative:
        raise RuntimeError("云下载整理只能处理云下载根下的直接子目录")
    return relative


def _inventory_fingerprint(folder: RemoteEntry, entries: tuple[RemoteEntry, ...]) -> str:
    values = [f"folder\0{folder.file_id}\0{folder.name}"]
    values.extend(
        f"{item.file_id}\0{item.parent_id}\0{item.relative_path}\0{item.size}\0{int(item.is_dir)}"
        for item in sorted(entries, key=lambda item: (item.relative_path.casefold(), item.file_id))
    )
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()[:24]


def _validate_plan_names(files: list[PlannedFile]) -> None:
    seen: set[tuple[str, str]] = set()
    source_shapes: set[tuple[str, int, str]] = set()
    for item in files:
        key = (item.destination_path.casefold(), item.replacement.casefold())
        if key in seen:
            raise OrganizerReview("多个源文件会生成相同目标名称，未执行整理")
        seen.add(key)
        shape = (item.source.name, int(item.source.size), item.destination_path)
        if shape in source_shapes:
            raise OrganizerReview("同一目标目录存在无法区分的同名源文件，未执行整理")
        source_shapes.add(shape)


def _companion_files(
    video_plan: list[PlannedFile],
    entries: tuple[RemoteEntry, ...],
) -> list[PlannedFile]:
    """Carry conservatively associated subtitles/NFO files with their video."""
    planned_source_ids = {item.source.provider_file_id for item in video_plan}
    companions: list[PlannedFile] = []
    for entry in entries:
        extension = os.path.splitext(entry.name)[1].casefold()
        if entry.is_dir or entry.file_id in planned_source_ids or extension not in _COMPANION_EXTENSIONS:
            continue
        candidates: list[tuple[int, PlannedFile, str]] = []
        for video in video_plan:
            if entry.parent_id != video.source.provider_parent_id:
                continue
            source_stem = os.path.splitext(video.source.name)[0]
            if not entry.name.casefold().startswith(source_stem.casefold()):
                continue
            remainder = entry.name[len(source_stem):]
            if not remainder.startswith("."):
                continue
            replacement_stem = os.path.splitext(video.replacement)[0]
            candidates.append((len(source_stem), video, f"{replacement_stem}{remainder}"))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates or (len(candidates) > 1 and candidates[0][0] == candidates[1][0]):
            continue
        _length, video, replacement = candidates[0]
        companions.append(
            PlannedFile(
                SourceFile(entry.name, entry.size, entry.relative_path, entry.file_id, entry.parent_id),
                replacement,
                video.destination_path,
                video.season_number,
                "high",
                ("video_companion",),
            )
        )
    return companions


def _preflight_destinations(
    adapter: OrganizerProvider,
    plan: OrganizePlan,
    *,
    reusable_targets: dict[str, dict[str, Any]] | None = None,
) -> None:
    reusable = reusable_targets or {}
    for path, planned in _group_plan_files(plan).items():
        _existing_destination_matches(adapter, path, planned, reusable_targets=reusable)


def _execute_copy(
    settings: Settings,
    adapter: OrganizerProvider,
    plan: OrganizePlan,
    fingerprint: str,
    *,
    job_id: int | None = None,
    reusable_targets: dict[str, dict[str, Any]] | None = None,
    source_entries: tuple[RemoteEntry, ...] | None = None,
) -> None:
    reusable = reusable_targets or {}
    expected_source = source_entries or _read_plan_source_tree(adapter, plan)
    staging_root = (
        settings.p115_staging_path if adapter.provider == "p115" else settings.quark_staging_path
    ).rstrip("/")
    for index, (destination, planned) in enumerate(_group_plan_files(plan).items(), start=1):
        _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=planned)
        completed = _existing_destination_matches(
            adapter,
            destination,
            planned,
            reusable_targets=reusable,
        )
        expected_target_ids = {source_id: entry.file_id for source_id, entry in completed.items()}
        pending = [item for item in planned if item.source.provider_file_id not in completed]
        if not pending:
            verified = _verify_destination(adapter, destination, planned, expected_target_ids=expected_target_ids)
            if job_id is not None:
                _record_verified_targets(job_id, destination, verified)
            continue
        staging_leaf = str(index) if job_id is None else f"{index}-{secrets.token_hex(16)}"
        fresh_staging_path = f"{staging_root}/cloud-download-organizer/{fingerprint}/{staging_leaf}"
        receipt_staging_paths = {
            str(reusable.get(item.source.provider_file_id, {}).get("staging_path") or "")
            for item in pending
            if str(reusable.get(item.source.provider_file_id, {}).get("staging_path") or "")
        }
        copy_intents = _copy_intent_bindings(job_id) if job_id is not None else {}
        receipt_staging_paths.update(
            str(copy_intents.get(item.source.provider_file_id, {}).get("staging_path") or "")
            for item in pending
            if str(copy_intents.get(item.source.provider_file_id, {}).get("staging_path") or "")
        )
        staging_path = next(iter(receipt_staging_paths)) if len(receipt_staging_paths) == 1 else fresh_staging_path
        staging_id = adapter.directory_id(staging_path) if staging_path != fresh_staging_path else ""
        if not staging_id:
            staging_path = fresh_staging_path
            staging_id = adapter.ensure_directory(staging_path)
        staging_entries = tuple(adapter.list_directory(staging_id))
        received = _match_staging_files_with_bindings(
            pending,
            staging_entries,
            reusable,
            copy_intents,
            staging_path,
            staging_id,
        )
        bound_entry_ids = {entry.file_id for entry in received.values()}
        unbound_files = [
            entry for entry in staging_entries
            if not entry.is_dir and entry.file_id not in bound_entry_ids
        ]
        if unbound_files:
            raise OrganizerReview("整理暂存目录存在没有本任务回执的文件，未冒险认领或覆盖")
        missing = [item for item in pending if item.source.provider_file_id not in received]
        if missing:
            if job_id is not None:
                _record_copy_intents(
                    job_id,
                    destination,
                    staging_path,
                    staging_id,
                    missing,
                    staging_entries,
                )
                copy_intents = _copy_intent_bindings(job_id)
            for chunk in _chunks(missing):
                _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=chunk)
                adapter.copy([item.source.provider_file_id for item in chunk], staging_id)
                if job_id is not None:
                    _acknowledge_copy_intents(
                        job_id,
                        {item.source.provider_file_id for item in chunk},
                    )
            if job_id is not None:
                copy_intents = _copy_intent_bindings(job_id)
            deadline = time.monotonic() + min(30, max(1, adapter.request_timeout_seconds))
            while True:
                _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=pending)
                current_staging = tuple(adapter.list_directory(staging_id))
                received = (
                    _match_staging_files_with_bindings(
                        pending,
                        current_staging,
                        reusable,
                        copy_intents,
                        staging_path,
                        staging_id,
                    )
                    if job_id is not None
                    else _match_staging_files(pending, current_staging)
                )
                if len(received) == len(pending):
                    received_ids = {value.file_id for value in received.values()}
                    if any(
                        not entry.is_dir and entry.file_id not in received_ids
                        for entry in current_staging
                    ):
                        raise OrganizerReview("复制期间暂存目录出现未授权文件，已停止续作")
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("复制任务已提交，但暂存目录未在时限内出现全部文件")
                time.sleep(1)
        rename_pairs = [
            (received[item.source.provider_file_id].file_id, item.replacement)
            for item in pending
            if received[item.source.provider_file_id].name != item.replacement
        ]
        for chunk in _chunks(rename_pairs):
            _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=pending)
            adapter.rename(chunk)
        if job_id is not None:
            _record_write_receipts(job_id, destination, staging_path, pending, received)
        _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=pending)
        final_id = adapter.ensure_directory(destination)
        staged_ids = [received[item.source.provider_file_id].file_id for item in pending]
        expected_target_ids.update(
            (item.source.provider_file_id, received[item.source.provider_file_id].file_id)
            for item in pending
        )
        for chunk in _chunks(staged_ids):
            _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=pending)
            adapter.move(chunk, final_id)
        verified = _verify_destination(adapter, destination, planned, expected_target_ids=expected_target_ids)
        if job_id is not None:
            _record_verified_targets(job_id, destination, verified)
        if not adapter.list_directory(staging_id):
            try:
                _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=[])
                adapter.trash(staging_id)
            except ORGANIZER_PROVIDER_ERRORS:
                # The organized target and preserved source are authoritative;
                # an empty internal staging folder is safe to leave for a
                # later maintenance pass and must not turn success into a
                # misleading partial-transfer failure.
                pass
    _verify_source_snapshot(adapter, plan, _inventory_fingerprint(plan.source_folder, expected_source))


def _execute_move(
    adapter: OrganizerProvider,
    plan: OrganizePlan,
    *,
    job_id: int | None = None,
    reusable_targets: dict[str, dict[str, Any]] | None = None,
    source_entries: tuple[RemoteEntry, ...] | None = None,
) -> None:
    reusable = reusable_targets or {}
    expected_source = source_entries or _read_plan_source_tree(adapter, plan)
    for destination, planned in _group_plan_files(plan).items():
        current = _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=[])
        completed = _existing_destination_matches(
            adapter,
            destination,
            planned,
            reusable_targets=reusable,
        )
        expected_target_ids = {source_id: entry.file_id for source_id, entry in completed.items()}
        pending = [item for item in planned if item.source.provider_file_id not in completed]
        if pending:
            current = _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=pending)
            current_by_id = {item.file_id: item for item in current}
            _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=pending)
            final_id = adapter.ensure_directory(destination)
            rename_pairs = [
                (item.source.provider_file_id, item.replacement)
                for item in pending
                if current_by_id[item.source.provider_file_id].name != item.replacement
            ]
            for chunk in _chunks(rename_pairs):
                chunk_ids = {file_id for file_id, _name in chunk}
                required = [item for item in pending if item.source.provider_file_id in chunk_ids]
                _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=required)
                adapter.rename(chunk)
            for chunk in _chunks(pending):
                _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=chunk)
                adapter.move([item.source.provider_file_id for item in chunk], final_id)
            expected_target_ids.update(
                (item.source.provider_file_id, item.source.provider_file_id)
                for item in pending
            )
        verified = _verify_destination(adapter, destination, planned, expected_target_ids=expected_target_ids)
        if job_id is not None:
            _record_verified_targets(job_id, destination, verified)
    if plan.loose_group_key:
        current = _ensure_mutation_boundary(adapter, plan, expected_source, job_id=job_id, required=[])
        remaining = {
            item.file_id for item in current
            if item.file_id in {planned.source.provider_file_id for planned in plan.files}
        }
        if remaining:
            raise RuntimeError("直接媒体文件未全部移离云下载子目录")
        return
    _cleanup_residual_files(adapter, plan, job_id=job_id, source_entries=expected_source)


def _group_plan_files(plan: OrganizePlan) -> dict[str, list[PlannedFile]]:
    groups: dict[str, list[PlannedFile]] = {}
    for item in plan.files:
        groups.setdefault(item.destination_path, []).append(item)
    return groups


def _match_staging_files(planned: list[PlannedFile], entries: tuple[RemoteEntry, ...]) -> dict[str, RemoteEntry]:
    matched: dict[str, RemoteEntry] = {}
    used: set[str] = set()
    for item in planned:
        candidates = [
            entry
            for entry in entries
            if not entry.is_dir
            and entry.file_id not in used
            and entry.name in {item.source.name, item.replacement}
            and (not item.source.size or entry.size == item.source.size)
        ]
        if len(candidates) > 1:
            raise RuntimeError(f"暂存目录存在多个无法区分的文件：{item.source.name}")
        if candidates:
            matched[item.source.provider_file_id] = candidates[0]
            used.add(candidates[0].file_id)
    return matched


def _match_staging_files_with_bindings(
    planned: list[PlannedFile],
    entries: tuple[RemoteEntry, ...],
    receipts: dict[str, dict[str, Any]],
    intents: dict[str, dict[str, Any]],
    staging_path: str,
    staging_id: str,
) -> dict[str, RemoteEntry]:
    """Match only provider IDs covered by a receipt or a pre-copy intent."""
    matched: dict[str, RemoteEntry] = {}
    used: set[str] = set()
    for item in planned:
        source_id = item.source.provider_file_id
        receipt = receipts.get(source_id)
        if isinstance(receipt, dict) and str(receipt.get("staging_path") or "") == staging_path:
            expected_id = str(receipt.get("file_id") or "")
            exact = [
                entry for entry in entries
                if not entry.is_dir
                and entry.file_id == expected_id
                and entry.name in {item.source.name, item.replacement}
                and (not item.source.size or entry.size == item.source.size)
            ]
            if len(exact) == 1:
                matched[source_id] = exact[0]
                used.add(exact[0].file_id)
                continue
        intent = intents.get(source_id)
        if not _copy_intent_matches(intent, item, staging_path, staging_id):
            continue
        baseline_ids = {str(value) for value in intent.get("baseline_ids") or ()}
        candidates = [
            entry for entry in entries
            if not entry.is_dir
            and entry.file_id not in baseline_ids
            and entry.file_id not in used
            and entry.name in {item.source.name, item.replacement}
            and (not item.source.size or entry.size == item.source.size)
        ]
        if len(candidates) > 1:
            raise OrganizerReview(f"复制意图对账到多个无法区分的文件：{item.source.name}")
        if candidates:
            matched[source_id] = candidates[0]
            used.add(candidates[0].file_id)
    return matched


def _copy_intent_matches(
    intent: dict[str, Any] | None,
    item: PlannedFile,
    staging_path: str,
    staging_id: str,
) -> bool:
    return bool(
        isinstance(intent, dict)
        and str(intent.get("staging_path") or "") == staging_path
        and str(intent.get("staging_id") or "") == staging_id
        and normalize_save_root(str(intent.get("destination") or ""))
        == normalize_save_root(item.destination_path)
        and str(intent.get("source_name") or "") == item.source.name
        and str(intent.get("replacement") or "") == item.replacement
        and int(intent.get("size") or 0) == int(item.source.size or 0)
        and bool(intent.get("acknowledged"))
    )


def _existing_destination_matches(
    adapter: OrganizerProvider,
    path: str,
    planned: list[PlannedFile],
    *,
    reusable_targets: dict[str, dict[str, Any]],
) -> dict[str, RemoteEntry]:
    directory_id = adapter.directory_id(path)
    if not directory_id:
        return {}
    entries = list(adapter.list_directory(directory_id))
    matched: dict[str, RemoteEntry] = {}
    for item in planned:
        same_name = [entry for entry in entries if entry.name.casefold() == item.replacement.casefold()]
        if not same_name:
            continue
        exact = [
            entry for entry in same_name
            if not entry.is_dir
            and entry.name == item.replacement
            and (not item.source.size or entry.size == item.source.size)
        ]
        source_id = item.source.provider_file_id
        binding = reusable_targets.get(source_id)
        binding_matches = (
            isinstance(binding, dict)
            and normalize_save_root(str(binding.get("path") or "")) == normalize_save_root(path)
            and str(binding.get("file_id") or "") == (exact[0].file_id if len(exact) == 1 else "")
            and str(binding.get("name") or "") == item.replacement
            and int(binding.get("size") or 0) == int(item.source.size or 0)
        )
        if len(same_name) != 1 or len(exact) != 1 or not binding_matches:
            raise OrganizerReview(f"目标目录已有同名文件：{item.replacement}；未覆盖现有内容")
        matched[source_id] = exact[0]
    return matched


def _verify_destination(
    adapter: OrganizerProvider,
    path: str,
    planned: list[PlannedFile],
    *,
    expected_target_ids: dict[str, str],
) -> dict[str, RemoteEntry]:
    directory_id = adapter.directory_id(path)
    if not directory_id:
        raise RuntimeError("正式媒体库目标目录未确认")
    entries = [item for item in adapter.list_directory(directory_id) if not item.is_dir]
    verified: dict[str, RemoteEntry] = {}
    for item in planned:
        same_name = [
            entry
            for entry in entries
            if entry.name == item.replacement
        ]
        expected_file_id = str(expected_target_ids.get(item.source.provider_file_id) or "")
        matches = [
            entry for entry in same_name
            if entry.file_id == expected_file_id
            and (not item.source.size or entry.size == item.source.size)
        ]
        if not expected_file_id or len(same_name) != 1 or len(matches) != 1:
            raise RuntimeError(f"目标文件未唯一确认：{item.replacement}")
        verified[item.source.provider_file_id] = matches[0]
    return verified


def _chunks(values: list[Any], size: int = REMOTE_MUTATION_BATCH_SIZE) -> list[list[Any]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _verify_source_folder_scope(adapter: OrganizerProvider, plan: OrganizePlan) -> None:
    scope_path = _plan_scope_path(plan)
    scope_id = adapter.directory_id(scope_path)
    if plan.loose_group_key:
        if not scope_id or scope_id != plan.source_folder.file_id:
            raise OrganizerReview("已选云下载子目录身份已变化，未执行远端操作")
        return
    if not scope_id or scope_id != plan.source_folder.parent_id:
        raise OrganizerReview("源媒体目录已不属于原先授权的云下载子目录，未执行远端操作")
    matches = [
        item
        for item in adapter.list_directory(scope_id)
        if item.is_dir
        and item.file_id == plan.source_folder.file_id
        and item.name == plan.source_folder.name
        and item.parent_id == scope_id
    ]
    if len(matches) != 1:
        raise OrganizerReview("源媒体目录身份或名称已经变化，未执行远端操作")


def _verify_current_authorization(
    settings: Settings,
    adapter: OrganizerProvider,
    plan: OrganizePlan,
) -> None:
    """Re-authorize the exact source scope and fixed target mapping."""
    provider = adapter.provider
    scope_path = _plan_scope_path(plan)
    selected = {
        normalize_save_root(value)
        for value in settings.provider_cloud_download_organizer_directories(provider)
    }
    if scope_path not in selected:
        raise OrganizerStopped("该云下载子目录已取消授权；未继续写入或清理")
    download_root = normalize_save_root(settings.provider_cloud_download_path(provider))
    library_root = normalize_save_root(settings.provider_save_root(provider))
    try:
        child_name = _direct_child_name(download_root, scope_path)
    except (RuntimeError, ValueError) as exc:
        raise OrganizerStopped("云下载根目录已变更；原整理计划已停止") from exc
    target_category = normalize_save_root(f"{library_root.rstrip('/')}/{child_name}")
    for item in plan.files:
        destination = normalize_save_root(item.destination_path)
        if destination != target_category and not destination.startswith(f"{target_category.rstrip('/')}/"):
            raise OrganizerStopped("正式媒体库根目录或子目录映射已变更；原计划已停止")


def _plan_scope_path(plan: OrganizePlan) -> str:
    value = plan.source_scope_path or plan.source_path.rsplit("/", 1)[0]
    return normalize_save_root(value)


def _verify_source_snapshot(adapter: OrganizerProvider, plan: OrganizePlan, fingerprint: str) -> None:
    _verify_source_folder_scope(adapter, plan)
    current = _read_plan_source_tree(adapter, plan)
    if _inventory_fingerprint(plan.source_folder, current) != fingerprint:
        raise OrganizerReview("下载目录在核对期间发生变化，已停止本轮整理并重新等待稳定")


def _verify_source_inventory_subset(
    adapter: OrganizerProvider,
    plan: OrganizePlan,
    expected_entries: tuple[RemoteEntry, ...],
    *,
    required: list[PlannedFile] | None = None,
) -> tuple[RemoteEntry, ...]:
    _verify_source_folder_scope(adapter, plan)
    current = _read_plan_source_tree(adapter, plan, expected_entries=expected_entries)
    expected = {item.file_id: item for item in expected_entries}
    replacement_by_id = {
        item.source.provider_file_id: item.replacement
        for item in plan.files
    }
    for item in current:
        original = expected.get(item.file_id)
        if original is None:
            raise OrganizerReview("源媒体目录出现了计划外的新到达文件或目录，已停止后续写入和清理")
        allowed_names = {original.name}
        if item.file_id in replacement_by_id:
            allowed_names.add(replacement_by_id[item.file_id])
        if (
            item.name not in allowed_names
            or item.parent_id != original.parent_id
            or int(item.size or 0) != int(original.size or 0)
            or bool(item.is_dir) != bool(original.is_dir)
        ):
            raise OrganizerReview("源文件身份、名称、大小或所在目录已变化，已停止后续写入和清理")
    current_ids = {item.file_id for item in current}
    for planned in required or []:
        if planned.source.provider_file_id not in current_ids:
            raise OrganizerReview(f"计划源文件已不存在或已离开授权目录：{planned.source.name}")
    return current


def _ensure_mutation_boundary(
    adapter: OrganizerProvider,
    plan: OrganizePlan,
    expected_entries: tuple[RemoteEntry, ...],
    *,
    job_id: int | None,
    required: list[PlannedFile],
) -> tuple[RemoteEntry, ...]:
    if job_id is not None:
        _ensure_job_active(job_id)
        _verify_current_authorization(get_settings(), adapter, plan)
    return _verify_source_inventory_subset(adapter, plan, expected_entries, required=required)


def _cleanup_residual_files(
    adapter: OrganizerProvider,
    plan: OrganizePlan,
    *,
    job_id: int | None = None,
    source_entries: tuple[RemoteEntry, ...] | None = None,
) -> None:
    """Trash only exact, pre-existing residual files; retain every directory."""
    expected = source_entries or _read_media_tree(adapter, plan.source_folder)
    planned_ids = {item.source.provider_file_id for item in plan.files}
    residual = {
        item.file_id: item
        for item in expected
        if not item.is_dir and item.file_id not in planned_ids
    }
    for residual_entry in sorted(residual.values(), key=lambda item: (item.relative_path.casefold(), item.file_id)):
        current = _ensure_mutation_boundary(adapter, plan, expected, job_id=job_id, required=[])
        current_files = [item for item in current if not item.is_dir]
        if any(_entry_is_video(item) for item in current_files):
            raise OrganizerReview("目标已核验，但源目录仍有疑似视频；为避免误删已保留全部源残留")
        if any(item.file_id not in residual for item in current_files):
            raise OrganizerReview("目标已核验，但源目录出现新到达或未完全移动的文件；已保留全部源残留")
        matched = [
            item
            for item in current_files
            if item.file_id == residual_entry.file_id
            and item.name == residual_entry.name
            and item.parent_id == residual_entry.parent_id
            and int(item.size or 0) == int(residual_entry.size or 0)
        ]
        if not matched:
            continue
        adapter.trash(residual_entry.file_id)
        deadline = time.monotonic() + min(30, max(1, adapter.request_timeout_seconds))
        while True:
            current = _ensure_mutation_boundary(adapter, plan, expected, job_id=job_id, required=[])
            if all(item.file_id != residual_entry.file_id for item in current):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"残留文件回收站操作未在时限内确认：{residual_entry.name}；"
                    "可能已部分清理，未标记整理完成"
                )
            time.sleep(0.25)
    # A final exact-ID read catches no-op trash calls and late arrivals.  The
    # directory shell and all directories are intentionally retained.
    current = _ensure_mutation_boundary(adapter, plan, expected, job_id=job_id, required=[])
    remaining_residuals = [
        item for item in current
        if not item.is_dir and item.file_id in residual
    ]
    if remaining_residuals:
        raise RuntimeError("残留文件未全部确认进入回收站；未标记整理完成")
    if any(not item.is_dir and _entry_is_video(item) for item in current):
        raise OrganizerReview("残留清理期间出现疑似视频；已停止清理并保留源目录壳")


def _source_inventory_has_additions(
    plan: OrganizePlan,
    expected_entries: tuple[RemoteEntry, ...],
    current_entries: tuple[RemoteEntry, ...],
) -> bool:
    """Accept only idempotent rename/move progress plus genuinely new IDs."""
    expected = {item.file_id: item for item in expected_entries}
    replacement_by_id = {
        item.source.provider_file_id: item.replacement
        for item in plan.files
    }
    additions = False
    for item in current_entries:
        original = expected.get(item.file_id)
        if original is None:
            additions = True
            continue
        allowed_names = {original.name}
        replacement = replacement_by_id.get(item.file_id)
        if replacement:
            allowed_names.add(replacement)
        if (
            item.name not in allowed_names
            or item.parent_id != original.parent_id
            or int(item.size or 0) != int(original.size or 0)
            or bool(item.is_dir) != bool(original.is_dir)
        ):
            raise OrganizerReview("续作期间源文件身份、名称、大小或所在目录已变化")
    return additions


def _reconcile_move_targets_before_inventory_reset(
    job_id: int,
    adapter: OrganizerProvider,
    plan: OrganizePlan,
    current_entries: tuple[RemoteEntry, ...],
) -> bool:
    """Bind already-moved IDs before a concurrent arrival replaces the old plan."""
    reusable = {
        item.source.provider_file_id: {
            "path": item.destination_path,
            "file_id": item.source.provider_file_id,
            "name": item.replacement,
            "size": int(item.source.size or 0),
        }
        for item in plan.files
    }
    completed: dict[str, RemoteEntry] = {}
    verified_by_destination: dict[str, dict[str, RemoteEntry]] = {}
    for destination, planned in _group_plan_files(plan).items():
        matches = _existing_destination_matches(
            adapter,
            destination,
            planned,
            reusable_targets=reusable,
        )
        completed.update(matches)
        verified_by_destination.setdefault(destination, {}).update(matches)
    current_ids = {item.file_id for item in current_entries}
    missing = [
        item.source.name
        for item in plan.files
        if item.source.provider_file_id not in completed
        and item.source.provider_file_id not in current_ids
    ]
    if missing:
        raise OrganizerReview(
            "新内容到达前的移动结果无法按文件 ID 完整对账；已保留现状待核对"
        )
    for destination, verified in verified_by_destination.items():
        if verified:
            _record_verified_targets(job_id, destination, verified)
    return len(completed) == len(plan.files)


def _reset_job_for_new_inventory(
    job_id: int,
    fingerprint: str,
    previous_state: dict[str, Any],
) -> None:
    """End the old write-ahead cycle and start a fresh stability window."""
    fresh_state = {
        "fingerprint": fingerprint,
        "mode": "move" if str(previous_state.get("mode") or "") == "move" else "copy",
        "write_started": False,
        "verified_targets": previous_state.get("verified_targets")
        if isinstance(previous_state.get("verified_targets"), dict)
        else {},
        "write_receipts": previous_state.get("write_receipts")
        if isinstance(previous_state.get("write_receipts"), dict)
        else {},
        "copy_intents": previous_state.get("copy_intents")
        if isinstance(previous_state.get("copy_intents"), list)
        else [],
    }
    with db() as conn:
        cursor = conn.execute(
            """UPDATE transfer_jobs SET status='ready',stage='organizer_waiting_stable',
               message='检测到新到达内容，已保留上次写入回执并重新等待稳定',
               created_at=CURRENT_TIMESTAMP,finished_at=NULL,review_state='',
               tmdb_id=NULL,media_type='',season_number=NULL,renamed_file='',
               rename_pairs_json='[]',save_path='',external_provider_status=?
               WHERE id=? AND status!='stopped'""",
            (json.dumps(fresh_state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )
        if not cursor.rowcount:
            raise OrganizerStopped("任务已由用户停止，未开启新的稳定周期")
    update_media_workflow_step(job_id, "resource_search", "running", "检测到新到达内容，正在重新等待目录稳定")
    update_media_workflow_step(job_id, "tmdb_rename", "pending", "等待新内容稳定后重新核对 TMDB")
    update_media_workflow_step(job_id, "transfer", "pending", "等待新计划")


def _recover_started_loose_jobs(
    settings: Settings,
    adapter: OrganizerProvider,
    scope_path: str,
) -> dict[str, str]:
    """Recover direct-file jobs even after every source file left the scope."""
    with db() as conn:
        rows = conn.execute(
            """SELECT * FROM transfer_jobs
               WHERE provider=? AND request_source='cloud_download_organizer'
                 AND execution_key LIKE ? AND status NOT IN ('done','stopped')
               ORDER BY id""",
            (adapter.provider, f"organizer:{adapter.provider}:loose:%"),
        ).fetchall()
    outcomes: dict[str, str] = {}
    normalized_scope = normalize_save_root(scope_path)
    for raw in rows:
        row = dict(raw)
        state = _decode_job_state(row.get("external_provider_status"))
        if not bool(state.get("write_started")) or not state.get("loose_group_key"):
            continue
        if normalize_save_root(str(state.get("source_scope_path") or "/")) != normalized_scope:
            continue
        folder = RemoteEntry(
            str(state.get("source_folder_id") or ""),
            "",
            str(state.get("source_folder_name") or row.get("display_title") or "直接媒体文件"),
            is_dir=True,
        )
        source_path = str(state.get("source_path") or row.get("source_file") or "")
        execution_key = str(row.get("execution_key") or "")
        try:
            plan = _deserialize_plan(row, state, folder, source_path)
            expected = _deserialize_source_inventory(state.get("source_inventory"))
            current = _read_plan_source_tree(adapter, plan, expected_entries=expected)
            outcome = _recover_started_job(
                settings,
                adapter,
                folder,
                source_path,
                current,
                execution_key,
            )
        except OrganizerStopped:
            raise
        except Exception:
            outcome = "failed"
        if outcome is not None:
            outcomes[execution_key] = outcome
    return outcomes


def _recover_started_job(
    settings: Settings,
    adapter: OrganizerProvider,
    folder: RemoteEntry,
    source_path: str,
    entries: tuple[RemoteEntry, ...],
    execution_key: str,
) -> str | None:
    with db() as conn:
        raw = conn.execute(
            "SELECT * FROM transfer_jobs WHERE execution_key=? ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
    if not raw:
        return None
    row = dict(raw)
    state = _decode_job_state(row.get("external_provider_status"))
    status = str(row.get("status") or "")
    if status == "stopped" and bool(state.get("write_started")):
        return "waiting"
    if status == "done" or not bool(state.get("write_started")):
        return None
    job_id = int(row["id"])
    try:
        _ensure_job_active(job_id)
        if str(state.get("source_folder_id") or "") != folder.file_id:
            raise OrganizerReview("上次写入计划的源目录身份与当前目录不一致，无法自动续作")
        if normalize_save_root(str(state.get("source_path") or "")) != normalize_save_root(source_path):
            raise OrganizerReview("上次写入计划的源路径与当前路径不一致，无法自动续作")
        plan = _deserialize_plan(row, state, folder, source_path)
        expected = _deserialize_source_inventory(state.get("source_inventory"))
        if not plan.files or not expected:
            raise OrganizerReview("上次远端写入缺少可验证的持久化计划，已停止自动续作")
        _verify_current_authorization(settings, adapter, plan)
        _verify_source_folder_scope(adapter, plan)
        mode = "move" if str(state.get("mode") or "") == "move" else "copy"
        if _source_inventory_has_additions(plan, expected, entries):
            if mode == "move":
                all_completed = _reconcile_move_targets_before_inventory_reset(job_id, adapter, plan, entries)
                if all_completed:
                    completion = "已按文件 ID 恢复核验上次移动结果；并发新到达内容已保留"
                    if not _update_job(job_id, "running", "organizer_recovering", completion):
                        raise OrganizerStopped("任务已由用户停止")
                    complete_transfer_workflow_step(job_id, "done", "provider_completed", completion)
                    if not _update_job(job_id, "running", "organizer_post_processing", "旧计划已核验，正在生成 STRM 并通知入库"):
                        raise OrganizerStopped("任务已由用户停止，未触发后处理")
                    _ensure_job_active(job_id)
                    run_post_transfer_pipeline(
                        job_id,
                        provider=adapter.provider,
                        title=plan.target.title,
                        poster_url=plan.target.poster_url,
                        target_path=plan.media_path,
                        target_files=tuple(_verified_target_bindings(job_id).values()),
                    )
                    if not _update_job(job_id, "done", "organizer_completed", completion, finished=True):
                        raise OrganizerStopped("任务已由用户停止")
                    return "organized"
                with db() as conn:
                    refreshed = conn.execute(
                        "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
                        (job_id,),
                    ).fetchone()
                state = _decode_job_state(refreshed["external_provider_status"] if refreshed else "")
            _reset_job_for_new_inventory(job_id, _inventory_fingerprint(folder, entries), state)
            return None
        reusable = _verified_target_bindings(job_id)
        if mode == "copy":
            reusable = {**_write_receipt_bindings(job_id), **reusable}
        else:
            for item in plan.files:
                reusable.setdefault(
                    item.source.provider_file_id,
                    {
                        "path": item.destination_path,
                        "file_id": item.source.provider_file_id,
                        "name": item.replacement,
                        "size": int(item.source.size or 0),
                    },
                )
        completed: set[str] = set()
        for destination, planned in _group_plan_files(plan).items():
            completed.update(
                _existing_destination_matches(
                    adapter,
                    destination,
                    planned,
                    reusable_targets=reusable,
                )
            )
        unresolved = [item for item in plan.files if item.source.provider_file_id not in completed]
        required = list(plan.files) if mode == "copy" else unresolved
        current = _verify_source_inventory_subset(adapter, plan, expected, required=required)
        planned_ids = {item.source.provider_file_id for item in plan.files}
        if any(not item.is_dir and _entry_is_video(item) and item.file_id not in planned_ids for item in current):
            raise OrganizerReview("续作期间发现计划外疑似视频，已停止自动写入和清理")
        _ensure_job_active(job_id)
        if not _update_job(job_id, "running", "organizer_recovering", "正在核验并续作上次中断的云端整理"):
            raise OrganizerStopped("任务已由用户停止，未继续上次中断的整理")
        fingerprint = str(state.get("fingerprint") or _inventory_fingerprint(folder, expected))
        if mode == "copy":
            _execute_copy(
                settings,
                adapter,
                plan,
                fingerprint,
                job_id=job_id,
                reusable_targets=reusable,
                source_entries=expected,
            )
            completion = "已恢复并核验复制结果；云下载来源已保留"
        else:
            _execute_move(
                adapter,
                plan,
                job_id=job_id,
                reusable_targets=reusable,
                source_entries=expected,
            )
            completion = "已恢复并核验移动结果；已精确清理残留文件并保留源目录壳"
        _ensure_job_active(job_id)
        complete_transfer_workflow_step(job_id, "done", "provider_completed", completion)
        if not _update_job(job_id, "running", "organizer_post_processing", "目标已恢复核验，正在生成 STRM 并通知入库"):
            raise OrganizerStopped("任务已由用户停止；目标已恢复核验，未触发入库后处理")
        _ensure_job_active(job_id)
        run_post_transfer_pipeline(
            job_id,
            provider=adapter.provider,
            title=plan.target.title,
            poster_url=plan.target.poster_url,
            target_path=plan.media_path,
            target_files=tuple(_verified_target_bindings(job_id).values()),
        )
        if not _update_job(job_id, "done", "organizer_completed", completion, finished=True):
            raise OrganizerStopped("任务已由用户停止；远端目标已恢复核验")
        return "organized"
    except OrganizerReview as exc:
        message = str(exc)[:500]
        _update_job(job_id, "needs_review", "organizer_needs_review", message, finished=True, review_state="pending")
        complete_transfer_workflow_step(job_id, "needs_review", "needs_review", message)
        return "review"
    except OrganizerStopped as exc:
        message = str(exc)[:500]
        _update_job(job_id, "stopped", "organizer_stopped", message, finished=True)
        complete_transfer_workflow_step(job_id, "failed", "provider_failed", message)
        return "failed"
    except ORGANIZER_RECOVERABLE_ERRORS as exc:
        message = str(exc)[:500]
        _update_job(job_id, "failed", "organizer_failed", message, finished=True)
        complete_transfer_workflow_step(job_id, "failed", "provider_failed", message)
        return "failed"
    except Exception as exc:
        message = f"云下载整理恢复失败（{type(exc).__name__}）"
        _update_job(job_id, "failed", "organizer_failed", message, finished=True)
        complete_transfer_workflow_step(job_id, "failed", "provider_failed", message)
        return "failed"


def _deserialize_plan(
    row: dict[str, Any],
    state: dict[str, Any],
    folder: RemoteEntry,
    source_path: str,
) -> OrganizePlan:
    try:
        raw_files = json.loads(str(row.get("rename_pairs_json") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        raw_files = []
    files: list[PlannedFile] = []
    for raw in raw_files if isinstance(raw_files, list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("source"), dict):
            continue
        source_raw = raw["source"]
        source = SourceFile(
            str(source_raw.get("name") or ""),
            int(source_raw.get("size") or 0),
            str(source_raw.get("path") or ""),
            str(source_raw.get("provider_file_id") or ""),
            str(source_raw.get("provider_parent_id") or ""),
            str(source_raw.get("obj_category") or ""),
        )
        if not source.provider_file_id or not raw.get("replacement") or not raw.get("destination_path"):
            continue
        files.append(
            PlannedFile(
                source,
                str(raw["replacement"]),
                str(raw["destination_path"]),
                int(raw["season_number"]) if raw.get("season_number") is not None else None,
                str(raw.get("confidence") or "high"),
                tuple(str(value) for value in (raw.get("reasons") or ())),
            )
        )
    target = MediaTarget(
        int(row.get("tmdb_id") or 0),
        str(row.get("media_type") or "movie"),
        str(row.get("display_title") or folder.name),
        category=str(state.get("category") or ""),
        poster_url=str(state.get("poster_url") or ""),
    )
    return OrganizePlan(
        target,
        folder,
        source_path,
        str(row.get("save_path") or ""),
        str(state.get("category") or ""),
        tuple(files),
        str(state.get("source_scope_path") or ""),
        str(state.get("loose_group_key") or ""),
    )


def _deserialize_source_inventory(value: Any) -> tuple[RemoteEntry, ...]:
    if not isinstance(value, list):
        return ()
    result: list[RemoteEntry] = []
    for raw in value:
        if not isinstance(raw, dict) or not raw.get("file_id"):
            continue
        result.append(
            RemoteEntry(
                str(raw["file_id"]),
                str(raw.get("parent_id") or ""),
                str(raw.get("name") or ""),
                int(raw.get("size") or 0),
                bool(raw.get("is_dir")),
                str(raw.get("relative_path") or ""),
            )
        )
    return tuple(result)


def _stable_job(
    execution_key: str,
    provider: str,
    source_path: str,
    title: str,
    fingerprint: str,
    mode: str,
) -> dict[str, Any]:
    reset_workflow = False
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM transfer_jobs WHERE execution_key=? ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if row:
            job_id = int(row["id"])
            state = _decode_job_state(row["external_provider_status"])
            same_inventory = state.get("fingerprint") == fingerprint and state.get("mode") == mode
            status = str(row["status"])
            if same_inventory and status in {"ready", "done", "stopped"}:
                return dict(row)
            if same_inventory and status == "running":
                # A running row encountered under the process-wide scan lock is
                # an interrupted previous process.  Resume without reusing an
                # older inventory's stability timestamp.
                conn.execute(
                    """UPDATE transfer_jobs SET status='ready',stage='organizer_resuming',
                       message='检测到上次进程中断，正在核验已完成的远端操作',finished_at=NULL
                       WHERE id=? AND status='running'""",
                    (job_id,),
                )
            elif same_inventory:
                # A provider/TMDB failure is retried only after a fresh stable
                # interval, while its write-ahead state remains available for
                # safe reconciliation.
                conn.execute(
                    """UPDATE transfer_jobs SET status='ready',stage='organizer_waiting_stable',
                       message='上次尝试未完成，等待目录再次稳定',created_at=CURRENT_TIMESTAMP,
                       finished_at=NULL,review_state='' WHERE id=?""",
                    (job_id,),
                )
                reset_workflow = True
            else:
                verified_targets = state.get("verified_targets")
                write_receipts = state.get("write_receipts")
                fresh_state = {
                    "fingerprint": fingerprint,
                    "mode": mode,
                    "write_started": False,
                    "verified_targets": verified_targets if isinstance(verified_targets, dict) else {},
                    "write_receipts": write_receipts if isinstance(write_receipts, dict) else {},
                }
                conn.execute(
                    """UPDATE transfer_jobs SET status='ready',stage='organizer_waiting_stable',
                       message='目录内容已变化，重新等待稳定后整理',display_title=?,source_file=?,
                       created_at=CURRENT_TIMESTAMP,finished_at=NULL,review_state='',tmdb_id=NULL,
                       media_type='',season_number=NULL,renamed_file='',rename_pairs_json='[]',save_path='',
                       external_provider_status=? WHERE id=?""",
                    (
                        title,
                        source_path,
                        json.dumps(fresh_state, ensure_ascii=False, separators=(",", ":")),
                        job_id,
                    ),
                )
                reset_workflow = True
        else:
            state = {
                "fingerprint": fingerprint,
                "mode": mode,
                "write_started": False,
                "verified_targets": {},
                "write_receipts": {},
            }
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,source_file,
                   request_source,execution_key,external_provider_status)
                   VALUES('cloud',?,'ready','organizer_waiting_stable','等待下载目录稳定后再整理',?,?,
                   'cloud_download_organizer',?,?)""",
                (
                    provider,
                    title,
                    source_path,
                    execution_key,
                    json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            job_id = int(cursor.lastrowid)
            reset_workflow = True
    initialize_media_workflow(job_id)
    if reset_workflow:
        update_media_workflow_step(job_id, "resource_search", "running", "已发现云下载媒体目录，正在等待内容稳定")
        update_media_workflow_step(job_id, "tmdb_rename", "pending", "等待目录稳定后核对 TMDB")
        update_media_workflow_step(job_id, "transfer", "pending", "等待 TMDB 与文件名核对")
    with db() as conn:
        return dict(conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (job_id,)).fetchone())


def _start_run_job(provider: str, source_path: str, save_path: str) -> int:
    execution_key = f"organizer-run:{provider}"
    title = f"{'115' if provider == 'p115' else '夸克'}云下载整理"
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM transfer_jobs WHERE execution_key=? ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if row:
            job_id = int(row["id"])
            conn.execute(
                """UPDATE transfer_jobs SET status='running',stage='organizer_scanning',message='正在扫描已选云下载目录',
                   display_title=?,source_file=?,save_path=?,request_source='cloud_download_organizer',
                   created_at=CURRENT_TIMESTAMP,finished_at=NULL WHERE id=?""",
                (title, source_path, save_path, job_id),
            )
        else:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,source_file,save_path,
                   request_source,execution_key)
                   VALUES('cloud',?,'running','organizer_scanning','正在扫描已选云下载目录',?,?,?,
                   'cloud_download_organizer',?)""",
                (provider, title, source_path, save_path, execution_key),
            )
            job_id = int(cursor.lastrowid)
    return job_id


def _finish_run_job(job_id: int, status: str, message: str) -> None:
    stage = (
        "organizer_scan_failed" if status == "failed"
        else "organizer_scan_stopped" if status == "stopped"
        else "organizer_scan_completed"
    )
    with db() as conn:
        conn.execute(
            "UPDATE transfer_jobs SET status=?,stage=?,message=?,finished_at=CURRENT_TIMESTAMP WHERE id=? AND status!='stopped'",
            (status, stage, message[:500], job_id),
        )


def _update_job(
    job_id: int,
    status: str,
    stage: str,
    message: str,
    *,
    finished: bool = False,
    review_state: str = "",
) -> bool:
    with db() as conn:
        cursor = conn.execute(
            """UPDATE transfer_jobs SET status=?,stage=?,message=?,review_state=?,
               finished_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END
               WHERE id=? AND (status!='stopped' OR ?='stopped')""",
            (status, stage, message[:500], review_state, int(finished), job_id, status),
        )
        return bool(cursor.rowcount)


def _update_job_plan(
    job_id: int,
    plan: OrganizePlan,
    serialized: list[dict[str, Any]],
    fingerprint: str,
    mode: str,
    *,
    source_entries: tuple[RemoteEntry, ...] = (),
) -> None:
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        state = _decode_job_state(row["external_provider_status"] if row else "")
        state.update(
            {
                "fingerprint": fingerprint,
                "mode": mode,
                "source_folder_id": plan.source_folder.file_id,
                "source_folder_name": plan.source_folder.name,
                "source_path": plan.source_path,
                "source_scope_path": plan.source_scope_path,
                "loose_group_key": plan.loose_group_key,
                "category": plan.category,
                "poster_url": plan.target.poster_url,
                "write_started": bool(state.get("write_started")),
                "verified_targets": state.get("verified_targets")
                if isinstance(state.get("verified_targets"), dict)
                else {},
                "write_receipts": state.get("write_receipts")
                if isinstance(state.get("write_receipts"), dict)
                else {},
                "copy_intents": state.get("copy_intents")
                if isinstance(state.get("copy_intents"), list)
                else [],
                "source_inventory": [_serialize_remote_entry(item) for item in source_entries],
            }
        )
        conn.execute(
            """UPDATE transfer_jobs SET tmdb_id=?,media_type=?,display_title=?,season_number=?,
               renamed_file=?,rename_pairs_json=?,save_path=?,external_provider_status=?
               WHERE id=? AND status!='stopped'""",
            (
                plan.target.tmdb_id,
                plan.target.media_type,
                plan.target.title,
                next((item.season_number for item in plan.files if item.season_number is not None), None),
                plan.files[0].replacement if len(plan.files) == 1 else "",
                json.dumps(serialized, ensure_ascii=False, separators=(",", ":")),
                plan.media_path,
                json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                job_id,
            ),
        )


def _ensure_job_active(job_id: int) -> None:
    with db() as conn:
        row = conn.execute(
            """SELECT status,provider,source_file,save_path,execution_key,request_source
               FROM transfer_jobs WHERE id=?""",
            (int(job_id),),
        ).fetchone()
    if row and str(row["status"]) == "stopped":
        raise OrganizerStopped("任务已由用户停止；已完成的原子网盘操作保留，未继续清理源目录")
    settings = get_settings()
    provider = str(row["provider"] or "") if row else ""
    enabled = (
        settings.provider_cloud_download_organizer_enabled(provider)
        if provider in {"p115", "quark"}
        else any(settings.provider_cloud_download_organizer_enabled(value) for value in ("p115", "quark"))
    )
    if not enabled:
        raise OrganizerStopped("对应网盘的云下载整理开关已关闭；已完成的原子网盘操作保留，未继续写入或清理")
    if not row or str(row["request_source"] or "") != "cloud_download_organizer":
        return
    execution_key = str(row["execution_key"] or "")
    if execution_key.startswith("organizer-run:"):
        return
    if not execution_key.startswith("organizer:"):
        return
    current_mode = "move" if settings.cloud_download_organizer_mode == "move" else "copy"
    task_mode = execution_key.rsplit(":", 1)[-1]
    if task_mode in {"copy", "move"} and task_mode != current_mode:
        raise OrganizerStopped("云下载整理模式已变更；原任务未继续写入或清理")
    source_path = normalize_save_root(str(row["source_file"] or ""))
    if provider not in {"p115", "quark"} or "/" not in source_path.rstrip("/"):
        raise OrganizerStopped("整理任务缺少可复核的授权路径，已停止")
    scope_path = normalize_save_root(source_path.rsplit("/", 1)[0])
    selected = {
        normalize_save_root(value)
        for value in settings.provider_cloud_download_organizer_directories(provider)
    }
    if scope_path not in selected:
        raise OrganizerStopped("该云下载子目录已取消授权；未继续写入、清理或入库后处理")
    download_root = normalize_save_root(settings.provider_cloud_download_path(provider))
    library_root = normalize_save_root(settings.provider_save_root(provider))
    try:
        child_name = _direct_child_name(download_root, scope_path)
    except (RuntimeError, ValueError) as exc:
        raise OrganizerStopped("云下载根目录已变更；未继续原任务") from exc
    expected_category = normalize_save_root(f"{library_root.rstrip('/')}/{child_name}")
    save_path = normalize_save_root(str(row["save_path"] or ""))
    if save_path and save_path != expected_category and not save_path.startswith(f"{expected_category.rstrip('/')}/"):
        raise OrganizerStopped("正式媒体库映射已变更；未继续原任务")


def _mark_job_write_started(job_id: int) -> None:
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=? AND status!='stopped'",
            (int(job_id),),
        ).fetchone()
        if not row:
            raise OrganizerStopped("任务已由用户停止，未开始远端写入")
        state = _decode_job_state(row["external_provider_status"])
        state["write_started"] = True
        cursor = conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=? AND status!='stopped'",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )
        if not cursor.rowcount:
            raise OrganizerStopped("任务已由用户停止，未开始远端写入")


def _verified_target_bindings(job_id: int) -> dict[str, dict[str, Any]]:
    with db() as conn:
        row = conn.execute("SELECT external_provider_status FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
    state = _decode_job_state(row["external_provider_status"] if row else "")
    values = state.get("verified_targets")
    return {
        str(key): dict(value)
        for key, value in values.items()
        if isinstance(value, dict)
    } if isinstance(values, dict) else {}


def _write_receipt_bindings(job_id: int) -> dict[str, dict[str, Any]]:
    with db() as conn:
        row = conn.execute("SELECT external_provider_status FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
    state = _decode_job_state(row["external_provider_status"] if row else "")
    values = state.get("write_receipts")
    return {
        str(key): dict(value)
        for key, value in values.items()
        if isinstance(value, dict)
    } if isinstance(values, dict) else {}


def _copy_intent_bindings(job_id: int | None) -> dict[str, dict[str, Any]]:
    if job_id is None:
        return {}
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()
    state = _decode_job_state(row["external_provider_status"] if row else "")
    batches = state.get("copy_intents")
    result: dict[str, dict[str, Any]] = {}
    for batch in batches if isinstance(batches, list) else ():
        if not isinstance(batch, dict) or not isinstance(batch.get("items"), dict):
            continue
        shared = {
            "destination": str(batch.get("destination") or ""),
            "staging_path": str(batch.get("staging_path") or ""),
            "staging_id": str(batch.get("staging_id") or ""),
            "baseline_ids": [str(value) for value in (batch.get("baseline_ids") or ())],
        }
        for source_id, value in batch["items"].items():
            if isinstance(value, dict):
                result[str(source_id)] = {**shared, **value}
    return result


def _record_copy_intents(
    job_id: int,
    destination: str,
    staging_path: str,
    staging_id: str,
    planned: list[PlannedFile],
    baseline_entries: tuple[RemoteEntry, ...],
) -> None:
    """Persist intent before a copy API call so new provider IDs can be reconciled."""
    source_ids = {item.source.provider_file_id for item in planned}
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=? AND status!='stopped'",
            (int(job_id),),
        ).fetchone()
        if not row:
            raise OrganizerStopped("任务已停止，未提交复制请求")
        state = _decode_job_state(row["external_provider_status"])
        previous = state.get("copy_intents")
        batches: list[dict[str, Any]] = []
        for raw in previous if isinstance(previous, list) else ():
            if not isinstance(raw, dict) or not isinstance(raw.get("items"), dict):
                continue
            kept_items = {
                str(key): value
                for key, value in raw["items"].items()
                if str(key) not in source_ids and isinstance(value, dict)
            }
            if kept_items:
                batches.append({**raw, "items": kept_items})
        batches.append(
            {
                "destination": destination,
                "staging_path": staging_path,
                "staging_id": staging_id,
                "baseline_ids": [entry.file_id for entry in baseline_entries],
                "items": {
                    item.source.provider_file_id: {
                        "source_name": item.source.name,
                        "replacement": item.replacement,
                        "size": int(item.source.size or 0),
                        "acknowledged": False,
                    }
                    for item in planned
                },
            }
        )
        state["copy_intents"] = batches
        cursor = conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=? AND status!='stopped'",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )
        if not cursor.rowcount:
            raise OrganizerStopped("任务已停止，未提交复制请求")


def _acknowledge_copy_intents(job_id: int, source_ids: set[str]) -> None:
    """Mark only copy calls that returned successfully to the organizer."""
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=? AND status!='stopped'",
            (int(job_id),),
        ).fetchone()
        if not row:
            raise OrganizerStopped("任务已停止；复制请求可能已提交，但未继续认领结果")
        state = _decode_job_state(row["external_provider_status"])
        raw_batches = state.get("copy_intents")
        batches = [dict(value) for value in raw_batches] if isinstance(raw_batches, list) else []
        acknowledged: set[str] = set()
        for batch in batches:
            raw_items = batch.get("items")
            if not isinstance(raw_items, dict):
                continue
            items = {str(key): dict(value) for key, value in raw_items.items() if isinstance(value, dict)}
            for source_id in source_ids:
                if source_id in items:
                    items[source_id]["acknowledged"] = True
                    acknowledged.add(source_id)
            batch["items"] = items
        if acknowledged != source_ids:
            raise RuntimeError("复制请求返回后缺少对应的写前意图")
        state["copy_intents"] = batches
        cursor = conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=? AND status!='stopped'",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )
        if not cursor.rowcount:
            raise OrganizerStopped("任务已停止；已提交的复制结果未继续处理")


def _record_write_receipts(
    job_id: int,
    destination: str,
    staging_path: str,
    planned: list[PlannedFile],
    received: dict[str, RemoteEntry],
) -> None:
    """Persist copied target IDs before the non-atomic staging-to-library move."""
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=? AND status!='stopped'",
            (int(job_id),),
        ).fetchone()
        if not row:
            raise OrganizerStopped("任务已停止；已复制到暂存区的文件保留，未继续移入媒体库")
        state = _decode_job_state(row["external_provider_status"])
        receipts = state.get("write_receipts")
        if not isinstance(receipts, dict):
            receipts = {}
        for item in planned:
            source_id = item.source.provider_file_id
            entry = received.get(source_id)
            if not entry:
                raise RuntimeError(f"复制回执缺少暂存文件：{item.source.name}")
            receipts[source_id] = {
                "path": destination,
                "staging_path": staging_path,
                "file_id": entry.file_id,
                "name": item.replacement,
                "size": int(item.source.size or 0),
            }
        state["write_receipts"] = receipts
        state["copy_intents"] = _copy_intents_without(
            state.get("copy_intents"),
            {item.source.provider_file_id for item in planned},
        )
        cursor = conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=? AND status!='stopped'",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )
        if not cursor.rowcount:
            raise OrganizerStopped("任务已停止；已复制到暂存区的文件保留")


def _record_verified_targets(
    job_id: int,
    destination: str,
    verified: dict[str, RemoteEntry],
) -> None:
    with db() as conn:
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=? AND status!='stopped'",
            (int(job_id),),
        ).fetchone()
        if not row:
            raise OrganizerStopped("任务已停止；目标已核验，但未继续记录或清理源目录")
        state = _decode_job_state(row["external_provider_status"])
        targets = state.get("verified_targets")
        if not isinstance(targets, dict):
            targets = {}
        receipts = state.get("write_receipts")
        if not isinstance(receipts, dict):
            receipts = {}
        for source_id, entry in verified.items():
            targets[str(source_id)] = {
                "path": destination,
                "file_id": entry.file_id,
                "name": entry.name,
                "size": int(entry.size or 0),
            }
            receipts.pop(str(source_id), None)
        state["verified_targets"] = targets
        state["write_receipts"] = receipts
        state["copy_intents"] = _copy_intents_without(
            state.get("copy_intents"),
            {str(source_id) for source_id in verified},
        )
        conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=? AND status!='stopped'",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )


def _decode_job_state(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _copy_intents_without(value: Any, source_ids: set[str]) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    for raw in value if isinstance(value, list) else ():
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), dict):
            continue
        kept_items = {
            str(key): item
            for key, item in raw["items"].items()
            if str(key) not in source_ids and isinstance(item, dict)
        }
        if kept_items:
            retained.append({**raw, "items": kept_items})
    return retained


def _serialize_remote_entry(entry: RemoteEntry) -> dict[str, Any]:
    return {
        "file_id": entry.file_id,
        "parent_id": entry.parent_id,
        "name": entry.name,
        "size": int(entry.size or 0),
        "is_dir": bool(entry.is_dir),
        "relative_path": entry.relative_path,
    }


def _parse_db_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _mode_label(mode: str) -> str:
    return "移动" if mode == "move" else "复制"


def _counts_message(counts: dict[str, int]) -> str:
    return (
        f"扫描 {counts['scanned']} 个目录；等待稳定 {counts['waiting']}，"
        f"已整理 {counts['organized']}，待核对 {counts['review']}，失败 {counts['failed']}"
    )
