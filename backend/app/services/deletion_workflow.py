from __future__ import annotations

import hashlib
from datetime import date
import json
from pathlib import PurePosixPath
import re
from typing import Any
import unicodedata

from app.clients.p115 import P115Client, P115Error
from app.core.config import get_settings
from app.db.database import db
from app.services.media_assets import get_asset
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
    delete_directory: bool = False,
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
    asset_id = asset_ids.pop()
    directory_path = _parent_directory(path) if delete_directory else ""
    if directory_path and not _strm_directory_is_exclusive(path, asset_id):
        directory_path = ""
    return request_deletion(
        asset_id,
        trigger_source=trigger_source,
        trigger_ref=trigger_ref,
        log_group=log_group,
        log_label=log_label,
        directory_relative_path=directory_path,
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
    delete_directory: bool = False,
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
            delete_directory=delete_directory,
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
    source = _safe_trigger(trigger_source)
    expected_directory = path if source == "emby_webhook" else ""
    asset_placeholders = ",".join("?" for _ in asset_ids)
    with db() as conn:
        active = conn.execute(
            f"""SELECT * FROM deletion_intents
                WHERE asset_id IN ({asset_placeholders}) AND state IN ('requested','confirmed','executing')""",
            sorted(asset_ids),
        ).fetchall()
    if any(
        str(intent["trigger_source"] or "") != source
        or str(intent["trigger_ref"] or "") != str(trigger_ref or "")[:256]
        or _directory_scope_path(dict(intent)) != expected_directory
        for intent in active
    ):
        raise DeletionWorkflowError("目录内资产已有不同来源或删除范围的待处理意图；本次未创建批量删除")
    intents = [
        request_deletion(
            asset_id,
            trigger_source=trigger_source,
            trigger_ref=trigger_ref,
            log_group=log_group,
            log_label=log_label,
            directory_relative_path=path,
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
    directory_relative_path: str = "",
) -> dict[str, Any]:
    asset = get_asset(asset_id)
    if not asset or asset.get("status") != "ready":
        raise DeletionWorkflowError("资产不存在或当前不可删除")
    if asset.get("provider") != "p115":
        raise DeletionWorkflowError("目前仅支持将 115 资产移入回收站")
    source = _safe_trigger(trigger_source)
    directory_path = (
        _safe_relative_path_or_directory(directory_relative_path)
        if source == "emby_webhook" and str(directory_relative_path or "").strip()
        else ""
    )
    receipt = _deletion_scope_receipt(directory_path)
    with db() as conn:
        existing = conn.execute(
            """
            SELECT * FROM deletion_intents WHERE asset_id=? AND state IN ('requested','confirmed','executing')
            ORDER BY id DESC LIMIT 1
            """,
            (int(asset_id),),
        ).fetchone()
        if existing:
            existing_intent = dict(existing)
            if (
                str(existing_intent.get("trigger_source") or "") != source
                or str(existing_intent.get("trigger_ref") or "") != str(trigger_ref or "")[:256]
                or _directory_scope_path(existing_intent) != directory_path
            ):
                raise DeletionWorkflowError("资产已有不同来源或删除范围的待处理意图；本次不会扩大网盘删除范围")
            return existing_intent
        references = int(conn.execute("SELECT COUNT(*) FROM strm_entries WHERE asset_id=? AND status='ready'", (int(asset_id),)).fetchone()[0])
        cursor = conn.execute(
            """
            INSERT INTO deletion_intents(
                asset_id,trigger_source,trigger_ref,log_group,state,references_at_request,trash_receipt_json,message_safe
            ) VALUES(?,?,?,?,'requested',?,?,?)
            """,
            (
                int(asset_id),
                source,
                str(trigger_ref or "")[:256],
                str(log_group or "")[:128],
                references,
                receipt,
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
            SELECT i.*,a.file_id,a.parent_id,a.name AS asset_name,a.size AS asset_size,
                   a.relative_path AS asset_relative_path,a.inventory_root_path,
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
    directory_path = _directory_scope_path(intent)
    operation_intents = _directory_operation_intents(intent, directory_path) if directory_path else [intent]
    operation_ids = [int(item["id"]) for item in operation_intents]
    placeholders = ",".join("?" for _ in operation_ids)
    with db() as conn:
        changed = conn.execute(
            f"""UPDATE deletion_intents
                SET state='executing',confirmed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                WHERE id IN ({placeholders}) AND state='requested'""",
            operation_ids,
        )
        if changed.rowcount != len(operation_ids):
            raise DeletionWorkflowError("删除意图正在由其他操作处理")
    running_message = (
        "正在按 Emby 目录删除范围解析对应的 115 精确目录 ID"
        if directory_path
        else f"正在按 115 文件 ID {intent['file_id']} 移入回收站"
    )
    _update_deletion_log(int(intent_id), "running", "deletion_trashing", running_message)
    try:
        p115 = p115_client or P115Client()
        if not p115.configured():
            raise DeletionWorkflowError("115 连接未配置，保留删除意图供稍后确认")
        if directory_path:
            directory_id, affected_asset_ids = _resolve_directory_target(operation_intents, directory_path, p115)
            p115.trash_directory(directory_id)
            completed_message = "已按 Emby 目录删除范围将对应 115 媒体目录移入回收站"
            log_message = "115 已确认对应媒体目录移入回收站，STRM 映射已标记移除"
        else:
            p115.trash_file(str(intent["file_id"]))
            affected_asset_ids = [int(intent["asset_id"])]
            completed_message = "已按精确文件 ID 移入 115 回收站"
            log_message = "115 已确认移入回收站，STRM 映射已标记移除"
        asset_placeholders = ",".join("?" for _ in affected_asset_ids)
        with db() as conn:
            conn.execute(
                f"""UPDATE media_assets SET status='deleted',updated_at=CURRENT_TIMESTAMP
                    WHERE id IN ({asset_placeholders})""",
                affected_asset_ids,
            )
            conn.execute(
                f"""UPDATE strm_entries SET status='removed',updated_at=CURRENT_TIMESTAMP
                    WHERE asset_id IN ({asset_placeholders})""",
                affected_asset_ids,
            )
            conn.execute(
                f"""UPDATE deletion_intents SET state='completed',message_safe=?,
                    completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})""",
                (completed_message, *operation_ids),
            )
            row = conn.execute("SELECT * FROM deletion_intents WHERE id=?", (int(intent_id),)).fetchone()
        for asset_id in affected_asset_ids:
            invalidate_asset_cache(asset_id)
        _update_deletion_log(int(intent_id), "done", "deletion_completed", log_message, finished=True)
        if intent["trigger_source"] != "emby_webhook":
            add_notification(
                f"deletion:{intent_id}:completed",
                "success",
                "115 删除同步完成",
                "源文件已按精确 ID 移入 115 回收站。",
                "strm",
            )
        return dict(row)
    except (P115Error, DeletionWorkflowError) as exc:
        with db() as conn:
            conn.execute(
                f"""UPDATE deletion_intents SET state='requested',message_safe=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders}) AND state='executing'""",
                (_safe_message(str(exc)), *operation_ids),
            )
        _update_deletion_log(int(intent_id), "failed", "deletion_failed", _safe_message(str(exc)), finished=True)
        if intent["trigger_source"] != "emby_webhook":
            add_notification(f"deletion:{intent_id}:failed", "error", "115 删除同步失败", _safe_message(str(exc)), "strm", deliver=False)
        raise DeletionWorkflowError(_safe_message(str(exc))) from exc


def _directory_operation_intents(intent: dict[str, Any], directory_path: str) -> list[dict[str, Any]]:
    trigger_ref = str(intent.get("trigger_ref") or "").strip()
    with db() as conn:
        if trigger_ref:
            rows = conn.execute(
                """SELECT i.*,a.file_id,a.parent_id,a.name AS asset_name,a.size AS asset_size,
                          a.relative_path AS asset_relative_path,a.inventory_root_path,
                          a.account_id,a.provider,a.status AS asset_status
                   FROM deletion_intents i JOIN media_assets a ON a.id=i.asset_id
                   WHERE i.trigger_source='emby_webhook' AND i.trigger_ref=? ORDER BY i.id""",
                (trigger_ref,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT i.*,a.file_id,a.parent_id,a.name AS asset_name,a.size AS asset_size,
                          a.relative_path AS asset_relative_path,a.inventory_root_path,
                          a.account_id,a.provider,a.status AS asset_status
                   FROM deletion_intents i JOIN media_assets a ON a.id=i.asset_id WHERE i.id=?""",
                (int(intent["id"]),),
            ).fetchall()
    batch = [dict(row) for row in rows]
    if not batch or any(
        row["state"] != "requested"
        or row["provider"] != "p115"
        or row["asset_status"] != "ready"
        or _directory_scope_path(row) != directory_path
        for row in batch
    ):
        raise DeletionWorkflowError("Emby 目录删除意图不完整或状态已变化；未执行网盘操作")
    return batch


def _resolve_directory_target(
    intents: list[dict[str, Any]],
    directory_path: str,
    p115: P115Client,
) -> tuple[str, list[int]]:
    scope = PurePosixPath(_safe_relative_path_or_directory(directory_path))
    if not scope.parts:
        raise DeletionWorkflowError("拒绝删除 115 来源根目录")
    accounts = {str(intent.get("account_id") or "") for intent in intents}
    stored_roots = {str(intent.get("inventory_root_path") or "").strip() for intent in intents}
    roots = {_normalized_inventory_root(root) for root in stored_roots}
    if len(accounts) != 1 or len(stored_roots) != 1 or len(roots) != 1:
        raise DeletionWorkflowError("Emby 目录映射跨越多个 115 账号或来源根目录；未执行网盘操作")
    target_paths: list[str] = []
    direct_parent_ids: set[str] = set()
    all_targets_are_direct_parents = True
    for intent in intents:
        asset_path = PurePosixPath(_safe_asset_relative_path(str(intent.get("asset_relative_path") or "")))
        if len(asset_path.parts) <= len(scope.parts):
            raise DeletionWorkflowError("115 资产路径不能证明 Emby 删除目录；未执行网盘操作")
        projected = str(asset_path.with_suffix(".strm"))
        with db() as conn:
            entries = conn.execute(
                """SELECT relative_path FROM strm_entries
                   WHERE asset_id=? AND status IN ('ready','pending_remove')""",
                (int(intent["asset_id"]),),
            ).fetchall()
        if not any(_canonical_relative_path(str(entry["relative_path"])) == _canonical_relative_path(projected) for entry in entries):
            raise DeletionWorkflowError("STRM 与 115 资产目录不再一致；未执行目录删除")
        target = str(PurePosixPath(*asset_path.parts[: len(scope.parts)]))
        if _canonical_relative_path(target) != _canonical_relative_path(str(scope)):
            raise DeletionWorkflowError("Emby 删除目录未唯一对应 115 资产目录；未执行网盘操作")
        target_paths.append(target)
        asset_parent = str(asset_path.parent)
        all_targets_are_direct_parents = all_targets_are_direct_parents and (
            _canonical_relative_path(asset_parent) == _canonical_relative_path(target)
        )
        direct_parent_ids.add(str(intent.get("parent_id") or "").strip())
    if len({_canonical_relative_path(path) for path in target_paths}) != 1:
        raise DeletionWorkflowError("Emby 删除目录对应多个 115 目录；未执行网盘操作")
    target_path = target_paths[0]
    root_path = next(iter(roots))
    if all_targets_are_direct_parents and len(direct_parent_ids) == 1:
        directory_id = next(iter(direct_parent_ids))
    else:
        if not root_path:
            raise DeletionWorkflowError("缺少 115 来源根路径，无法安全解析上级删除目录")
        remote_path = f"/{target_path}" if root_path == "/" else f"{root_path}/{target_path}"
        directory_id = str(p115.directory_id(remote_path)).strip()
    if directory_id in {"", "0"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", directory_id):
        raise DeletionWorkflowError("未解析到安全的 115 目录 ID；未执行网盘操作")
    escaped_target = target_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with db() as conn:
        rows = conn.execute(
            """SELECT id,relative_path FROM media_assets
               WHERE provider='p115' AND account_id=? AND inventory_root_path=?
                 AND relative_path LIKE ? ESCAPE '\\' AND status<>'deleted'
               ORDER BY id LIMIT 10001""",
            (next(iter(accounts)), next(iter(stored_roots)), f"{escaped_target}/%"),
        ).fetchall()
    prefix = f"{_canonical_relative_path(target_path)}/"
    affected_asset_ids = [
        int(row["id"])
        for row in rows
        if _canonical_relative_path(str(row["relative_path"])).startswith(prefix)
    ]
    if len(affected_asset_ids) > 10000:
        raise DeletionWorkflowError("对应 115 目录包含超过 10000 条本地资产记录；已拒绝目录删除")
    operation_asset_ids = {int(intent["asset_id"]) for intent in intents}
    if not operation_asset_ids.issubset(set(affected_asset_ids)):
        raise DeletionWorkflowError("115 目录范围未覆盖全部 Emby 删除映射；未执行网盘操作")
    return directory_id, affected_asset_ids


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
                          MAX(CASE WHEN state='completed' AND trash_receipt_json LIKE '%"scope":"directory"%' THEN 1 ELSE 0 END) AS directory_completed
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
                message = (
                    f"115 已按 Emby 目录删除范围将对应媒体目录移入回收站，{completed} 个 STRM 映射已标记移除"
                    if directory_completed
                    else f"115 已确认 {completed} 个源文件移入回收站，STRM 映射已标记移除"
                )
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


def _parent_directory(relative_path: str) -> str:
    parent = str(PurePosixPath(_safe_relative_path(relative_path)).parent)
    # A movie STRM directly under the configured library root must never
    # turn into a request to trash the matching 115 inventory root.
    return "" if parent in {"", "."} else _safe_relative_path_or_directory(parent)


def _strm_directory_is_exclusive(relative_path: str, asset_id: int) -> bool:
    directory = _parent_directory(relative_path)
    if not directory:
        return False
    prefix = f"{_canonical_relative_path(directory)}/"
    with db() as conn:
        rows = conn.execute(
            """SELECT asset_id,relative_path FROM strm_entries
               WHERE asset_id<>? AND status IN ('ready','pending_remove')""",
            (int(asset_id),),
        ).fetchall()
    return not any(_canonical_relative_path(str(row["relative_path"])).startswith(prefix) for row in rows)


def _deletion_scope_receipt(directory_path: str) -> str:
    payload = {"scope": "directory", "relative_path": directory_path} if directory_path else {"scope": "file"}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _deletion_scope(intent: dict[str, Any]) -> tuple[str, str]:
    raw = str(intent.get("trash_receipt_json") or "").strip()
    if not raw:
        return "file", ""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeletionWorkflowError("删除意图范围记录无效；未执行网盘操作") from exc
    if not isinstance(payload, dict) or payload.get("scope") not in {"file", "directory"}:
        raise DeletionWorkflowError("删除意图范围记录无效；未执行网盘操作")
    if payload["scope"] == "file":
        return "file", ""
    directory_path = _safe_relative_path_or_directory(str(payload.get("relative_path") or ""))
    return "directory", directory_path


def _directory_scope_path(intent: dict[str, Any]) -> str:
    scope, directory_path = _deletion_scope(intent)
    return directory_path if scope == "directory" else ""


def deletion_intent_deletes_directory(intent: dict[str, Any]) -> bool:
    try:
        return _deletion_scope(intent)[0] == "directory"
    except DeletionWorkflowError:
        return False


def _safe_asset_relative_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or len(path.parts) < 2
        or any(part in {"", ".", ".."} or any(char in part for char in "\r\n\x00") for part in path.parts)
    ):
        raise DeletionWorkflowError("115 资产相对路径无效；未执行目录删除")
    return str(path)


def _normalized_inventory_root(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    return "/" if raw == "/" else raw.rstrip("/")


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
