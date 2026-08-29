from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlparse

from app.core.config import get_settings
from app.db.database import db
from app.services.playback import issue_asset_token


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".wmv", ".webm", ".iso"}
EXCLUDED_NAME_TOKENS = {"trailer", "sample", "preview", "花絮", "预告", "广告"}
_STRM_WRITE_LOCKS = tuple(threading.Lock() for _ in range(64))


class StrmReconcileError(RuntimeError):
    pass


@dataclass(frozen=True)
class StrmReconcileResult:
    created: int = 0
    replaced: int = 0
    unchanged: int = 0
    filtered: int = 0
    conflicts: int = 0
    removed: int = 0
    scraped: int = 0
    pending_removal: int = 0


def reconcile_strm(
    *,
    output_root: str | None = None,
    playback_base_url: str | None = None,
    provider: str | None = None,
    source_root_path: str | None = None,
    include_directories: Iterable[str] | None = None,
    allow_removal: bool = False,
    asset_ids: Iterable[int] | None = None,
) -> StrmReconcileResult:
    """Reconcile only MediaIndex-owned STRM entries from ready assets.

    This never scans/deletes arbitrary .strm files.  A path collision between
    two active assets becomes an explicit conflict rather than a guessed
    replacement; replacement is allowed only for the same asset identity.
    """
    settings = get_settings()
    root = _resolve_output_root(output_root if output_root is not None else settings.strm_output_root)
    base_url = _safe_playback_base(playback_base_url if playback_base_url is not None else settings.strm_playback_base_url)
    library_root_id = _safe_root_id(settings.strm_library_root_id)
    if provider not in {None, "p115", "quark"}:
        raise StrmReconcileError("STRM 网盘类型无效")
    source_root = _safe_source_root(source_root_path) if source_root_path is not None else ""
    if source_root and not provider:
        raise StrmReconcileError("按来源目录生成 STRM 时必须指定网盘类型")
    selected_directories = _selected_directories(source_root, include_directories)
    targeted_asset_ids = tuple(dict.fromkeys(int(value) for value in (asset_ids or ()) if int(value) > 0))
    targeted = asset_ids is not None
    if targeted and allow_removal:
        raise StrmReconcileError("定点 STRM 生成不允许执行缺失清理")
    video_extensions = _configured_extensions(settings)
    excluded_tokens = _configured_tokens(settings)
    min_size_bytes = max(0, int(getattr(settings, "strm_min_file_size_mb", 0) or 0)) * 1024 * 1024
    with db() as conn:
        if targeted:
            if not targeted_asset_ids:
                assets = []
            else:
                placeholders = ",".join("?" for _ in targeted_asset_ids)
                clauses = [f"id IN ({placeholders})", "status='ready'", "missing_scan_count=0"]
                params: list[Any] = [*targeted_asset_ids]
                if provider:
                    clauses.append("provider=?")
                    params.append(provider)
                if source_root:
                    clauses.append("inventory_root_path=?")
                    params.append(source_root)
                assets = [dict(row) for row in conn.execute(
                    f"SELECT * FROM media_assets WHERE {' AND '.join(clauses)} ORDER BY id",
                    tuple(params),
                ).fetchall()]
            # Collisions must still be checked against every MediaIndex-owned
            # mapping in this output library, even though only the requested
            # assets are eligible for writes.
            entries = [dict(row) for row in conn.execute(
                "SELECT * FROM strm_entries WHERE library_root_id=?",
                (library_root_id,),
            ).fetchall()]
        elif provider:
            if source_root:
                if selected_directories:
                    selection = _relative_directory_selection_sql("", selected_directories)
                    assets = [dict(row) for row in conn.execute(
                        f"SELECT * FROM media_assets WHERE status='ready' AND missing_scan_count=0 AND provider=? AND inventory_root_path=?{selection[0]} ORDER BY id",
                        (provider, source_root, *selection[1]),
                    ).fetchall()]
                    entry_selection = _relative_directory_selection_sql("a.", selected_directories)
                    entries = [dict(row) for row in conn.execute(
                        f"SELECT e.* FROM strm_entries e JOIN media_assets a ON a.id=e.asset_id WHERE e.library_root_id=? AND a.provider=? AND a.inventory_root_path=?{entry_selection[0]}",
                        (library_root_id, provider, source_root, *entry_selection[1]),
                    ).fetchall()]
                else:
                    assets = [dict(row) for row in conn.execute(
                        "SELECT * FROM media_assets WHERE status='ready' AND missing_scan_count=0 AND provider=? AND inventory_root_path=? ORDER BY id",
                        (provider, source_root),
                    ).fetchall()]
                    entries = [dict(row) for row in conn.execute(
                        "SELECT e.* FROM strm_entries e JOIN media_assets a ON a.id=e.asset_id WHERE e.library_root_id=? AND a.provider=? AND a.inventory_root_path=?",
                        (library_root_id, provider, source_root),
                    ).fetchall()]
            else:
                assets = [dict(row) for row in conn.execute("SELECT * FROM media_assets WHERE status='ready' AND missing_scan_count=0 AND provider=? ORDER BY id", (provider,)).fetchall()]
                entries = [dict(row) for row in conn.execute(
                    "SELECT e.* FROM strm_entries e JOIN media_assets a ON a.id=e.asset_id WHERE e.library_root_id=? AND a.provider=?",
                    (library_root_id, provider),
                ).fetchall()]
        else:
            assets = [dict(row) for row in conn.execute("SELECT * FROM media_assets WHERE status='ready' AND missing_scan_count=0 ORDER BY id").fetchall()]
            entries = [dict(row) for row in conn.execute("SELECT * FROM strm_entries WHERE library_root_id=?", (library_root_id,)).fetchall()]
    by_asset = {int(entry["asset_id"]): entry for entry in entries}
    by_path = {
        str(entry["relative_path"]): entry
        for entry in entries
        if str(entry.get("status") or "") != "removed"
    }
    candidate_paths: dict[int, str] = {}
    active_asset_ids: set[int] = set()
    for asset in assets:
        asset_id = int(asset["id"])
        # A source that was enumerated successfully remains active even when
        # a user-side extension, name, or size filter excludes it from new
        # writes. Filter changes are not proof of a remote deletion.
        active_asset_ids.add(asset_id)
        relative_path = _relative_path(asset, video_extensions=video_extensions, excluded_tokens=excluded_tokens, min_size_bytes=min_size_bytes)
        if relative_path is not None:
            candidate_paths[asset_id] = relative_path

    relocation_count = sum(
        1
        for asset_id, relative_path in candidate_paths.items()
        if (owned := by_asset.get(asset_id))
        and str(owned.get("status") or "") != "removed"
        and _path_identity(str(owned["relative_path"])) != _path_identity(relative_path)
    )
    scoped_ready_entries = sum(1 for entry in entries if str(entry.get("status") or "") != "removed")
    relocation_limit = min(50, max(1, math.floor(scoped_ready_entries * 0.10)))
    if relocation_count > relocation_limit:
        raise StrmReconcileError(
            f"STRM 路径迁移熔断：计划改变 {relocation_count} 条已有路径，超过当前范围 {scoped_ready_entries} 条的安全阈值 {relocation_limit}；本次未写入或删除 STRM"
        )

    created = replaced = unchanged = filtered = conflicts = removed = scraped = 0
    for asset in assets:
        asset_id = int(asset["id"])
        relative_path = candidate_paths.get(asset_id)
        if relative_path is None:
            filtered += 1
            continue
        content = f"{base_url}/api/play/{issue_asset_token(asset)}\n"
        version = _content_version(asset, content)
        owned = by_asset.get(asset_id)
        conflicting = by_path.get(relative_path)
        if conflicting and int(conflicting["asset_id"]) != asset_id:
            _mark_conflict(asset_id, library_root_id, relative_path, "目标 STRM 路径已由另一个资产占用")
            conflicts += 1
            continue
        entry = owned
        target = _target_path(root, relative_path)
        if entry and entry["content_version"] == version and target.is_file() and _read_text(target) == content:
            _mark_entry(asset_id, library_root_id, relative_path, version, "ready", "", verified=True)
            unchanged += 1
            continue
        _atomic_write_text(target, content)
        if entry and str(entry["relative_path"]) != relative_path:
            previous = _target_path(root, str(entry["relative_path"]))
            if previous.is_file():
                # Stop Emby deletion webhooks from treating a MediaIndex path
                # correction as a request to delete the cloud source.
                _mark_entry(asset_id, library_root_id, str(entry["relative_path"]), version, "reconciling", "")
                previous.unlink()
        _mark_entry(asset_id, library_root_id, relative_path, version, "ready", "", written=True, verified=True)
        by_path[relative_path] = {"asset_id": asset_id, "relative_path": relative_path}
        if entry:
            replaced += 1
        else:
            created += 1

    # Destructive cleanup is never part of an incremental reconcile. A caller
    # must explicitly prove that a full provider traversal completed before it
    # can advance a missing mapping toward removal.
    if not allow_removal:
        return StrmReconcileResult(created, replaced, unchanged, filtered, conflicts, removed, scraped, 0)

    missing_entries = [
        entry for entry in entries
        if int(entry["asset_id"]) not in active_asset_ids
        and str(entry.get("status") or "") != "removed"
    ]
    pending_removal = 0
    removal_candidates: list[dict[str, Any]] = []
    for entry in missing_entries:
        if int(entry.get("missing_scan_count") or 0) < 1:
            _mark_pending_removal(entry)
            pending_removal += 1
        else:
            removal_candidates.append(entry)

    # A normal full scan must not erase a large part of a library silently.
    # The floor avoids blocking a small number of legitimate removals; above
    # it, more than ten percent of the current scope is considered anomalous.
    scoped_count = len([entry for entry in entries if str(entry.get("status") or "") != "removed"])
    ratio_limit = max(1, math.floor(scoped_count * 0.10))
    removal_limit = min(50, ratio_limit)
    if len(removal_candidates) > removal_limit:
        raise StrmReconcileError(
            f"STRM 清理熔断：计划删除 {len(removal_candidates)} 条，超过当前扫描范围 {scoped_count} 条的安全阈值 {removal_limit}；本次未删除任何 STRM"
        )

    # Only MediaIndex-owned records absent from two consecutive complete full
    # scans are eligible. The exact stored path is used; globs are forbidden.
    for entry in removal_candidates:
        target = _target_path(root, str(entry["relative_path"]))
        try:
            # Mark the mapping unavailable before unlinking the local STRM.
            # Emby can observe filesystem changes immediately; this ordering
            # keeps a full scan read-only with respect to the cloud provider.
            _mark_entry(int(entry["asset_id"]), library_root_id, str(entry["relative_path"]), str(entry["content_version"]), "removed", "", verified=True)
            if target.is_file():
                target.unlink()
            with db() as conn:
                conn.execute(
                    "UPDATE media_assets SET status='unavailable',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='ready'",
                    (int(entry["asset_id"]),),
                )
            removed += 1
        except OSError as exc:
            _mark_entry(int(entry["asset_id"]), library_root_id, str(entry["relative_path"]), str(entry["content_version"]), "error", "STRM 清理失败")
    return StrmReconcileResult(created, replaced, unchanged, filtered, conflicts, removed, scraped, pending_removal)


def _safe_source_root(value: str | None) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    parts = [part for part in raw.split("/") if part]
    if any(part in {".", ".."} or len(part) > 240 or any(char in part for char in "\x00\r\n") for part in parts):
        raise StrmReconcileError("STRM 来源目录无效")
    return "/" + "/".join(parts)


def _path_identity(value: str) -> str:
    """Normalize separators and Unicode without collapsing real directories."""
    return unicodedata.normalize("NFC", str(value or "").replace("\\", "/"))


def _selected_directories(source_root: str, values: Iterable[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    if not source_root:
        raise StrmReconcileError("选择 STRM 子目录时必须提供来源目录")
    prefix = "/" if source_root == "/" else f"{source_root.rstrip('/')}/"
    selected: list[str] = []
    for value in values:
        candidate = _safe_source_root(str(value or ""))
        if not candidate.startswith(prefix):
            raise StrmReconcileError("STRM 选中的子目录不属于当前来源目录")
        relative = candidate[len(prefix):]
        if not relative or "/" in relative:
            raise StrmReconcileError("STRM 只能选择来源目录下的直接子目录")
        if relative not in selected:
            selected.append(relative)
    return tuple(selected)


def _relative_directory_selection_sql(alias: str, directories: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    return (
        " AND (" + " OR ".join(f"{alias}relative_path LIKE ?" for _ in directories) + ")",
        tuple(f"{directory}/%" for directory in directories),
    )


def list_strm_entries(limit: int = 200) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT e.*,a.provider,a.file_id,a.name AS asset_name,a.status AS asset_status
            FROM strm_entries e JOIN media_assets a ON a.id=e.asset_id
            ORDER BY e.updated_at DESC,e.id DESC LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


def _relative_path(asset: dict[str, Any], *, video_extensions: set[str] = VIDEO_EXTENSIONS, excluded_tokens: set[str] = EXCLUDED_NAME_TOKENS, min_size_bytes: int = 0) -> str | None:
    name = str(asset.get("name") or "").strip()
    suffix = Path(name).suffix.lower()
    lowered = name.casefold()
    if suffix not in video_extensions or any(token in lowered for token in excluded_tokens) or int(asset.get("size") or 0) < min_size_bytes:
        return None
    raw_path = str(asset.get("relative_path") or name).strip().replace("\\", "/").strip("/")
    path = PurePosixPath(raw_path)
    if not raw_path or path.is_absolute() or any(part in {"", ".", ".."} or any(char in part for char in "\r\n\x00") for part in path.parts):
        return None
    if path.name != name:
        return None
    return str(path.with_suffix(".strm"))


def _configured_extensions(settings: Any) -> set[str]:
    try:
        values = json.loads(str(getattr(settings, "strm_video_extensions_json", "") or ""))
    except (TypeError, ValueError):
        values = []
    normalized = {str(value).strip().casefold() for value in values if re.fullmatch(r"\.[a-z0-9]{1,12}", str(value).strip().casefold())}
    return normalized or set(VIDEO_EXTENSIONS)


def _configured_tokens(settings: Any) -> set[str]:
    try:
        values = json.loads(str(getattr(settings, "strm_excluded_name_tokens_json", "") or ""))
    except (TypeError, ValueError):
        values = []
    normalized = {str(value).strip().casefold() for value in values if str(value).strip()}
    return normalized if values else set(EXCLUDED_NAME_TOKENS)


def _resolve_output_root(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise StrmReconcileError("请先在 STRM 设置页配置输出目录")
    if "\x00" in raw:
        raise StrmReconcileError("STRM 输出目录无效")
    candidate = Path(raw).expanduser()
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        root = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise StrmReconcileError(f"STRM 输出目录的挂载父目录不存在：{raw}") from exc
    except PermissionError as exc:
        raise StrmReconcileError(f"STRM 输出目录没有创建或写入权限：{raw}") from exc
    except OSError as exc:
        raise StrmReconcileError(f"STRM 输出目录无法创建：{raw}") from exc
    if not root.is_dir():
        raise StrmReconcileError("STRM 输出目录不可用")
    return root


def _safe_playback_base(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    if base:
        if not re.fullmatch(r"https?://[^/?#\s]+", base):
            raise StrmReconcileError("STRM 播放地址无效")
        return base

    # The normal deployment exposes the same playback route through a
    # dedicated host port (8097 by default).  Reuse Emby's configured host so
    # users only choose that port; no public URL or reverse-proxy URL is
    # embedded in a STRM file.
    settings = get_settings()
    emby_url = str(getattr(settings, "emby_base_url", "") or "").strip()
    parsed = urlparse(emby_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StrmReconcileError("请先在 Emby 连接中填写 Emby 内网地址，以生成 302 播放地址")
    port = int(getattr(settings, "emby_proxy_port", 8097) or 8097)
    if not 1024 <= port <= 65535:
        raise StrmReconcileError("302 播放端口无效")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}:{port}"


def _safe_root_id(value: str) -> str:
    root_id = str(value or "default").strip() or "default"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", root_id):
        raise StrmReconcileError("STRM 媒体库标识无效")
    return root_id


def _target_path(root: Path, relative_path: str) -> Path:
    normalized = str(relative_path or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or path.suffix != ".strm" or any(part in {"", ".", ".."} for part in path.parts):
        raise StrmReconcileError("STRM 路径记录无效")
    target = root.joinpath(*path.parts).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise StrmReconcileError("STRM 路径越界") from exc
    return target


def _atomic_write_text(target: Path, content: str) -> None:
    lock = _STRM_WRITE_LOCKS[hash(str(target)) % len(_STRM_WRITE_LOCKS)]
    with lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{target.name}.",
                suffix=".media-index.tmp",
                dir=target.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _content_version(asset: dict[str, Any], content: str) -> str:
    from hashlib import sha256

    raw = "|".join(str(asset.get(key) or "") for key in ("provider", "account_id", "file_id", "revision", "sha1", "size"))
    return sha256(f"{raw}|{content}".encode("utf-8")).hexdigest()[:32]


def _mark_entry(asset_id: int, root_id: str, relative_path: str, version: str, status: str, error: str, *, written: bool = False, verified: bool = False) -> None:
    with db() as conn:
        # Removed mappings retain audit rows, but may not block a replacement
        # asset from legitimately reusing the same library path.
        conn.execute(
            """DELETE FROM strm_entries
               WHERE library_root_id=? AND relative_path=? AND asset_id<>? AND status='removed'""",
            (root_id, relative_path, asset_id),
        )
        conn.execute(
            """
            INSERT INTO strm_entries(asset_id,library_root_id,relative_path,content_version,status,last_error_safe,last_written_at,last_verified_at)
            VALUES(?,?,?,?,?,?,CASE WHEN ? THEN CURRENT_TIMESTAMP END,CASE WHEN ? THEN CURRENT_TIMESTAMP END)
            ON CONFLICT(asset_id,library_root_id) DO UPDATE SET
              relative_path=excluded.relative_path,content_version=excluded.content_version,status=excluded.status,
              last_error_safe=excluded.last_error_safe,
              last_written_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE strm_entries.last_written_at END,
              last_verified_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE strm_entries.last_verified_at END,
              missing_scan_count=CASE WHEN excluded.status='ready' THEN 0 ELSE strm_entries.missing_scan_count END,
              updated_at=CURRENT_TIMESTAMP
            """,
            (asset_id, root_id, relative_path, version, status, error[:500], written, verified, written, verified),
        )


def _mark_pending_removal(entry: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE strm_entries
               SET status='pending_remove',missing_scan_count=1,last_verified_at=CURRENT_TIMESTAMP,
                   last_error_safe='完整全量扫描首次未发现；等待下一次完整扫描确认',updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (int(entry["id"]),),
        )


def _mark_conflict(asset_id: int, root_id: str, relative_path: str, message: str) -> None:
    with db() as conn:
        conn.execute("UPDATE media_assets SET status='needs_review',updated_at=CURRENT_TIMESTAMP WHERE id=?", (asset_id,))
