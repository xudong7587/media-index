from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.services.media_assets import AssetInput, mark_missing_assets_unavailable, register_asset, register_assets


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".wmv", ".webm", ".iso"}
EXCLUDED_NAME_TOKENS = {"trailer", "sample", "preview", "花絮", "预告", "广告"}


class CloudInventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class InventoryResult:
    provider: str
    root_path: str
    directories_scanned: int
    files_indexed: int
    truncated: bool
    eligible_files_indexed: int = 0


@dataclass(frozen=True)
class InventoryProgress:
    """A directory traversal update intended for a throttled task log."""

    root_path: str
    relative_dir: str
    directories_scanned: int
    files_indexed: int


def scan_p115_inventory(
    root_path: str,
    *,
    max_files: int | None = None,
    client: P115Client | None = None,
    mark_missing: bool = True,
    include_directories: Iterable[str] | None = None,
    on_progress: Callable[[InventoryProgress], None] | None = None,
) -> InventoryResult:
    """Recursively index an existing 115 path without mutating the cloud drive."""
    path = _safe_path(root_path)
    limit = _scan_limit(max_files)
    included = _included_directories(path, include_directories)
    p115 = client or P115Client()
    if not p115.configured():
        raise CloudInventoryError("115 连接未配置")
    try:
        root_id = p115.directory_id(path)
    except P115Error as exc:
        raise CloudInventoryError(str(exc)) from exc
    if not root_id or root_id == "0" and path != "/":
        raise CloudInventoryError("115 目标目录不存在；索引不会自动创建目录")
    # Cookie bulk listings are substantially cheaper than recursive directory
    # reads.  For selected children we first read this one root page, then run
    # the same bulk listing for every selected child ID.  Unchecked siblings
    # are therefore never included in the remote read.
    if _supports_fast_p115_inventory(p115):
        try:
            inventory_roots = _fast_p115_inventory_roots(p115, root_id, included)
        except P115Error as exc:
            raise CloudInventoryError(str(exc)) from exc
        return _scan_p115_fast_inventory(
            p115,
            root_id=root_id,
            root_path=path,
            inventory_roots=inventory_roots,
            max_files=limit,
            mark_missing=mark_missing,
            include_directories=included,
            on_progress=on_progress,
        )
    pending = [(root_id, "")]
    directories = 0
    files = 0
    eligible_files = 0
    scanned_parent_ids: set[str] = set()
    seen_file_ids: set[str] = set()
    while pending and (limit is None or files < limit):
        directory_id, relative_dir = pending.pop()
        scanned_parent_ids.add(str(directory_id))
        directories += 1
        _report_progress(on_progress, path, relative_dir, directories, files)
        try:
            entries = p115.list_directory(directory_id)
        except P115Error as exc:
            raise CloudInventoryError(str(exc)) from exc
        for entry in entries:
            if entry.is_dir:
                if not relative_dir and included and entry.name not in included:
                    continue
                pending.append((entry.file_id, _join_relative(relative_dir, entry.name)))
                continue
            if not relative_dir and included:
                continue
            status = _inventory_status(entry.name)
            register_asset(
                AssetInput(
                    provider="p115",
                    file_id=entry.file_id,
                    parent_id=entry.parent_id,
                    name=entry.name,
                    relative_path=_join_relative(relative_dir, entry.name),
                    inventory_root_path=path,
                    size=entry.size,
                    status=status,
                )
            )
            if status == "ready":
                eligible_files += 1
            seen_file_ids.add(str(entry.file_id))
            files += 1
            if limit is not None and files >= limit:
                break
    truncated = bool(pending)
    if not truncated and mark_missing and seen_file_ids:
        mark_missing_assets_unavailable(
            "p115",
            parent_ids=scanned_parent_ids,
            seen_file_ids=seen_file_ids,
            inventory_root_path=path,
            relative_path_prefixes=included,
        )
    return InventoryResult("p115", path, directories, files, truncated, eligible_files)


def _supports_fast_p115_inventory(client: object) -> bool:
    supported = getattr(client, "supports_fast_inventory", None)
    iterator = getattr(client, "iter_fast_inventory_files", None)
    return callable(supported) and bool(supported()) and callable(iterator)


def _fast_p115_inventory_roots(
    client: object,
    root_id: str,
    included_directories: set[str],
) -> tuple[tuple[str, str], ...]:
    if not included_directories:
        return ((str(root_id), ""),)
    list_directory = getattr(client, "list_directory", None)
    if not callable(list_directory):
        raise CloudInventoryError("115 高速清单无法读取来源目录的已选子目录")
    entries = list_directory(root_id)
    children = {
        entry.name: entry
        for entry in entries
        if entry.is_dir and entry.name in included_directories
    }
    # A missing selected child intentionally produces no remote child read.
    # The scoped missing-asset reconciliation below marks only that historical
    # child unavailable; nothing is written to, moved in, or exported from 115.
    return tuple(
        (str(children[name].file_id), name)
        for name in sorted(included_directories)
        if name in children
    )


def _scan_p115_fast_inventory(
    client: object,
    *,
    root_id: str,
    root_path: str,
    inventory_roots: tuple[tuple[str, str], ...],
    max_files: int | None,
    mark_missing: bool,
    include_directories: set[str],
    on_progress: Callable[[InventoryProgress], None] | None,
) -> InventoryResult:
    """Index a full 115 source from bulk Cookie lists without cloud writes."""
    iterator = getattr(client, "iter_fast_inventory_files")
    directories = {str(root_id)}
    seen_file_ids: set[str] = set()
    files = 0
    eligible_files = 0
    truncated = False
    pending_assets: list[AssetInput] = []
    _report_progress(on_progress, root_path, "", 1, 0)
    try:
        for inventory_root_id, relative_prefix in inventory_roots:
            if max_files is not None and files >= max_files:
                truncated = True
                break
            remaining = None if max_files is None else max_files - files
            entries = iterator(inventory_root_id, max_files=remaining)
            for entry in entries:
                relative_path = _fast_relative_path(entry)
                if relative_prefix:
                    relative_path = f"{relative_prefix}/{relative_path}"
                status = _inventory_status(entry.name)
                pending_assets.append(
                    AssetInput(
                        provider="p115",
                        file_id=entry.file_id,
                        parent_id=entry.parent_id,
                        name=entry.name,
                        relative_path=relative_path,
                        inventory_root_path=root_path,
                        size=entry.size,
                        status=status,
                    )
                )
                if status == "ready":
                    eligible_files += 1
                directories.add(str(entry.parent_id))
                seen_file_ids.add(str(entry.file_id))
                files += 1
                if len(pending_assets) >= 500:
                    register_assets(tuple(pending_assets))
                    pending_assets.clear()
                # The bulk endpoint does not expose a folder-walk sequence.
                # The displayed path is therefore the folder currently being
                # indexed, not a claim that 115 is recursively visiting it.
                if files % 500 == 0:
                    _report_fast_progress(on_progress, root_path, relative_path, len(directories), files)
                if max_files is not None and files >= max_files:
                    truncated = True
                    break
        if pending_assets:
            register_assets(tuple(pending_assets))
    except P115Error as exc:
        raise CloudInventoryError(str(exc)) from exc
    if not truncated and mark_missing and seen_file_ids:
        mark_missing_assets_unavailable(
            "p115",
            parent_ids=directories,
            seen_file_ids=seen_file_ids,
            inventory_root_path=root_path,
            relative_path_prefixes=include_directories,
        )
    return InventoryResult("p115", root_path, len(directories), files, truncated, eligible_files)


def scan_quark_inventory(
    root_path: str,
    *,
    max_files: int | None = None,
    client: QuarkClient | None = None,
    mark_missing: bool = True,
    include_directories: Iterable[str] | None = None,
    on_progress: Callable[[InventoryProgress], None] | None = None,
) -> InventoryResult:
    """Recursively index an existing Quark path without receiving or moving files."""
    path = _safe_path(root_path)
    limit = _scan_limit(max_files)
    included = _included_directories(path, include_directories)
    quark = client or QuarkClient()
    if not quark.configured():
        raise CloudInventoryError("夸克连接未配置")
    try:
        root_id = quark.directory_id(path)
    except QuarkError as exc:
        raise CloudInventoryError(str(exc)) from exc
    if not root_id:
        raise CloudInventoryError("夸克目标目录不存在；索引不会自动创建目录")
    pending = [(root_id, "")]
    directories = files = 0
    eligible_files = 0
    scanned_parent_ids: set[str] = set()
    seen_file_ids: set[str] = set()
    while pending and (limit is None or files < limit):
        directory_id, relative_dir = pending.pop()
        scanned_parent_ids.add(str(directory_id))
        directories += 1
        _report_progress(on_progress, path, relative_dir, directories, files)
        try:
            entries = quark.list_directory(directory_id)
        except QuarkError as exc:
            raise CloudInventoryError(str(exc)) from exc
        for entry in entries:
            if entry.is_dir:
                if not relative_dir and included and entry.name not in included:
                    continue
                pending.append((entry.file_id, _join_relative(relative_dir, entry.name)))
                continue
            if not relative_dir and included:
                continue
            status = _inventory_status(entry.name)
            register_asset(
                AssetInput(provider="quark", file_id=entry.file_id, parent_id=entry.parent_id, name=entry.name, relative_path=_join_relative(relative_dir, entry.name), inventory_root_path=path, size=entry.size, status=status)
            )
            if status == "ready":
                eligible_files += 1
            seen_file_ids.add(str(entry.file_id))
            files += 1
            if limit is not None and files >= limit:
                break
    truncated = bool(pending)
    if not truncated and mark_missing and seen_file_ids:
        mark_missing_assets_unavailable(
            "quark",
            parent_ids=scanned_parent_ids,
            seen_file_ids=seen_file_ids,
            inventory_root_path=path,
            relative_path_prefixes=included,
        )
    return InventoryResult("quark", path, directories, files, truncated, eligible_files)


def _safe_path(value: str) -> str:
    components = [item.strip() for item in str(value or "").replace("\\", "/").split("/") if item.strip()]
    if any(item in {".", ".."} or len(item) > 180 for item in components):
        raise CloudInventoryError("115 索引目录无效")
    return "/" + "/".join(components)


def _scan_limit(value: int | None) -> int | None:
    """Keep optional diagnostic limits, but never impose a production default."""
    if value is None:
        return None
    return max(1, min(int(value), 50000))


def _included_directories(root_path: str, values: Iterable[str] | None) -> set[str]:
    """Return validated direct-child names, not arbitrary nested paths."""
    selected: set[str] = set()
    for value in values or ():
        normalized = _safe_path(str(value or ""))
        root_prefix = root_path.rstrip("/")
        expected_prefix = "/" if root_prefix == "" else f"{root_prefix}/"
        if not normalized.startswith(expected_prefix):
            raise CloudInventoryError("STRM 选中的子目录不属于当前来源目录")
        relative = normalized[len(expected_prefix):]
        if "/" in relative or not relative:
            raise CloudInventoryError("STRM 只能选择来源目录下的直接子目录")
        selected.add(relative)
    return selected


def _report_progress(
    callback: Callable[[InventoryProgress], None] | None,
    root_path: str,
    relative_dir: str,
    directories_scanned: int,
    files_indexed: int,
) -> None:
    # Task progress is stored in SQLite. First and every 25th directory keeps
    # the visible log current without a write for every single directory.
    if callback is None or (directories_scanned != 1 and directories_scanned % 25 != 0):
        return
    callback(InventoryProgress(root_path, relative_dir, directories_scanned, files_indexed))


def _report_fast_progress(
    callback: Callable[[InventoryProgress], None] | None,
    root_path: str,
    relative_path: str,
    directories_scanned: int,
    files_indexed: int,
) -> None:
    if callback is None:
        return
    relative_dir = relative_path.rsplit("/", 1)[0] if "/" in relative_path else ""
    callback(InventoryProgress(root_path, relative_dir, directories_scanned, files_indexed))


def _fast_relative_path(entry: P115File) -> str:
    raw = str(entry.path or "").replace("\\", "/").strip("/")
    if not raw:
        raw = str(entry.name or "")
    parts = raw.split("/")
    if (
        not parts
        or parts[-1] != str(entry.name or "")
        or any(not part or part in {".", ".."} or any(char in part for char in "\x00\r\n") for part in parts)
    ):
        raise CloudInventoryError("115 高速清单返回了无法安全映射的文件路径")
    return "/".join(parts)


def _join_relative(parent: str, name: str) -> str:
    component = str(name or "").strip().replace("\\", "/")
    if not component or "/" in component or component in {".", ".."} or any(char in component for char in "\x00\r\n"):
        raise CloudInventoryError("网盘目录包含无法安全映射的名称")
    return "/".join(part for part in (parent, component) if part)


def _inventory_status(name: str) -> str:
    from pathlib import Path

    lowered = str(name or "").casefold()
    return "ready" if Path(lowered).suffix in VIDEO_EXTENSIONS and not any(token in lowered for token in EXCLUDED_NAME_TOKENS) else "discovered"
