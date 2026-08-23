from __future__ import annotations

from dataclasses import dataclass

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.services.media_assets import AssetInput, mark_missing_assets_unavailable, register_asset


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


def scan_p115_inventory(root_path: str, *, max_files: int = 10000, client: P115Client | None = None, mark_missing: bool = True) -> InventoryResult:
    """Recursively index an existing 115 path without mutating the cloud drive."""
    path = _safe_path(root_path)
    limit = max(1, min(int(max_files), 50000))
    p115 = client or P115Client()
    if not p115.configured():
        raise CloudInventoryError("115 连接未配置")
    try:
        root_id = p115.directory_id(path)
    except P115Error as exc:
        raise CloudInventoryError(str(exc)) from exc
    if not root_id or root_id == "0" and path != "/":
        raise CloudInventoryError("115 目标目录不存在；索引不会自动创建目录")
    pending = [(root_id, "")]
    directories = 0
    files = 0
    scanned_parent_ids: set[str] = set()
    seen_file_ids: set[str] = set()
    while pending and files < limit:
        directory_id, relative_dir = pending.pop()
        scanned_parent_ids.add(str(directory_id))
        directories += 1
        try:
            entries = p115.list_directory(directory_id)
        except P115Error as exc:
            raise CloudInventoryError(str(exc)) from exc
        for entry in entries:
            if entry.is_dir:
                pending.append((entry.file_id, _join_relative(relative_dir, entry.name)))
                continue
            register_asset(
                AssetInput(
                    provider="p115",
                    file_id=entry.file_id,
                    parent_id=entry.parent_id,
                    name=entry.name,
                    relative_path=_join_relative(relative_dir, entry.name),
                    size=entry.size,
                    status=_inventory_status(entry.name),
                )
            )
            seen_file_ids.add(str(entry.file_id))
            files += 1
            if files >= limit:
                break
    truncated = bool(pending)
    if not truncated and mark_missing:
        mark_missing_assets_unavailable("p115", parent_ids=scanned_parent_ids, seen_file_ids=seen_file_ids)
    return InventoryResult("p115", path, directories, files, truncated)


def scan_quark_inventory(root_path: str, *, max_files: int = 10000, client: QuarkClient | None = None, mark_missing: bool = True) -> InventoryResult:
    """Recursively index an existing Quark path without receiving or moving files."""
    path = _safe_path(root_path)
    limit = max(1, min(int(max_files), 50000))
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
    scanned_parent_ids: set[str] = set()
    seen_file_ids: set[str] = set()
    while pending and files < limit:
        directory_id, relative_dir = pending.pop()
        scanned_parent_ids.add(str(directory_id))
        directories += 1
        try:
            entries = quark.list_directory(directory_id)
        except QuarkError as exc:
            raise CloudInventoryError(str(exc)) from exc
        for entry in entries:
            if entry.is_dir:
                pending.append((entry.file_id, _join_relative(relative_dir, entry.name)))
                continue
            register_asset(
                AssetInput(provider="quark", file_id=entry.file_id, parent_id=entry.parent_id, name=entry.name, relative_path=_join_relative(relative_dir, entry.name), size=entry.size, status=_inventory_status(entry.name))
            )
            seen_file_ids.add(str(entry.file_id))
            files += 1
            if files >= limit:
                break
    truncated = bool(pending)
    if not truncated and mark_missing:
        mark_missing_assets_unavailable("quark", parent_ids=scanned_parent_ids, seen_file_ids=seen_file_ids)
    return InventoryResult("quark", path, directories, files, truncated)


def _safe_path(value: str) -> str:
    components = [item.strip() for item in str(value or "").replace("\\", "/").split("/") if item.strip()]
    if any(item in {".", ".."} or len(item) > 180 for item in components):
        raise CloudInventoryError("115 索引目录无效")
    return "/" + "/".join(components)


def _join_relative(parent: str, name: str) -> str:
    component = str(name or "").strip().replace("\\", "/")
    if not component or "/" in component or component in {".", ".."} or any(char in component for char in "\x00\r\n"):
        raise CloudInventoryError("网盘目录包含无法安全映射的名称")
    return "/".join(part for part in (parent, component) if part)


def _inventory_status(name: str) -> str:
    from pathlib import Path

    lowered = str(name or "").casefold()
    return "ready" if Path(lowered).suffix in VIDEO_EXTENSIONS and not any(token in lowered for token in EXCLUDED_NAME_TOKENS) else "discovered"
