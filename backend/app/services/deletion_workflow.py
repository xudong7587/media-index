from __future__ import annotations

from typing import Any

from app.clients.p115 import P115Client, P115Error
from app.db.database import db
from app.services.media_assets import MediaAssetError, get_asset, mark_asset_deleted
from app.services.playback import invalidate_asset_cache


class DeletionWorkflowError(RuntimeError):
    pass


def request_deletion_for_strm(relative_path: str, *, trigger_source: str, trigger_ref: str = "") -> dict[str, Any]:
    path = _safe_relative_path(relative_path)
    with db() as conn:
        entry = conn.execute(
            "SELECT asset_id FROM strm_entries WHERE relative_path=? AND status='ready' ORDER BY id DESC LIMIT 1", (path,)
        ).fetchone()
    if not entry:
        raise DeletionWorkflowError("未找到精确的 MediaIndex STRM 映射；不会按名称猜测删除网盘文件")
    return request_deletion(int(entry["asset_id"]), trigger_source=trigger_source, trigger_ref=trigger_ref)


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
    return dict(row)


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
        return dict(row)
    except (P115Error, MediaAssetError, DeletionWorkflowError) as exc:
        with db() as conn:
            conn.execute(
                "UPDATE deletion_intents SET state='requested',message_safe=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (_safe_message(str(exc)), int(intent_id)),
            )
        raise DeletionWorkflowError(_safe_message(str(exc))) from exc


def _safe_relative_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    if not path or len(path) > 500 or "/" in path or not path.endswith(".strm") or any(char in path for char in "\r\n\x00"):
        raise DeletionWorkflowError("STRM 路径无效")
    return path


def _safe_trigger(value: str) -> str:
    trigger = str(value or "").strip().lower()
    if trigger not in {"emby_webhook", "manual"}:
        raise DeletionWorkflowError("删除触发来源无效")
    return trigger


def _safe_message(value: str) -> str:
    return str(value or "删除操作失败").replace("\r", " ").replace("\n", " ").strip()[:500]
