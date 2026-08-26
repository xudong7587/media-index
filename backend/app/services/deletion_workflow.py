from __future__ import annotations

import hashlib
from datetime import date
from pathlib import PurePosixPath
import re
from typing import Any
import unicodedata

from app.clients.p115 import P115Client, P115Error
from app.core.config import get_settings
from app.db.database import db
from app.services.media_assets import MediaAssetError, get_asset, mark_asset_deleted
from app.services.playback import invalidate_asset_cache
from app.services.notifications import add_notification
from app.services.strm_reconciler import projected_strm_relative_path


class DeletionWorkflowError(RuntimeError):
    pass


def request_deletion_for_strm(
    relative_path: str,
    *,
    trigger_source: str,
    trigger_ref: str = "",
    log_group: str = "",
    log_label: str = "",
) -> dict[str, Any]:
    path = _safe_relative_path(relative_path)
    entries = _exact_strm_entries(path)
    if not entries and trigger_source == "emby_webhook":
        _recover_exact_strm_entry(path)
        entries = _exact_strm_entries(path)
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


def _exact_strm_entries(path: str) -> list[Any]:
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
    return list(entries)


def _recover_exact_strm_entry(path: str) -> None:
    """Repair a missing mapping only from the unique current STRM path projection."""
    canonical_path = _canonical_relative_path(path)
    with db() as conn:
        assets = [dict(row) for row in conn.execute(
            """SELECT * FROM media_assets
               WHERE status='ready' AND missing_scan_count=0
               ORDER BY id"""
        ).fetchall()]
    matches = []
    for asset in assets:
        projected = projected_strm_relative_path(asset)
        if projected and _canonical_relative_path(projected) == canonical_path:
            matches.append(asset)
            if len(matches) > 1:
                return
    if len(matches) != 1 or matches[0].get("provider") != "p115" or not str(matches[0].get("file_id") or "").strip():
        return
    root_id = str(get_settings().strm_library_root_id or "default").strip() or "default"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", root_id):
        return
    with db() as conn:
        conn.execute(
            """INSERT INTO strm_entries(
                   asset_id,library_root_id,relative_path,content_version,status,
                   last_error_safe,missing_scan_count
               ) VALUES(?,?,?,'','pending_remove',?,1)
               ON CONFLICT DO NOTHING""",
            (
                int(matches[0]["id"]),
                root_id,
                path,
                "Emby 删除联动按唯一资产完整路径恢复精确 STRM 映射",
            ),
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
            SELECT i.*,a.file_id,a.parent_id,a.relative_path AS asset_relative_path,
                   a.account_id,a.provider,a.status AS asset_status
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
        p115.trash_file(str(intent["file_id"]))
        directory_id = _empty_parent_directory_id(intent, p115) if intent["trigger_source"] == "emby_webhook" else ""
        if directory_id:
            try:
                p115.trash_directory(directory_id)
            except P115Error:
                directory_id = ""
        completed_message = (
            "已按精确文件和目录 ID 将源文件及空置独占媒体目录移入 115 回收站"
            if directory_id
            else "已按精确文件 ID 移入 115 回收站"
        )
        log_message = (
            "115 已确认源文件及空置独占媒体目录移入回收站，STRM 映射已标记移除"
            if directory_id
            else "115 已确认移入回收站，STRM 映射已标记移除"
        )
        notification_message = (
            "源文件及其空置的独占目录已按精确 ID 移入 115 回收站。"
            if directory_id
            else "源文件已按精确 ID 移入 115 回收站。"
        )
        mark_asset_deleted(int(intent["asset_id"]))
        invalidate_asset_cache(int(intent["asset_id"]))
        with db() as conn:
            conn.execute(
                """
                UPDATE deletion_intents SET state='completed',message_safe=?,
                    completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (completed_message, int(intent_id)),
            )
            conn.execute("UPDATE strm_entries SET status='removed',updated_at=CURRENT_TIMESTAMP WHERE asset_id=?", (int(intent["asset_id"]),))
            row = conn.execute("SELECT * FROM deletion_intents WHERE id=?", (int(intent_id),)).fetchone()
        _update_deletion_log(int(intent_id), "done", "deletion_completed", log_message, finished=True)
        if intent["trigger_source"] != "emby_webhook":
            add_notification(f"deletion:{intent_id}:completed", "success", "115 删除同步完成", notification_message, "strm")
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


def _empty_parent_directory_id(intent: dict[str, Any], p115: P115Client) -> str:
    """Return the parent ID only after the source file was trashed and no sibling remains."""
    parent_id = str(intent.get("parent_id") or "").strip()
    raw_path = str(intent.get("asset_relative_path") or "").strip().replace("\\", "/").strip("/")
    relative_path = PurePosixPath(raw_path)
    if (
        parent_id in {"", "0"}
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", parent_id)
        or not raw_path
        or relative_path.is_absolute()
        or len(relative_path.parts) < 2
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        return ""
    with db() as conn:
        sibling = conn.execute(
            """SELECT 1 FROM media_assets
               WHERE provider='p115' AND account_id=? AND parent_id=? AND id<>? AND status<>'deleted'
               LIMIT 1""",
            (str(intent.get("account_id") or ""), parent_id, int(intent["asset_id"])),
        ).fetchone()
    if sibling:
        return ""
    try:
        entries = p115.list_directory(parent_id)
    except P115Error:
        return ""
    target_id = str(intent.get("file_id") or "").strip()
    # 115 listings can briefly retain the just-trashed target. It is the only
    # tolerated entry; any other file or subdirectory keeps the parent intact.
    if any(entry.is_dir or str(entry.file_id) != target_id for entry in entries):
        return ""
    return parent_id


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
                          SUM(CASE WHEN state='completed' THEN 1 ELSE 0 END) AS completed,
                          MAX(CASE WHEN state='completed' AND message_safe LIKE '%空置独占媒体目录%' THEN 1 ELSE 0 END) AS directory_completed
                   FROM deletion_intents
                   WHERE trigger_source='emby_webhook'
                     AND ((?<>'' AND log_group=? AND date(requested_at)=date('now')) OR (?='' AND trigger_ref=?))""",
                (group, group, group, intent["trigger_ref"]),
            ).fetchone()
            total = int(counts["total"] or 0)
            completed = int(counts["completed"] or 0)
            directory_completed = bool(counts["directory_completed"])
            if status == "done" and completed < total:
                status = "running"
                stage = "deletion_trashing"
                message = f"正在按精确文件 ID 移入 115 回收站（{completed}/{total}）"
                finished = False
            elif status == "done":
                source_label = "个源项移入回收站（含空目录清理）" if directory_completed else "个源文件移入回收站"
                message = f"115 已确认 {completed} {source_label}，STRM 映射已标记移除"
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
