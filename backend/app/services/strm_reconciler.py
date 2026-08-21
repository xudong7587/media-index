from __future__ import annotations

import os
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import get_settings
from app.clients.http import open_url
from app.db.database import db
from app.services.playback import issue_asset_token


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".wmv", ".webm", ".iso"}
EXCLUDED_NAME_TOKENS = {"trailer", "sample", "preview", "花絮", "预告", "广告"}


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


def reconcile_strm(*, output_root: str | None = None, playback_base_url: str | None = None, provider: str | None = None) -> StrmReconcileResult:
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
    scrape_enabled = bool(
        provider
        and getattr(settings, f"{provider}_strm_scrape_enabled", False)
    )
    video_extensions = _configured_extensions(settings)
    excluded_tokens = _configured_tokens(settings)
    min_size_bytes = max(0, int(getattr(settings, "strm_min_file_size_mb", 0) or 0)) * 1024 * 1024
    with db() as conn:
        if provider:
            assets = [dict(row) for row in conn.execute("SELECT * FROM media_assets WHERE status='ready' AND provider=? ORDER BY id", (provider,)).fetchall()]
            entries = [dict(row) for row in conn.execute(
                "SELECT e.* FROM strm_entries e JOIN media_assets a ON a.id=e.asset_id WHERE e.library_root_id=? AND a.provider=?",
                (library_root_id, provider),
            ).fetchall()]
        else:
            assets = [dict(row) for row in conn.execute("SELECT * FROM media_assets WHERE status='ready' ORDER BY id").fetchall()]
            entries = [dict(row) for row in conn.execute("SELECT * FROM strm_entries WHERE library_root_id=?", (library_root_id,)).fetchall()]
        media_catalog = [dict(row) for row in conn.execute("SELECT * FROM media ORDER BY updated_at DESC").fetchall()] if scrape_enabled else []
    by_asset = {int(entry["asset_id"]): entry for entry in entries}
    by_path = {str(entry["relative_path"]): entry for entry in entries}
    created = replaced = unchanged = filtered = conflicts = removed = scraped = 0
    active_asset_ids: set[int] = set()
    for asset in assets:
        asset_id = int(asset["id"])
        relative_path = _relative_path(asset, video_extensions=video_extensions, excluded_tokens=excluded_tokens, min_size_bytes=min_size_bytes)
        if relative_path is None:
            filtered += 1
            continue
        active_asset_ids.add(asset_id)
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
            if scrape_enabled and _write_scrape_assets(root, target, asset, media_catalog):
                scraped += 1
            unchanged += 1
            continue
        _atomic_write_text(target, content)
        if entry and str(entry["relative_path"]) != relative_path:
            previous = _target_path(root, str(entry["relative_path"]))
            if previous.is_file():
                previous.unlink()
            _remove_owned_scrape_assets(root, previous)
        _mark_entry(asset_id, library_root_id, relative_path, version, "ready", "", written=True, verified=True)
        if scrape_enabled and _write_scrape_assets(root, target, asset, media_catalog):
            scraped += 1
        by_path[relative_path] = {"asset_id": asset_id, "relative_path": relative_path}
        if entry:
            replaced += 1
        else:
            created += 1

    # Only records that MediaIndex created and whose asset is no longer ready
    # are eligible for removal. The local file is removed only at its exact
    # stored relative path, never through a glob.
    for entry in entries:
        if int(entry["asset_id"]) in active_asset_ids:
            continue
        target = _target_path(root, str(entry["relative_path"]))
        try:
            if target.is_file():
                target.unlink()
            _remove_owned_scrape_assets(root, target)
            _mark_entry(int(entry["asset_id"]), library_root_id, str(entry["relative_path"]), str(entry["content_version"]), "removed", "", verified=True)
            removed += 1
        except OSError as exc:
            _mark_entry(int(entry["asset_id"]), library_root_id, str(entry["relative_path"]), str(entry["content_version"]), "error", "STRM 清理失败")
    return StrmReconcileResult(created, replaced, unchanged, filtered, conflicts, removed, scraped)


def _write_scrape_assets(root: Path, strm_path: Path, asset: dict[str, Any], media_catalog: list[dict[str, Any]]) -> bool:
    metadata = _match_media_metadata(asset, media_catalog)
    if not metadata:
        return False
    tmdb_id = int(metadata["tmdb_id"])
    media_type = str(metadata["media_type"])
    tag = "movie" if media_type == "movie" else "tvshow"
    document = ET.Element(tag)
    for key, value in (
        ("title", metadata.get("title")),
        ("originaltitle", metadata.get("original_title")),
        ("year", metadata.get("year")),
        ("plot", metadata.get("overview")),
        ("tmdbid", tmdb_id),
        ("generator", "MediaIndex"),
    ):
        if value not in {None, ""}:
            ET.SubElement(document, key).text = str(value)
    nfo = ET.tostring(document, encoding="unicode", xml_declaration=False) + "\n"
    _atomic_write_text(strm_path.with_suffix(".nfo"), nfo)
    for field, suffix in (("poster_url", "-poster.jpg"), ("backdrop_url", "-fanart.jpg")):
        url = str(metadata.get(field) or "").strip()
        if url:
            _download_tmdb_image(url, strm_path.with_name(f"{strm_path.stem}{suffix}"), root)
    return True


def _match_media_metadata(asset: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    tmdb_id = int(asset.get("tmdb_id") or 0)
    media_type = str(asset.get("media_type") or "")
    if tmdb_id and media_type in {"movie", "tv"}:
        return next((item for item in catalog if int(item.get("tmdb_id") or 0) == tmdb_id and item.get("media_type") == media_type), None)
    filename = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", Path(str(asset.get("name") or "")).stem.casefold())
    if not filename:
        return None
    matched = []
    for item in catalog:
        titles = {
            re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(item.get(key) or "").casefold())
            for key in ("title", "original_title")
        }
        titles.discard("")
        if not any(len(title) >= 3 and title in filename for title in titles):
            continue
        year = str(item.get("year") or "").strip()
        if year and year not in filename:
            continue
        matched.append(item)
    return matched[0] if len(matched) == 1 else None


def _remove_owned_scrape_assets(root: Path, strm_path: Path) -> None:
    nfo = strm_path.with_suffix(".nfo")
    if not nfo.is_file() or "<generator>MediaIndex</generator>" not in _read_text(nfo):
        return
    for target in (
        nfo,
        strm_path.with_name(f"{strm_path.stem}-poster.jpg"),
        strm_path.with_name(f"{strm_path.stem}-fanart.jpg"),
    ):
        try:
            resolved = target.resolve()
            resolved.relative_to(root)
            if resolved.is_file():
                resolved.unlink()
        except (OSError, ValueError):
            continue


def _download_tmdb_image(url: str, target: Path, root: Path) -> None:
    if not re.fullmatch(r"https://image\.tmdb\.org/t/p/[A-Za-z0-9_./-]+", url):
        return
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "MediaIndex/0.6"}, method="GET")
        with open_url(request, timeout=20) as response:
            payload = response.read(10_000_001)
        if not payload or len(payload) > 10_000_000:
            return
        target = target.resolve()
        target.relative_to(root)
        _atomic_write_bytes(target, payload)
    except Exception:
        return


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    temporary = target.with_name(f".{target.name}.media-index.tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


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
        raise StrmReconcileError("请先在网盘工作台设置 STRM 输出目录")
    if "\x00" in raw:
        raise StrmReconcileError("STRM 输出目录无效")
    root = Path(raw).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise StrmReconcileError("STRM 输出目录不可用")
    return root


def _safe_playback_base(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    if not re.fullmatch(r"https?://[^/?#\s]+", base):
        raise StrmReconcileError("请先设置 STRM 播放网关根地址，例如 http://媒体服务器地址:8000")
    return base


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
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.media-index.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
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
        conn.execute(
            """
            INSERT INTO strm_entries(asset_id,library_root_id,relative_path,content_version,status,last_error_safe,last_written_at,last_verified_at)
            VALUES(?,?,?,?,?,?,CASE WHEN ? THEN CURRENT_TIMESTAMP END,CASE WHEN ? THEN CURRENT_TIMESTAMP END)
            ON CONFLICT(asset_id,library_root_id) DO UPDATE SET
              relative_path=excluded.relative_path,content_version=excluded.content_version,status=excluded.status,
              last_error_safe=excluded.last_error_safe,
              last_written_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE strm_entries.last_written_at END,
              last_verified_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE strm_entries.last_verified_at END,
              updated_at=CURRENT_TIMESTAMP
            """,
            (asset_id, root_id, relative_path, version, status, error[:500], written, verified, written, verified),
        )


def _mark_conflict(asset_id: int, root_id: str, relative_path: str, message: str) -> None:
    with db() as conn:
        conn.execute("UPDATE media_assets SET status='needs_review',updated_at=CURRENT_TIMESTAMP WHERE id=?", (asset_id,))
