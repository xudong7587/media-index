from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.core.config import get_settings
from app.db.database import db
from app.services.bounded_range_stream import BoundedRangeStream, RangeStreamError, iter_range_chunks
from app.services.media_assets import AssetInput, MediaAssetError, register_asset


STREAM_BUFFER_BYTES = 8 * 1024 * 1024
UPLOAD_PART_BYTES = 16 * 1024 * 1024
ACTIVE_STATES = {"created", "fingerprinting", "rapid_probe", "upload_initializing", "streaming", "target_confirming"}
RUNNABLE_STATES = {"created", "failed_recoverable", "retry_wait"}
DELETABLE_STATES = {"created", "failed_recoverable", "paused_source_changed", "completed"}


class CrossCloudTransferError(RuntimeError):
    """Safe error shown for an explicit cross-cloud operation."""


class CrossCloudTransferCancelled(CrossCloudTransferError):
    pass


@dataclass(frozen=True)
class CrossCloudTransferRequest:
    source_parent_id: str
    source_file_id: str
    target_parent_path: str
    target_name: str = ""


def list_cross_cloud_transfers(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 200))
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM cross_cloud_transfers ORDER BY created_at DESC, id DESC LIMIT ?", (safe_limit,)
        ).fetchall()
    return [_public_record(dict(row)) for row in rows]


def get_cross_cloud_transfer(transfer_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),)).fetchone()
    return _public_record(dict(row)) if row else None


def transfer_events(transfer_id: int) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id,attempt,state,message,fingerprinted_bytes,uploaded_bytes,created_at
            FROM cross_cloud_transfer_events WHERE transfer_id=? ORDER BY id ASC
            """,
            (int(transfer_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_cross_cloud_transfer(transfer_id: int) -> None:
    """Delete one local terminal record without touching either cloud drive."""
    with db() as conn:
        row = conn.execute("SELECT state,cleanup_state FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),)).fetchone()
        if not row:
            raise CrossCloudTransferError("跨盘任务不存在")
        record = dict(row)
        if record["state"] not in DELETABLE_STATES:
            raise CrossCloudTransferError("只能删除未运行或已结束的任务")
        if record["cleanup_state"] == "remote_cleanup_pending":
            raise CrossCloudTransferError("任务仍有待核对的远端状态，暂不能删除记录")
        conn.execute("DELETE FROM cross_cloud_transfer_events WHERE transfer_id=?", (int(transfer_id),))
        conn.execute("DELETE FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),))


def create_cross_cloud_transfer(
    request: CrossCloudTransferRequest,
    *,
    quark_client: QuarkClient | None = None,
) -> dict[str, Any]:
    """Create a read-validated Quark -> 115 transfer without remote writes."""
    parent_id = _safe_id(request.source_parent_id, "夸克源目录 ID")
    file_id = _safe_id(request.source_file_id, "夸克源文件 ID")
    target_path = _safe_cloud_path(request.target_parent_path)
    quark = quark_client or QuarkClient()
    if not quark.configured():
        raise CrossCloudTransferError("夸克连接未配置")
    try:
        source = quark.file_in_directory(parent_id, file_id)
    except QuarkError as exc:
        raise CrossCloudTransferError(str(exc)) from exc
    if source.size <= 0:
        raise CrossCloudTransferError("只支持大小明确的夸克普通文件")
    target_name = _safe_filename(request.target_name or source.name)
    execution_key = "|".join(("quark", parent_id, file_id, str(source.size), "p115", target_path, target_name))
    with db() as conn:
        existing = conn.execute(
            """
            SELECT * FROM cross_cloud_transfers
            WHERE execution_key=? AND state IN ('created','fingerprinting','rapid_probe','upload_initializing','streaming','target_confirming')
            ORDER BY id DESC LIMIT 1
            """,
            (execution_key,),
        ).fetchone()
        if existing:
            return _public_record(dict(existing))
        cursor = conn.execute(
            """
            INSERT INTO cross_cloud_transfers(
                execution_key,source_parent_id,source_file_id,source_name,source_size,
                target_parent_path,target_name,total_bytes,state,stage_message
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (execution_key, parent_id, file_id, source.name, source.size, target_path, target_name, source.size, "created", "已验证夸克源文件，等待明确启动"),
        )
        transfer_id = int(cursor.lastrowid)
        _event(conn, transfer_id, 0, "created", "已验证夸克源文件，尚未对任一网盘写入", 0, 0)
        row = conn.execute("SELECT * FROM cross_cloud_transfers WHERE id=?", (transfer_id,)).fetchone()
    return _public_record(dict(row))


def request_cancel(transfer_id: int) -> dict[str, Any]:
    """Ask a worker to stop at the next bounded read; never hide remote residue."""
    with db() as conn:
        row = conn.execute("SELECT * FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),)).fetchone()
        if not row:
            raise CrossCloudTransferError("跨盘任务不存在")
        record = dict(row)
        if record["state"] not in ACTIVE_STATES | RUNNABLE_STATES:
            return _public_record(record)
        conn.execute(
            "UPDATE cross_cloud_transfers SET state='cancel_requested',stage_message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            ("已请求停止，正在等待当前内存分片结束", int(transfer_id)),
        )
        _event(conn, int(transfer_id), int(record["attempt"]), "cancel_requested", "已请求停止", int(record["fingerprinted_bytes"]), int(record["uploaded_bytes"]))
        updated = conn.execute("SELECT * FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),)).fetchone()
    return _public_record(dict(updated))


def run_cross_cloud_transfer(
    transfer_id: int,
    *,
    quark_client: QuarkClient | None = None,
    p115_client: P115Client | None = None,
) -> dict[str, Any]:
    """Run one explicit Quark -> 115 attempt using bounded in-memory reads.

    A process interruption is intentionally not auto-resumed: the startup
    recovery marks it recoverable, and the user can start a fresh attempt from
    its preserved record.  This avoids assuming an opaque provider multipart
    session is still safe after credentials or source content changed.
    """
    record = _claim_attempt(transfer_id)
    if record is None:
        existing = get_cross_cloud_transfer(transfer_id)
        if not existing:
            raise CrossCloudTransferError("跨盘任务不存在")
        return existing
    quark = quark_client or QuarkClient()
    p115 = p115_client or P115Client()
    try:
        if not quark.configured():
            raise CrossCloudTransferError("夸克连接已失效，请重新连接后恢复")
        if not p115.configured():
            raise CrossCloudTransferError("115 连接未配置或已失效，请重新连接后恢复")
        source = quark.file_in_directory(record["source_parent_id"], record["source_file_id"])
        if source.name != record["source_name"] or source.size != int(record["source_size"]):
            _transition(transfer_id, "paused_source_changed", "夸克源文件名称或大小已变化，未继续写入 115")
            return _require_transfer(transfer_id)

        read_range = lambda start, end, limit: quark.read_download_range(source.file_id, start, end, max_bytes=limit)
        source_sha1 = str(getattr(source, "sha1", "") or "").strip().upper()
        provider_sha1 = bool(re.fullmatch(r"[A-F0-9]{40}", source_sha1))
        if not provider_sha1:
            _update_fields(transfer_id, strategy="stream_hash_then_probe")
            _transition(
                transfer_id,
                "fingerprinting",
                "夸克未提供可信完整 SHA1，正在不落盘完整读取并计算指纹；此阶段不是秒传",
            )
            digest = hashlib.sha1()
            fingerprinted = 0
            for chunk in iter_range_chunks(source.size, read_range, chunk_bytes=STREAM_BUFFER_BYTES):
                _raise_if_cancelled(transfer_id)
                digest.update(chunk)
                fingerprinted += len(chunk)
                _update_progress(transfer_id, fingerprinted_bytes=fingerprinted)
            source_sha1 = digest.hexdigest().upper()
        else:
            _update_fields(transfer_id, strategy="provider_sha1_rapid_then_stream")
            _transition(transfer_id, "fingerprinting", "夸克已直接提供可信完整 SHA1，无需完整读取源文件")
        _update_fields(transfer_id, source_sha1=source_sha1, fingerprinted_bytes=source.size)

        # Directory creation is the first cloud-side write and happens only
        # after the user explicitly started this persisted transfer record.
        _transition(
            transfer_id,
            "upload_initializing",
            "正在确认 115 目标目录并探测真正 SHA1 秒传"
            if provider_sha1
            else "源指纹已通过完整读取计算；正在确认 115 目标目录并探测内容复用",
        )
        target_parent_id = p115.ensure_directory(record["target_parent_path"])
        _update_fields(transfer_id, target_parent_id=target_parent_id)

        def read_sign_check(sign_check: str) -> bytes:
            start, end = _parse_sign_check(sign_check, source.size)
            return quark.read_download_range(source.file_id, start, end, max_bytes=STREAM_BUFFER_BYTES)

        _transition(
            transfer_id,
            "rapid_probe",
            "正在向 115 探测真正 SHA1 秒传" if provider_sha1 else "正在向 115 探测内容复用（不计为秒传）",
        )
        initialization = p115.initialize_stream_upload(
            record["target_name"], source_sha1, source.size, target_parent_id, read_sign_check
        )
        _update_fields(
            transfer_id,
            rapid_probe_result="hit" if initialization.reused else "miss",
            remote_upload_id=initialization.upload_id,
        )
        if not initialization.reused:
            _transition(
                transfer_id,
                "streaming",
                "真正 SHA1 秒传未命中，正在不落盘流式传输到 115"
                if provider_sha1
                else "115 内容复用未命中，正在以固定内存上限不落盘流式传输",
            )

            def on_upload_read(position: int) -> None:
                _raise_if_cancelled(transfer_id)
                _update_progress(transfer_id, uploaded_bytes=max(0, min(position, source.size)))

            with BoundedRangeStream(
                source.size,
                read_range,
                buffer_bytes=STREAM_BUFFER_BYTES,
                on_read=on_upload_read,
            ) as stream:
                p115.upload_stream(
                    stream,
                    record["target_name"],
                    source_sha1,
                    source.size,
                    target_parent_id,
                    part_size=UPLOAD_PART_BYTES,
                )
            _update_progress(transfer_id, uploaded_bytes=source.size)

        _transition(transfer_id, "target_confirming", "正在核对 115 最终文件身份和大小")
        target_file_id = _confirm_target_file(p115, target_parent_id, record["target_name"], source.size)
        register_asset(
            AssetInput(
                provider="p115",
                file_id=target_file_id,
                parent_id=target_parent_id,
                name=record["target_name"],
                relative_path=_target_relative_path(record["target_parent_path"], record["target_name"]),
                inventory_root_path=getattr(get_settings(), "p115_root_path", "/"),
                size=source.size,
                sha1=source_sha1,
                source_transfer_id=transfer_id,
                status="ready",
            )
        )
        strm_message = _reconcile_p115_strm_if_enabled()
        if initialization.reused and provider_sha1:
            completion_message = f"真正 SHA1 秒传已命中；未读取完整夸克源文件，且未写入本地媒体文件{strm_message}"
        elif initialization.reused:
            completion_message = f"115 已复用相同内容；但夸克源已完整读取以计算 SHA1，因此不计为真正秒传{strm_message}"
        elif provider_sha1:
            completion_message = f"真正 SHA1 秒传未命中，已完成不落盘流式传输{strm_message}"
        else:
            completion_message = f"夸克无原生 SHA1，已完成指纹校验和不落盘流式传输；未冒充秒传{strm_message}"
        _transition(
            transfer_id,
            "completed",
            completion_message,
            target_file_id=target_file_id,
            uploaded_bytes=source.size if not initialization.reused else 0,
            cleanup_state="not_needed",
            completed=True,
        )
    except CrossCloudTransferCancelled:
        _transition(
            transfer_id,
            "cancelled_with_remote_residue",
            "已在安全边界停止；115 远端上传会话可能需要后续清理",
            cleanup_state="remote_cleanup_pending",
        )
    except (CrossCloudTransferError, QuarkError, P115Error, RangeStreamError, MediaAssetError) as exc:
        _transition(
            transfer_id,
            "failed_recoverable",
            _safe_error_message(str(exc)),
            last_error_code=exc.__class__.__name__,
            last_error_message_safe=_safe_error_message(str(exc)),
            cleanup_state="remote_cleanup_pending" if _may_have_remote_residue(transfer_id) else "not_needed",
        )
    except Exception:
        _transition(
            transfer_id,
            "failed_recoverable",
            "跨盘任务发生未分类错误；已保留上下文，可在检查连接后重试",
            last_error_code="unexpected_error",
            last_error_message_safe="跨盘任务发生未分类错误；已保留上下文，可在检查连接后重试",
            cleanup_state="remote_cleanup_pending" if _may_have_remote_residue(transfer_id) else "not_needed",
        )
    return _require_transfer(transfer_id)


def _reconcile_p115_strm_if_enabled() -> str:
    from app.services.strm_reconciler import reconcile_strm
    from app.services.cloud_inventory import scan_p115_inventory

    if not bool(getattr(get_settings(), "p115_strm_enabled", False)):
        return ""
    try:
        settings = get_settings()
        source_root = settings.provider_strm_source_root("p115")
        scan_p115_inventory(source_root, mark_missing=False)
        result = reconcile_strm(provider="p115", source_root_path=source_root)
        return f"；STRM 已校正（新增 {result.created}，替换 {result.replaced}）"
    except Exception as exc:
        # Cloud transfer is already complete at this point. A local filesystem,
        # metadata or configuration failure must remain a retryable add-on and
        # must never roll the completed remote write back to a failed task.
        return f"；STRM 待处理（{exc.__class__.__name__}），请到 STRM 页面重试"


def _target_relative_path(target_parent_path: str, target_name: str) -> str:
    from app.core.config import get_settings

    target = _safe_cloud_path(target_parent_path).strip("/")
    root = _safe_cloud_path(getattr(get_settings(), "p115_root_path", "/")).strip("/")
    if root and target == root:
        relative_dir = ""
    elif root and target.startswith(f"{root}/"):
        relative_dir = target[len(root) + 1 :]
    else:
        relative_dir = target
    return "/".join(part for part in (relative_dir, _safe_filename(target_name)) if part)


def recover_interrupted_cross_cloud_transfers() -> int:
    """Make interrupted in-memory streaming attempts explicitly recoverable."""
    placeholders = ",".join("?" for _ in ACTIVE_STATES)
    with db() as conn:
        rows = conn.execute(
            f"SELECT id,attempt,fingerprinted_bytes,uploaded_bytes FROM cross_cloud_transfers WHERE state IN ({placeholders})",
            tuple(ACTIVE_STATES),
        ).fetchall()
        for row in rows:
            transfer_id = int(row["id"])
            conn.execute(
                """
                UPDATE cross_cloud_transfers
                SET state='failed_recoverable',stage_message=?,last_error_code='interrupted',
                    last_error_message_safe=?,cleanup_state='remote_cleanup_pending',updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                ("服务重启前任务被中断；请检查连接后新建恢复尝试", "服务重启前任务被中断；请检查连接后新建恢复尝试", transfer_id),
            )
            _event(conn, transfer_id, int(row["attempt"]), "failed_recoverable", "服务重启前任务被中断；请检查连接后新建恢复尝试", int(row["fingerprinted_bytes"]), int(row["uploaded_bytes"]))
    return len(rows)


def _claim_attempt(transfer_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),)).fetchone()
        if not row:
            raise CrossCloudTransferError("跨盘任务不存在")
        record = dict(row)
        if record["state"] not in RUNNABLE_STATES:
            return None
        updated = conn.execute(
            """
            UPDATE cross_cloud_transfers
            SET state='fingerprinting',attempt=attempt+1,stage_message=?,last_error_code='',last_error_message_safe='',
                fingerprinted_bytes=0,uploaded_bytes=0,updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND state IN ('created','failed_recoverable','retry_wait')
            """,
            ("正在准备新的不落盘传输尝试", int(transfer_id)),
        )
        if updated.rowcount != 1:
            return None
        current = conn.execute("SELECT * FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),)).fetchone()
        _event(conn, int(transfer_id), int(current["attempt"]), "fingerprinting", "正在准备新的不落盘传输尝试", 0, 0)
    return dict(current)


def _transition(transfer_id: int, state: str, message: str, *, completed: bool = False, **fields: Any) -> None:
    assignments = ["state=?", "stage_message=?", "updated_at=CURRENT_TIMESTAMP"]
    values: list[Any] = [state, _safe_error_message(message)]
    for name, value in fields.items():
        if name not in {"target_file_id", "uploaded_bytes", "cleanup_state", "last_error_code", "last_error_message_safe"}:
            continue
        assignments.append(f"{name}=?")
        values.append(value)
    if completed:
        assignments.append("completed_at=CURRENT_TIMESTAMP")
    values.append(int(transfer_id))
    with db() as conn:
        conn.execute(f"UPDATE cross_cloud_transfers SET {','.join(assignments)} WHERE id=?", values)
        row = conn.execute("SELECT attempt,fingerprinted_bytes,uploaded_bytes FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),)).fetchone()
        if row:
            _event(conn, int(transfer_id), int(row["attempt"]), state, _safe_error_message(message), int(row["fingerprinted_bytes"]), int(row["uploaded_bytes"]))


def _update_progress(transfer_id: int, *, fingerprinted_bytes: int | None = None, uploaded_bytes: int | None = None) -> None:
    assignments = ["updated_at=CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if fingerprinted_bytes is not None:
        assignments.append("fingerprinted_bytes=?")
        values.append(int(fingerprinted_bytes))
    if uploaded_bytes is not None:
        assignments.append("uploaded_bytes=?")
        values.append(int(uploaded_bytes))
    if len(assignments) == 1:
        return
    values.append(int(transfer_id))
    with db() as conn:
        conn.execute(f"UPDATE cross_cloud_transfers SET {','.join(assignments)} WHERE id=?", values)


def _update_fields(transfer_id: int, **fields: Any) -> None:
    allowed = {"source_sha1", "fingerprinted_bytes", "target_parent_id", "rapid_probe_result", "remote_upload_id", "strategy"}
    items = [(name, value) for name, value in fields.items() if name in allowed]
    if not items:
        return
    assignments = [f"{name}=?" for name, _ in items] + ["updated_at=CURRENT_TIMESTAMP"]
    values = [value for _, value in items] + [int(transfer_id)]
    with db() as conn:
        conn.execute(f"UPDATE cross_cloud_transfers SET {','.join(assignments)} WHERE id=?", values)


def _raise_if_cancelled(transfer_id: int) -> None:
    with db() as conn:
        row = conn.execute("SELECT state FROM cross_cloud_transfers WHERE id=?", (int(transfer_id),)).fetchone()
    if row and str(row["state"]) == "cancel_requested":
        raise CrossCloudTransferCancelled("已请求停止")


def _may_have_remote_residue(transfer_id: int) -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT state,remote_upload_id,target_parent_id FROM cross_cloud_transfers WHERE id=?",
            (int(transfer_id),),
        ).fetchone()
    if not row:
        return False
    return bool(
        str(row["remote_upload_id"] or "").strip()
        or str(row["target_parent_id"] or "").strip()
        or str(row["state"] or "") in {"rapid_probe", "streaming", "target_confirming"}
    )


def _confirm_target_file(p115: P115Client, parent_id: str, name: str, size: int) -> str:
    matches = [item for item in p115.list_directory(parent_id) if not item.is_dir and item.name == name and item.size == size]
    if len(matches) != 1:
        raise CrossCloudTransferError("115 目标文件无法唯一确认，已保留任务供人工核对")
    return matches[0].file_id


def _parse_sign_check(value: str, file_size: int) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*[-,:]\s*(\d+)\s*", str(value or ""))
    if not match:
        raise CrossCloudTransferError("115 返回了不兼容的秒传校验范围")
    start, end = int(match.group(1)), int(match.group(2))
    if start < 0 or end < start or end >= file_size or end - start + 1 > STREAM_BUFFER_BYTES:
        raise CrossCloudTransferError("115 秒传校验范围不安全")
    return start, end


def _safe_id(value: str, label: str) -> str:
    safe = str(value or "").strip()
    if not safe or len(safe) > 256 or any(char in safe for char in "\r\n/\\"):
        raise CrossCloudTransferError(f"{label}无效")
    return safe


def _safe_cloud_path(value: str) -> str:
    parts = [part.strip() for part in str(value or "").replace("\\", "/").split("/") if part.strip()]
    if not parts or any(part in {".", ".."} or len(part) > 180 for part in parts):
        raise CrossCloudTransferError("115 目标目录无效")
    return "/" + "/".join(parts)


def _safe_filename(value: str) -> str:
    safe = str(value or "").strip()
    if not safe or len(safe) > 240 or any(char in safe for char in "\\/\r\n\x00") or safe in {".", ".."}:
        raise CrossCloudTransferError("115 目标文件名无效")
    return safe


def _safe_error_message(value: str) -> str:
    text = str(value or "任务失败").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"(?i)(cookie|seid|token|authorization)\s*[=:]\s*[^\s,;]+", r"\1=[已隐藏]", text)
    return text[:500] or "任务失败"


def _event(conn: Any, transfer_id: int, attempt: int, state: str, message: str, fingerprinted: int, uploaded: int) -> None:
    conn.execute(
        """
        INSERT INTO cross_cloud_transfer_events(transfer_id,attempt,state,message,fingerprinted_bytes,uploaded_bytes)
        VALUES(?,?,?,?,?,?)
        """,
        (transfer_id, attempt, state, message, fingerprinted, uploaded),
    )


def _require_transfer(transfer_id: int) -> dict[str, Any]:
    record = get_cross_cloud_transfer(transfer_id)
    if not record:
        raise CrossCloudTransferError("跨盘任务不存在")
    return record


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    # Database rows intentionally contain no credential, temporary URL, or
    # share credential. Keep this explicit as fields are added in later phases.
    return record
