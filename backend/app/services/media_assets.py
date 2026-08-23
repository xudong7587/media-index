from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.database import db


class MediaAssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetInput:
    provider: str
    file_id: str
    account_id: str = ""
    parent_id: str = ""
    name: str = ""
    relative_path: str = ""
    size: int = 0
    sha1: str = ""
    md5: str = ""
    revision: str = ""
    media_type: str = ""
    tmdb_id: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    source_transfer_id: int | None = None
    status: str = "discovered"


def register_asset(asset: AssetInput) -> dict[str, Any]:
    provider = _safe_provider(asset.provider)
    file_id = _safe_text(asset.file_id, "文件 ID", 256)
    account_id = _safe_account(asset.account_id)
    name = _safe_text(asset.name, "文件名", 240)
    relative_path = _safe_relative_path(asset.relative_path, name)
    if int(asset.size) < 0:
        raise MediaAssetError("文件大小无效")
    media_type = str(asset.media_type or "")
    tmdb_id = asset.tmdb_id
    with db() as conn:
        conn.execute(
            """
            INSERT INTO media_assets(provider,account_id,file_id,parent_id,name,relative_path,size,sha1,md5,revision,media_type,tmdb_id,season_number,episode_number,source_transfer_id,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(provider,account_id,file_id) DO UPDATE SET
              parent_id=excluded.parent_id,name=excluded.name,
              relative_path=CASE WHEN excluded.relative_path<>'' THEN excluded.relative_path ELSE media_assets.relative_path END,
              size=excluded.size,
              sha1=CASE WHEN excluded.sha1<>'' THEN excluded.sha1 ELSE media_assets.sha1 END,
              md5=CASE WHEN excluded.md5<>'' THEN excluded.md5 ELSE media_assets.md5 END,
              revision=CASE WHEN excluded.revision<>'' THEN excluded.revision ELSE media_assets.revision END,
              media_type=CASE WHEN excluded.media_type<>'' THEN excluded.media_type ELSE media_assets.media_type END,
              tmdb_id=COALESCE(excluded.tmdb_id,media_assets.tmdb_id),
              season_number=COALESCE(excluded.season_number,media_assets.season_number),
              episode_number=COALESCE(excluded.episode_number,media_assets.episode_number),
              source_transfer_id=COALESCE(excluded.source_transfer_id,media_assets.source_transfer_id),
              status=CASE WHEN media_assets.status='needs_review' THEN media_assets.status ELSE excluded.status END,
              last_seen_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            """,
            (
                provider, account_id, file_id, str(asset.parent_id or "")[:256], name, relative_path, int(asset.size),
                str(asset.sha1 or "")[:80], str(asset.md5 or "")[:80], str(asset.revision or "")[:256],
                media_type, tmdb_id, asset.season_number, asset.episode_number,
                asset.source_transfer_id, _safe_status(asset.status),
            ),
        )
        row = conn.execute("SELECT * FROM media_assets WHERE provider=? AND account_id=? AND file_id=?", (provider, account_id, file_id)).fetchone()
    return dict(row)


def _safe_relative_path(value: str, fallback_name: str) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return fallback_name
    parts = raw.split("/")
    if any(
        not part or part in {".", ".."} or len(part) > 240 or any(char in part for char in "\x00\r\n")
        for part in parts
    ):
        raise MediaAssetError("媒体相对路径无效")
    if parts[-1] != fallback_name:
        raise MediaAssetError("媒体相对路径与文件名不一致")
    return "/".join(parts)


def list_assets(limit: int = 100, *, status: str = "") -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    query = "SELECT * FROM media_assets"
    params: list[Any] = []
    if status.strip():
        query += " WHERE status=?"
        params.append(_safe_status(status))
    query += " ORDER BY last_seen_at DESC,id DESC LIMIT ?"
    params.append(safe_limit)
    with db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_asset(asset_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM media_assets WHERE id=?", (int(asset_id),)).fetchone()
    return dict(row) if row else None


def mark_asset_deleted(asset_id: int) -> dict[str, Any]:
    with db() as conn:
        result = conn.execute("UPDATE media_assets SET status='deleted',updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(asset_id),))
        if result.rowcount != 1:
            raise MediaAssetError("媒体资产不存在")
        row = conn.execute("SELECT * FROM media_assets WHERE id=?", (int(asset_id),)).fetchone()
    return dict(row)


def mark_missing_assets_unavailable(provider: str, *, parent_ids: set[str], seen_file_ids: set[str]) -> int:
    """Invalidate only assets inside directories that were completely rescanned."""
    safe_provider = _safe_provider(provider)
    parents = {str(value).strip() for value in parent_ids if str(value).strip()}
    seen = {str(value).strip() for value in seen_file_ids if str(value).strip()}
    if not parents:
        return 0
    with db() as conn:
        rows = conn.execute("SELECT id,file_id,parent_id,status FROM media_assets WHERE provider=?", (safe_provider,)).fetchall()
        missing_ids = [
            int(row["id"])
            for row in rows
            if str(row["parent_id"] or "") in parents
            and str(row["file_id"] or "") not in seen
            and str(row["status"] or "") != "deleted"
        ]
        conn.executemany(
            "UPDATE media_assets SET status='unavailable',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            ((asset_id,) for asset_id in missing_ids),
        )
    return len(missing_ids)


def _safe_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if provider not in {"p115", "quark"}:
        raise MediaAssetError("不支持的资产网盘")
    return provider


def _safe_status(value: str) -> str:
    status = str(value or "").strip().lower()
    if status not in {"discovered", "ready", "deleted", "needs_review", "unavailable"}:
        raise MediaAssetError("资产状态无效")
    return status


def _safe_text(value: str, label: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit or "\x00" in text or "\r" in text or "\n" in text:
        raise MediaAssetError(f"{label}无效")
    return text


def _safe_account(value: str) -> str:
    text = str(value or "").strip()
    if len(text) > 256 or "\x00" in text or "\r" in text or "\n" in text:
        raise MediaAssetError("账号标识无效")
    return text
