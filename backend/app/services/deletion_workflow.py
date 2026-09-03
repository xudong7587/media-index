from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from typing import Any
import unicodedata

from app.clients.p115 import P115Client, P115Error
from app.core.config import get_settings
from app.db.database import db
from app.services.media_assets import MediaAssetError, get_asset, mark_asset_deleted
from app.services.playback import invalidate_asset_cache
from app.services.notifications import add_notification


class DeletionWorkflowError(RuntimeError):
    pass


_SAFE_FOLDER_RESIDUAL_EXTENSIONS = {
    ".ass", ".bmp", ".gif", ".idx", ".jpeg", ".jpg", ".nfo", ".png",
    ".srt", ".ssa", ".sub", ".sup", ".torrent", ".txt", ".url", ".vtt",
    ".webp", ".xml",
}
_SAFE_FOLDER_RESIDUAL_NAMES = {".ds_store", "thumbs.db"}
_MAX_FOLDER_CLEANUP_ENTRIES = 5000
_MAX_FOLDER_CLEANUP_DEPTH = 12


@dataclass(frozen=True)
class _FolderCleanupCandidate:
    folder_id: str
    parent_id: str
    folder_name: str
    target_file_id: str
    snapshot: tuple[tuple[str, str, str, int, bool], ...]


def request_deletion_for_strm(
    relative_path: str,
    *,
    trigger_source: str,
    trigger_ref: str = "",
    log_group: str = "",
    log_label: str = "",
) -> dict[str, Any]:
    path = _safe_relative_path(relative_path)
    with db() as conn:
        entries = conn.execute(
            """
            SELECT DISTINCT e.relative_path,e.asset_id,a.provider,a.file_id
            FROM strm_entries e JOIN media_assets a ON a.id=e.asset_id
            WHERE e.relative_path=? COLLATE NOCASE
              AND e.status IN ('ready','pending_remove') AND a.status='ready'
            ORDER BY e.asset_id
            """,
            (path,),
        ).fetchall()
        if not entries:
            rows = conn.execute(
                """SELECT DISTINCT e.relative_path,e.asset_id,a.provider,a.file_id
                   FROM strm_entries e JOIN media_assets a ON a.id=e.asset_id
                   WHERE e.status IN ('ready','pending_remove') AND a.status='ready' ORDER BY e.asset_id"""
            ).fetchall()
            canonical_path = _canonical_relative_path(path)
            entries = [entry for entry in rows if _canonical_relative_path(str(entry["relative_path"])) == canonical_path]
    if not entries:
        raise DeletionWorkflowError("未找到精确的 MediaIndex STRM 映射；不会按名称猜测删除网盘文件")
    p115_entries = [entry for entry in entries if entry["provider"] == "p115" and str(entry["file_id"] or "").strip()]
    file_ids = {str(entry["file_id"]).strip() for entry in p115_entries}
    asset_ids = {int(entry["asset_id"]) for entry in p115_entries}
    if len(entries) != len(p115_entries) or len(file_ids) != 1 or len(asset_ids) != 1:
        raise DeletionWorkflowError("STRM 路径未唯一映射到一个 115 文件 ID；不会执行网盘删除")
    return request_deletion(
        asset_ids.pop(),
        trigger_source=trigger_source,
        trigger_ref=trigger_ref,
        log_group=log_group,
        log_label=log_label,
    )


def request_deletions_for_strm_path(
    relative_path: str,
    *,
    trigger_source: str,
    trigger_ref: str = "",
    log_group: str = "",
    log_label: str = "",
) -> list[dict[str, Any]]:
    """Create exact deletion intents for one STRM file or one STRM directory.

    Directory deletion is intentionally prefix-based only after the API layer
    has verified that the absolute Emby path belongs to a configured library.
    Every matched row must still be a ready 115 asset with a stable file ID.
    """
    path = _safe_relative_path_or_directory(relative_path)
    if path.casefold().endswith(".strm"):
        return [request_deletion_for_strm(
            path,
            trigger_source=trigger_source,
            trigger_ref=trigger_ref,
            log_group=log_group,
            log_label=log_label,
        )]
    escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with db() as conn:
        entries = conn.execute(
            """
            SELECT DISTINCT e.asset_id,e.library_root_id,a.provider,a.file_id
            FROM strm_entries e JOIN media_assets a ON a.id=e.asset_id
            WHERE e.relative_path LIKE ? ESCAPE '\\' AND e.status='ready' AND a.status='ready'
            ORDER BY e.asset_id LIMIT 5001
            """,
            (f"{escaped}/%",),
        ).fetchall()
    if not entries:
        raise DeletionWorkflowError("该 Emby 目录下没有可删除的 MediaIndex STRM 精确映射")
    if len(entries) > 5000:
        raise DeletionWorkflowError("该目录包含超过 5000 个 STRM 映射，已拒绝批量删除")
    roots = {str(entry["library_root_id"] or "") for entry in entries}
    p115_entries = [entry for entry in entries if entry["provider"] == "p115" and str(entry["file_id"] or "").strip()]
    file_ids = {str(entry["file_id"]).strip() for entry in p115_entries}
    asset_ids = {int(entry["asset_id"]) for entry in p115_entries}
    if len(roots) != 1 or len(entries) != len(p115_entries) or len(file_ids) != len(entries) or len(asset_ids) != len(entries):
        raise DeletionWorkflowError("Emby 目录未唯一映射到同一个 STRM 库中的 115 文件；不会执行网盘删除")
    intents = [
        request_deletion(
            asset_id,
            trigger_source=trigger_source,
            trigger_ref=trigger_ref,
            log_group=log_group,
            log_label=log_label,
        )
        for asset_id in sorted(asset_ids)
    ]
    if trigger_source == "emby_webhook" and trigger_ref:
        _describe_deletion_batch_log(
            log_group or trigger_ref,
            path,
            len(intents),
            log_label=log_label,
            grouped=bool(log_group),
        )
    return intents


def request_deletion(
    asset_id: int,
    *,
    trigger_source: str,
    trigger_ref: str = "",
    log_group: str = "",
    log_label: str = "",
) -> dict[str, Any]:
    asset = get_asset(asset_id)
    if not asset or asset.get("status") != "ready":
        raise DeletionWorkflowError("资产不存在或当前不可删除")
    if asset.get("provider") != "p115":
        raise DeletionWorkflowError("目前仅支持将 115 资产移入回收站")
    source = _safe_trigger(trigger_source)
    with db() as conn:
        existing = conn.execute(
            """
            SELECT * FROM deletion_intents WHERE asset_id=? AND state IN ('requested','confirmed','executing')
            ORDER BY id DESC LIMIT 1
            """,
            (int(asset_id),),
        ).fetchone()
        if existing:
            return dict(existing)
        references = int(conn.execute("SELECT COUNT(*) FROM strm_entries WHERE asset_id=? AND status='ready'", (int(asset_id),)).fetchone()[0])
        cursor = conn.execute(
            """
            INSERT INTO deletion_intents(asset_id,trigger_source,trigger_ref,log_group,state,references_at_request,message_safe)
            VALUES(?,?,?,?,'requested',?,?)
            """,
            (
                int(asset_id),
                source,
                str(trigger_ref or "")[:256],
                str(log_group or "")[:128],
                references,
                "已创建回收意图，等待明确确认",
            ),
        )
        row = conn.execute("SELECT * FROM deletion_intents WHERE id=?", (int(cursor.lastrowid),)).fetchone()
    intent = dict(row)
    _create_deletion_log(intent, asset, log_label=log_label)
    if source != "emby_webhook":
        add_notification(f"deletion:{intent['id']}:requested", "info", "115 删除同步已接收", f"{asset.get('name') or '115 文件'}：已建立精确文件 ID 回收意图。", "strm", deliver=False)
    return intent


def list_deletion_intents(limit: int = 100) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT i.*,a.name AS asset_name,a.provider,a.file_id,a.status AS asset_status
            FROM deletion_intents i JOIN media_assets a ON a.id=i.asset_id
            ORDER BY i.requested_at DESC,i.id DESC LIMIT ?
            """,
            (max(1, min(int(limit), 300)),),
        ).fetchall()
    return [dict(row) for row in rows]


def confirm_deletion(intent_id: int, *, p115_client: P115Client | None = None) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            """
            SELECT i.*,a.file_id,a.parent_id,a.name,a.relative_path,a.inventory_root_path,a.size,
                   a.provider,a.status AS asset_status
            FROM deletion_intents i JOIN media_assets a ON a.id=i.asset_id WHERE i.id=?
            """,
            (int(intent_id),),
        ).fetchone()
        if not row:
            raise DeletionWorkflowError("删除意图不存在")
        intent = dict(row)
        if intent["state"] == "completed":
            return intent
        if intent["state"] != "requested" or intent["provider"] != "p115" or intent["asset_status"] != "ready":
            raise DeletionWorkflowError("删除意图状态已变化，未执行网盘操作")
        changed = conn.execute(
            "UPDATE deletion_intents SET state='executing',confirmed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='requested'",
            (int(intent_id),),
        )
        if changed.rowcount != 1:
            raise DeletionWorkflowError("删除意图正在由其他操作处理")
    _update_deletion_log(int(intent_id), "running", "deletion_trashing", f"正在按 115 文件 ID {intent['file_id']} 移入回收站")
    try:
        p115 = p115_client or P115Client()
        if not p115.configured():
            raise DeletionWorkflowError("115 连接未配置，保留删除意图供稍后确认")
        folder_candidate, folder_receipt = _prepare_emby_folder_cleanup(p115, intent)
        p115.trash_file(str(intent["file_id"]))
        mark_asset_deleted(int(intent["asset_id"]))
        invalidate_asset_cache(int(intent["asset_id"]))
        folder_receipt = _finish_emby_folder_cleanup(p115, folder_candidate, folder_receipt)
        completion_message = "已按精确文件 ID 移入 115 回收站"
        if folder_receipt.get("state") == "removed":
            completion_message += "；所在媒体目录已确认无其他媒体并一并移入回收站"
        elif folder_receipt.get("state") not in {"not_requested", "kept_root"}:
            completion_message += "；所在目录未满足安全清理条件，已保留"
        with db() as conn:
            conn.execute(
                """
                UPDATE deletion_intents SET state='completed',message_safe=?,trash_receipt_json=?,
                    completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (
                    _safe_message(completion_message),
                    json.dumps(folder_receipt, ensure_ascii=False, separators=(",", ":")),
                    int(intent_id),
                ),
            )
            conn.execute("UPDATE strm_entries SET status='removed',updated_at=CURRENT_TIMESTAMP WHERE asset_id=?", (int(intent["asset_id"]),))
            row = conn.execute("SELECT * FROM deletion_intents WHERE id=?", (int(intent_id),)).fetchone()
        log_message = "115 已确认移入回收站，STRM 映射已标记移除"
        if folder_receipt.get("state") == "removed":
            log_message += "；无其他媒体的源目录已一并清理"
        _update_deletion_log(int(intent_id), "done", "deletion_completed", log_message, finished=True)
        if intent["trigger_source"] != "emby_webhook":
            add_notification(f"deletion:{intent_id}:completed", "success", "115 删除同步完成", "源文件已按精确 ID 移入 115 回收站。", "strm")
        return dict(row)
    except (P115Error, MediaAssetError, DeletionWorkflowError) as exc:
        with db() as conn:
            conn.execute(
                "UPDATE deletion_intents SET state='requested',message_safe=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (_safe_message(str(exc)), int(intent_id)),
            )
        _update_deletion_log(int(intent_id), "failed", "deletion_failed", _safe_message(str(exc)), finished=True)
        if intent["trigger_source"] != "emby_webhook":
            add_notification(f"deletion:{intent_id}:failed", "error", "115 删除同步失败", _safe_message(str(exc)), "strm", deliver=False)
        raise DeletionWorkflowError(_safe_message(str(exc))) from exc


def _prepare_emby_folder_cleanup(
    p115: P115Client,
    intent: dict[str, Any],
) -> tuple[_FolderCleanupCandidate | None, dict[str, Any]]:
    """Preflight one optional folder cleanup without weakening exact-file deletion.

    The folder is eligible only when its absolute path still resolves to the
    asset's recorded parent ID and every other file is an allowlisted sidecar.
    Unknown files, nested media, incomplete listings, roots, and large trees
    all keep the directory intact.
    """
    if intent.get("trigger_source") != "emby_webhook":
        return None, _folder_cleanup_receipt("not_requested")
    directory_id = getattr(p115, "directory_id", None)
    list_complete = getattr(p115, "list_directory_complete", None)
    if not callable(directory_id) or not callable(list_complete):
        return None, _folder_cleanup_receipt("kept_unverified", "115 客户端不支持完整目录复核")
    try:
        root_path = _safe_cloud_path(str(intent.get("inventory_root_path") or ""))
        relative_path = _safe_asset_relative_path(str(intent.get("relative_path") or ""))
        relative_parent = PurePosixPath(relative_path).parent
        if str(relative_parent) in {"", "."}:
            return None, _folder_cleanup_receipt("kept_root", "文件位于索引根目录，禁止清理根目录")
        folder_path = _join_cloud_path(root_path, str(relative_parent))
        parent_path = _join_cloud_path(root_path, str(relative_parent.parent))
        configured_scopes = {
            _safe_cloud_path(value)
            for value in get_settings().provider_strm_included_directories("p115")
        }
        if folder_path in configured_scopes:
            return None, _folder_cleanup_receipt("kept_root", "文件位于已配置的 STRM 分类根目录，禁止清理该目录")
        folder_id = str(directory_id(folder_path) or "").strip()
        recorded_parent_id = str(intent.get("parent_id") or "").strip()
        root_id = str(directory_id(root_path) or "").strip()
        parent_id = str(directory_id(parent_path) or "").strip()
        if (
            not folder_id
            or folder_id == "0"
            or folder_id == root_id
            or folder_id != recorded_parent_id
            or not parent_id
        ):
            return None, _folder_cleanup_receipt("kept_identity", "源目录路径与已记录目录 ID 不一致")
        folder_name = relative_parent.name
        parent_entries = tuple(list_complete(parent_id))
        matches = [
            entry for entry in parent_entries
            if bool(entry.is_dir)
            and str(entry.file_id) == folder_id
            and str(entry.name) == folder_name
            and str(entry.parent_id) == parent_id
        ]
        if len(matches) != 1:
            return None, _folder_cleanup_receipt("kept_identity", "源目录未在父目录中唯一确认")
        snapshot = _read_complete_folder_tree(p115, folder_id)
        target_id = str(intent.get("file_id") or "").strip()
        target_matches = [
            entry for entry in snapshot
            if entry[0] == target_id
            and entry[1] == folder_id
            and entry[2] == str(intent.get("name") or "")
            and entry[3] == int(intent.get("size") or 0)
            and not entry[4]
        ]
        if len(target_matches) != 1:
            return None, _folder_cleanup_receipt("kept_identity", "待删除文件未在源目录中唯一确认")
        blockers = [entry for entry in snapshot if entry[0] != target_id and not entry[4] and not _safe_folder_residual(entry[2])]
        if blockers:
            return None, _folder_cleanup_receipt("kept_other_files", "源目录仍有其他媒体或未知文件")
        return (
            _FolderCleanupCandidate(folder_id, parent_id, folder_name, target_id, snapshot),
            _folder_cleanup_receipt("eligible"),
        )
    except (P115Error, DeletionWorkflowError, TypeError, ValueError) as exc:
        return None, _folder_cleanup_receipt("kept_unverified", _safe_message(str(exc)))


def _finish_emby_folder_cleanup(
    p115: P115Client,
    candidate: _FolderCleanupCandidate | None,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    if candidate is None:
        return receipt
    try:
        current = _read_complete_folder_tree(p115, candidate.folder_id)
        if any(entry[0] == candidate.target_file_id for entry in current):
            return _folder_cleanup_receipt("kept_unverified", "待删除文件仍在源目录清单中")
        expected = {entry[0]: entry for entry in candidate.snapshot if entry[0] != candidate.target_file_id}
        if any(expected.get(entry[0]) != entry for entry in current):
            return _folder_cleanup_receipt("kept_changed", "源目录在删除期间出现新增或身份变化")
        if any(not entry[4] and not _safe_folder_residual(entry[2]) for entry in current):
            return _folder_cleanup_receipt("kept_other_files", "源目录仍有其他媒体或未知文件")
        for residual in sorted(
            (entry for entry in current if not entry[4]),
            key=lambda entry: (entry[2].casefold(), entry[0]),
        ):
            latest = _read_complete_folder_tree(p115, candidate.folder_id)
            if any(expected.get(entry[0]) != entry for entry in latest):
                return _folder_cleanup_receipt("kept_changed", "残留清理前出现新增或身份变化")
            if any(not entry[4] and not _safe_folder_residual(entry[2]) for entry in latest):
                return _folder_cleanup_receipt("kept_other_files", "残留清理前仍有其他媒体或未知文件")
            matched = [entry for entry in latest if entry == residual]
            if not matched:
                continue
            residual_error = ""
            try:
                p115.trash_file(residual[0])
            except P115Error as exc:
                residual_error = _safe_message(str(exc))
            deadline = time.monotonic() + 3
            while True:
                latest = _read_complete_folder_tree(p115, candidate.folder_id)
                if all(entry[0] != residual[0] for entry in latest):
                    break
                if any(expected.get(entry[0]) != entry for entry in latest):
                    return _folder_cleanup_receipt("kept_changed", "残留清理期间出现新增或身份变化")
                if time.monotonic() >= deadline:
                    detail = f"残留文件回收结果未确认：{residual_error}" if residual_error else "残留文件回收操作未在时限内确认"
                    return _folder_cleanup_receipt("kept_unverified", detail)
                time.sleep(0.25)
        parent_entries = tuple(p115.list_directory_complete(candidate.parent_id))
        matches = [
            entry for entry in parent_entries
            if bool(entry.is_dir)
            and str(entry.file_id) == candidate.folder_id
            and str(entry.name) == candidate.folder_name
            and str(entry.parent_id) == candidate.parent_id
        ]
        if len(matches) != 1:
            return _folder_cleanup_receipt("kept_identity", "源目录身份在删除期间发生变化")
        # The provider does not offer compare-and-delete.  Repeat the complete
        # recursive snapshot after validating the parent and immediately
        # before recycling the exact folder ID, minimizing the only remaining
        # provider-side race window.
        final_current = _read_complete_folder_tree(p115, candidate.folder_id)
        if any(expected.get(entry[0]) != entry for entry in final_current):
            return _folder_cleanup_receipt("kept_changed", "目录回收前出现新增或身份变化")
        if any(not entry[4] for entry in final_current):
            return _folder_cleanup_receipt("kept_unverified", "目录回收前仍有未确认清理的文件")
        trash_error = ""
        try:
            p115.trash_file(candidate.folder_id)
        except P115Error as exc:
            trash_error = _safe_message(str(exc))
        deadline = time.monotonic() + 3
        while True:
            parent_entries = tuple(p115.list_directory_complete(candidate.parent_id))
            if all(str(entry.file_id) != candidate.folder_id for entry in parent_entries):
                return _folder_cleanup_receipt("removed", "源目录已移入 115 回收站")
            if time.monotonic() >= deadline:
                detail = f"目录回收结果未确认：{trash_error}" if trash_error else "目录回收操作未在时限内确认"
                return _folder_cleanup_receipt("kept_unverified", detail)
            time.sleep(0.25)
    except (P115Error, DeletionWorkflowError, TypeError, ValueError) as exc:
        return _folder_cleanup_receipt("kept_unverified", _safe_message(str(exc)))


def _read_complete_folder_tree(p115: P115Client, folder_id: str) -> tuple[tuple[str, str, str, int, bool], ...]:
    pending = [(str(folder_id), 0)]
    visited: set[str] = set()
    entries_by_id: dict[str, tuple[str, str, str, int, bool]] = {}
    while pending:
        directory_id, depth = pending.pop()
        if directory_id in visited:
            raise DeletionWorkflowError("源目录清单包含重复目录 ID")
        if depth > _MAX_FOLDER_CLEANUP_DEPTH:
            raise DeletionWorkflowError("源目录层级超过安全清理上限")
        visited.add(directory_id)
        for entry in p115.list_directory_complete(directory_id):
            identity = (
                str(entry.file_id),
                str(entry.parent_id),
                str(entry.name),
                int(entry.size or 0),
                bool(entry.is_dir),
            )
            if not identity[0] or identity[0] in entries_by_id or identity[1] != directory_id:
                raise DeletionWorkflowError("源目录清单身份不完整或包含重复文件 ID")
            entries_by_id[identity[0]] = identity
            if len(entries_by_id) > _MAX_FOLDER_CLEANUP_ENTRIES:
                raise DeletionWorkflowError("源目录条目超过安全清理上限")
            if identity[4]:
                pending.append((identity[0], depth + 1))
    return tuple(sorted(entries_by_id.values(), key=lambda entry: entry[0]))


def _safe_folder_residual(name: str) -> bool:
    normalized = str(name or "").strip().casefold()
    return normalized in _SAFE_FOLDER_RESIDUAL_NAMES or PurePosixPath(normalized).suffix in _SAFE_FOLDER_RESIDUAL_EXTENSIONS


def _safe_cloud_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw.startswith("/"):
        raise DeletionWorkflowError("资产来源根目录不是绝对网盘路径")
    parts = [part for part in raw.split("/") if part]
    if any(part in {".", ".."} or any(char in part for char in "\x00\r\n") for part in parts):
        raise DeletionWorkflowError("资产来源根目录无效")
    return "/" + "/".join(parts)


def _safe_asset_relative_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    parts = raw.split("/") if raw else []
    if not parts or any(part in {"", ".", ".."} or any(char in part for char in "\x00\r\n") for part in parts):
        raise DeletionWorkflowError("资产相对路径无效")
    return "/".join(parts)


def _join_cloud_path(root: str, relative: str) -> str:
    suffix = str(relative or "").replace("\\", "/").strip("/")
    if suffix in {"", "."}:
        return root
    return f"{root.rstrip('/')}/{suffix}"


def _folder_cleanup_receipt(state: str, message: str = "") -> dict[str, Any]:
    return {"folder_cleanup": True, "state": str(state), "message": _safe_message(message) if message else ""}


def log_deletion_webhook_failure(message: str, *, trigger_ref: str = "") -> None:
    safe = _safe_message(message)
    execution_key = f"deletion-webhook:{str(trigger_ref or '')[:120]}"
    with db() as conn:
        existing = conn.execute("SELECT id FROM transfer_jobs WHERE execution_key=? ORDER BY id DESC LIMIT 1", (execution_key,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE transfer_jobs SET status='failed',stage='deletion_failed',message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (safe, int(existing["id"])),
            )
        else:
            conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,request_source,execution_key,finished_at)
                   VALUES('cloud','deletion','failed','deletion_failed',?,'Emby → 115 删除同步','emby_webhook',?,CURRENT_TIMESTAMP)""",
                (safe, execution_key),
            )
    add_notification(f"deletion-webhook:{trigger_ref or safe}", "error", "Emby 删除同步未执行", safe, "strm", deliver=False)


def deletion_webhook_event_handled(trigger_ref: str) -> bool:
    """Return whether the exact Emby deletion event already reached a terminal decision.

    Emby may deliver the same notification more than once.  A rejected event
    must not turn into an endless retry loop, and a completed event must never
    create a second cloud trash request.
    """
    safe_ref = str(trigger_ref or "").strip()[:256]
    if not safe_ref:
        return False
    with db() as conn:
        intent = conn.execute(
            """SELECT 1 FROM deletion_intents
               WHERE trigger_source='emby_webhook' AND trigger_ref=? LIMIT 1""",
            (safe_ref,),
        ).fetchone()
        if intent:
            return True
        failure = conn.execute(
            "SELECT 1 FROM transfer_jobs WHERE execution_key=? LIMIT 1",
            (f"deletion-webhook:{safe_ref[:120]}",),
        ).fetchone()
    return bool(failure)


def _create_deletion_log(intent: dict[str, Any], asset: dict[str, Any], *, log_label: str = "") -> None:
    execution_key = _deletion_log_key(intent)
    with db() as conn:
        if intent["trigger_source"] == "emby_webhook" and str(intent.get("log_group") or "").strip():
            existing = conn.execute(
                "SELECT id FROM transfer_jobs WHERE execution_key=? ORDER BY id DESC LIMIT 1",
                (execution_key,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE transfer_jobs
                       SET status='ready',stage='deletion_requested',message='已匹配新的 STRM 与 115 精确文件 ID，等待执行',
                           display_title=?,finished_at=NULL
                       WHERE id=?""",
                    (f"{str(log_label or '媒体目录')[:120]} · Emby → 115 删除同步", int(existing["id"])),
                )
                return
        conn.execute(
            """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,save_path,source_file,request_source,execution_key)
               VALUES('cloud','deletion','ready','deletion_requested','已匹配 STRM 与 115 精确文件 ID，等待执行',?,?,?,?,?)
               ON CONFLICT DO NOTHING""",
            (
                (
                    f"{str(log_label or '媒体目录')[:120]} · Emby → 115 删除同步"
                    if intent["trigger_source"] == "emby_webhook"
                    else str(asset.get("name") or "115 文件")[:160]
                ),
                str(asset.get("path") or ""),
                str(asset.get("file_id") or ""),
                intent["trigger_source"],
                execution_key,
            ),
        )


def _update_deletion_log(intent_id: int, status: str, stage: str, message: str, *, finished: bool = False) -> None:
    with db() as conn:
        intent = conn.execute(
            "SELECT trigger_source,trigger_ref,log_group FROM deletion_intents WHERE id=?",
            (int(intent_id),),
        ).fetchone()
        if not intent:
            return
        intent_data = {
            "id": int(intent_id),
            "trigger_source": intent["trigger_source"],
            "trigger_ref": intent["trigger_ref"],
            "log_group": intent["log_group"],
        }
        execution_key = _deletion_log_key(intent_data)
        if intent["trigger_source"] == "emby_webhook" and str(intent["trigger_ref"] or "").strip():
            group = str(intent["log_group"] or "").strip()
            counts = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN state='completed' THEN 1 ELSE 0 END) AS completed
                   FROM deletion_intents
                   WHERE trigger_source='emby_webhook'
                     AND ((?<>'' AND log_group=? AND date(requested_at)=date('now')) OR (?='' AND trigger_ref=?))""",
                (group, group, group, intent["trigger_ref"]),
            ).fetchone()
            total = int(counts["total"] or 0)
            completed = int(counts["completed"] or 0)
            if status == "done" and completed < total:
                status = "running"
                stage = "deletion_trashing"
                message = f"正在按精确文件 ID 移入 115 回收站（{completed}/{total}）"
                finished = False
            elif status == "done":
                message = f"115 已确认 {completed} 个源文件移入回收站，STRM 映射已标记移除"
                receipt_rows = conn.execute(
                    """SELECT trash_receipt_json FROM deletion_intents
                       WHERE trigger_source='emby_webhook'
                         AND ((?<>'' AND log_group=? AND date(requested_at)=date('now')) OR (?='' AND trigger_ref=?))""",
                    (group, group, group, intent["trigger_ref"]),
                ).fetchall()
                removed_folders = sum(
                    1
                    for receipt_row in receipt_rows
                    if _folder_cleanup_state(receipt_row["trash_receipt_json"]) == "removed"
                )
                if removed_folders:
                    message += f"；并清理 {removed_folders} 个无其他媒体的源目录"
        conn.execute(
            f"UPDATE transfer_jobs SET status=?,stage=?,message=?{',finished_at=CURRENT_TIMESTAMP' if finished else ''} WHERE execution_key=?",
            (status, stage, _safe_message(message), execution_key),
        )


def _describe_deletion_batch_log(
    log_group: str,
    relative_path: str,
    count: int,
    *,
    log_label: str = "",
    grouped: bool = False,
) -> None:
    reference = str(log_group or "").strip()[:256]
    if not reference:
        return
    label = str(log_label or "").strip() or PurePosixPath(relative_path).name or "媒体目录"
    with db() as conn:
        conn.execute(
            """UPDATE transfer_jobs
               SET display_title=?,save_path=?,source_file=?,message=?
               WHERE execution_key=?""",
            (
                f"{label} · Emby → 115 删除同步"[:160],
                str(relative_path)[:500],
                f"{int(count)} 个精确 STRM 映射",
                f"已匹配 {int(count)} 个 STRM 与 115 精确文件 ID，等待执行",
                _deletion_group_key(reference) if grouped else _deletion_batch_key(reference),
            ),
        )


def _deletion_log_key(intent: dict[str, Any]) -> str:
    log_group = str(intent.get("log_group") or "").strip()
    if intent.get("trigger_source") == "emby_webhook" and log_group:
        return _deletion_group_key(log_group)
    trigger_ref = str(intent.get("trigger_ref") or "").strip()
    if intent.get("trigger_source") == "emby_webhook" and trigger_ref:
        return _deletion_batch_key(trigger_ref)
    return f"deletion:{int(intent['id'])}"


def _deletion_batch_key(trigger_ref: str) -> str:
    digest = hashlib.sha256(str(trigger_ref).encode("utf-8")).hexdigest()[:32]
    return f"deletion-batch:{digest}"


def _deletion_group_key(log_group: str) -> str:
    digest = hashlib.sha256(str(log_group).encode("utf-8")).hexdigest()[:24]
    return f"deletion-group:{digest}:{date.today().isoformat()}"


def _folder_cleanup_state(value: Any) -> str:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    return str(payload.get("state") or "") if isinstance(payload, dict) else ""


def _safe_relative_path(value: str) -> str:
    raw = _safe_relative_path_or_directory(value)
    if not raw.casefold().endswith(".strm"):
        raise DeletionWorkflowError("STRM 路径无效")
    return raw


def _safe_relative_path_or_directory(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    path = PurePosixPath(raw)
    if (
        not raw
        or len(raw) > 500
        or path.is_absolute()
        or any(part in {"", ".", ".."} or any(char in part for char in "\r\n\x00") for part in path.parts)
    ):
        raise DeletionWorkflowError("STRM 路径无效")
    return str(path)


def _canonical_relative_path(value: str) -> str:
    """Canonicalize a full relative STRM path without falling back to its name."""
    return unicodedata.normalize("NFC", _safe_relative_path_or_directory(value)).casefold()


def _safe_trigger(value: str) -> str:
    trigger = str(value or "").strip().lower()
    if trigger not in {"emby_webhook", "manual"}:
        raise DeletionWorkflowError("删除触发来源无效")
    return trigger


def _safe_message(value: str) -> str:
    return str(value or "删除操作失败").replace("\r", " ").replace("\n", " ").strip()[:500]
