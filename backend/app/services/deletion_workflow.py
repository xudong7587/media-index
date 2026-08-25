from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
import unicodedata

from app.clients.p115 import P115Client, P115Error
from app.db.database import db
from app.services.media_assets import MediaAssetError, get_asset, mark_asset_deleted
from app.services.playback import invalidate_asset_cache
from app.services.notifications import add_notification


class DeletionWorkflowError(RuntimeError):
    pass


def request_deletion_for_strm(relative_path: str, *, trigger_source: str, trigger_ref: str = "") -> dict[str, Any]:
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
    return request_deletion(asset_ids.pop(), trigger_source=trigger_source, trigger_ref=trigger_ref)


def request_deletions_for_strm_path(relative_path: str, *, trigger_source: str, trigger_ref: str = "") -> list[dict[str, Any]]:
    """Create exact deletion intents for one STRM file or one STRM directory.

    Directory deletion is intentionally prefix-based only after the API layer
    has verified that the absolute Emby path belongs to a configured library.
    Every matched row must still be a ready 115 asset with a stable file ID.
    """
    path = _safe_relative_path_or_directory(relative_path)
    if path.casefold().endswith(".strm"):
        return [request_deletion_for_strm(path, trigger_source=trigger_source, trigger_ref=trigger_ref)]
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
    return [
        request_deletion(asset_id, trigger_source=trigger_source, trigger_ref=trigger_ref)
        for asset_id in sorted(asset_ids)
    ]


def request_deletion(asset_id: int, *, trigger_source: str, trigger_ref: str = "") -> dict[str, Any]:
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
            INSERT INTO deletion_intents(asset_id,trigger_source,trigger_ref,state,references_at_request,message_safe)
            VALUES(?,?,?,'requested',?,?)
            """,
            (int(asset_id), source, str(trigger_ref or "")[:256], references, "已创建回收意图，等待明确确认"),
        )
        row = conn.execute("SELECT * FROM deletion_intents WHERE id=?", (int(cursor.lastrowid),)).fetchone()
    intent = dict(row)
    _create_deletion_log(intent, asset)
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
            SELECT i.*,a.file_id,a.provider,a.status AS asset_status
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
        mark_asset_deleted(int(intent["asset_id"]))
        invalidate_asset_cache(int(intent["asset_id"]))
        with db() as conn:
            conn.execute(
                """
                UPDATE deletion_intents SET state='completed',message_safe='已按精确文件 ID 移入 115 回收站',
                    completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (int(intent_id),),
            )
            conn.execute("UPDATE strm_entries SET status='removed',updated_at=CURRENT_TIMESTAMP WHERE asset_id=?", (int(intent["asset_id"]),))
            row = conn.execute("SELECT * FROM deletion_intents WHERE id=?", (int(intent_id),)).fetchone()
        _update_deletion_log(int(intent_id), "done", "deletion_completed", "115 已确认移入回收站，STRM 映射已标记移除", finished=True)
        add_notification(f"deletion:{intent_id}:completed", "success", "115 删除同步完成", "源文件已按精确 ID 移入 115 回收站。", "strm")
        return dict(row)
    except (P115Error, MediaAssetError, DeletionWorkflowError) as exc:
        with db() as conn:
            conn.execute(
                "UPDATE deletion_intents SET state='requested',message_safe=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (_safe_message(str(exc)), int(intent_id)),
            )
        _update_deletion_log(int(intent_id), "failed", "deletion_failed", _safe_message(str(exc)), finished=True)
        add_notification(f"deletion:{intent_id}:failed", "error", "115 删除同步失败", _safe_message(str(exc)), "strm", deliver=False)
        raise DeletionWorkflowError(_safe_message(str(exc))) from exc


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


def _create_deletion_log(intent: dict[str, Any], asset: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,save_path,source_file,request_source,execution_key)
               VALUES('cloud','deletion','ready','deletion_requested','已匹配 STRM 与 115 精确文件 ID，等待执行',?,?,?,?,?)""",
            (str(asset.get("name") or "115 文件")[:160], str(asset.get("path") or ""), str(asset.get("file_id") or ""), intent["trigger_source"], f"deletion:{intent['id']}"),
        )


def _update_deletion_log(intent_id: int, status: str, stage: str, message: str, *, finished: bool = False) -> None:
    with db() as conn:
        conn.execute(
            f"UPDATE transfer_jobs SET status=?,stage=?,message=?{',finished_at=CURRENT_TIMESTAMP' if finished else ''} WHERE execution_key=?",
            (status, stage, _safe_message(message), f"deletion:{int(intent_id)}"),
        )


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
