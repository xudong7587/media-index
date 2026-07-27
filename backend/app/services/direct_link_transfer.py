from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
import time
from urllib.parse import urlsplit

from app.clients.pansou import infer_share_provider
from app.clients.p115 import P115Client, P115CloudDownloadResult, P115Error
from app.clients.qas import QasClient
from app.core.config import get_settings
from app.db.database import db
from app.services.notifications import add_notification
from app.services.qas_executor import qas_trigger_accepted
from app.services.share_inspector import inspect_share


_LINK_RE = re.compile(r"(magnet:\?xt=[^\s]+|ed2k://[^\s]+|https?://[^\s]+)", re.IGNORECASE)
_OFFLINE_SCHEMES = {"magnet", "ed2k"}


@dataclass(frozen=True)
class DirectLinkResult:
    ok: bool
    job_id: int | None
    message: str
    unsupported: bool = False


def extract_download_link(text: str) -> str:
    match = _LINK_RE.search(str(text or "").strip())
    return match.group(1).strip() if match else ""


def looks_like_download_link(text: str) -> bool:
    return bool(extract_download_link(text))


def handle_direct_link_transfer(command: str, from_user: str = "") -> DirectLinkResult:
    settings = get_settings()
    link = extract_download_link(command)
    if not link:
        return DirectLinkResult(False, None, "没有识别到下载链接")
    if not settings.direct_download_enabled:
        return DirectLinkResult(False, None, "下载链接自动下载尚未启用")

    provider = settings.direct_download_provider.strip().lower() or settings.default_provider_key()
    if provider not in {"qas", "p115"}:
        provider = "qas"
    save_path = _direct_save_path(provider)
    try:
        _validate_provider_path(provider, save_path)
    except ValueError as exc:
        return DirectLinkResult(False, None, str(exc))
    parsed = urlsplit(link)
    if parsed.scheme.lower() in _OFFLINE_SCHEMES:
        if provider == "p115":
            job_id, duplicate = _create_direct_job(link, provider, save_path, from_user)
            if duplicate:
                return DirectLinkResult(True, job_id, "相同下载链接任务已在运行，未重复触发")
            try:
                return _finish_p115_cloud_download_job(job_id, _transfer_p115_cloud_download(link, save_path), save_path)
            except Exception as exc:
                message = _offline_failure_message(exc)
                _finish_job(job_id, "failed", "provider_failed", message)
                add_notification(f"direct-link:{job_id}:failed", "error", "115 离线下载失败", message, "history")
                return DirectLinkResult(False, job_id, message)
        return DirectLinkResult(False, None, "磁力/电驴链接目前只支持关联网盘选择 115 后提交离线下载", True)

    _cloud_type, inferred_provider = infer_share_provider(link)
    if inferred_provider and inferred_provider != provider:
        provider = inferred_provider
        save_path = _direct_save_path(provider)
        try:
            _validate_provider_path(provider, save_path)
        except ValueError as exc:
            return DirectLinkResult(False, None, str(exc))
    if not inferred_provider:
        if provider == "p115":
            job_id, duplicate = _create_direct_job(link, provider, save_path, from_user)
            if duplicate:
                return DirectLinkResult(True, job_id, "相同下载链接任务已在运行，未重复触发")
            try:
                return _finish_p115_cloud_download_job(job_id, _transfer_p115_cloud_download(link, save_path), save_path)
            except Exception as exc:
                message = _offline_failure_message(exc)
                _finish_job(job_id, "failed", "provider_failed", message)
                add_notification(f"direct-link:{job_id}:failed", "error", "115 离线下载失败", message, "history")
                return DirectLinkResult(False, job_id, message)
        return DirectLinkResult(False, None, "普通 HTTP 下载链接目前只支持关联网盘选择 115 后提交离线下载", True)

    job_id, duplicate = _create_direct_job(link, provider, save_path, from_user)
    if duplicate:
        return DirectLinkResult(True, job_id, f"相同下载链接任务已在运行，未重复触发")
    try:
        if provider == "p115":
            count = _transfer_p115_share(link, save_path)
            message = f"115 分享链接已转存到 {save_path}，共 {count} 个文件"
        else:
            count = _transfer_qas_share(link, save_path)
            message = f"夸克分享链接已提交到 {save_path}，共 {count} 个文件"
        _finish_job(job_id, "done", "provider_completed", message)
        add_notification(f"direct-link:{job_id}:done", "success", "下载链接转存完成", message, "history")
        return DirectLinkResult(True, job_id, message)
    except Exception as exc:
        message = f"下载链接转存失败：{_user_error_message(exc)}"
        _finish_job(job_id, "failed", "provider_failed", message)
        add_notification(f"direct-link:{job_id}:failed", "error", "下载链接转存失败", message, "history")
        return DirectLinkResult(False, job_id, message)


def _direct_save_path(provider: str) -> str:
    settings = get_settings()
    configured = settings.direct_download_save_path.strip()
    if configured:
        return configured
    root = settings.provider_save_root(provider).rstrip("/")
    return f"{root}/下载链接"


def _validate_provider_path(provider: str, path: str) -> None:
    root = get_settings().provider_save_root(provider).rstrip("/")
    normalized = "/" + "/".join(part for part in path.replace("\\", "/").split("/") if part)
    if not root or normalized == "/" or not (normalized == root or normalized.startswith(f"{root}/")):
        raise ValueError("下载链接默认路径必须位于所选网盘保存根目录内")


def _create_direct_job(link: str, provider: str, save_path: str, from_user: str) -> tuple[int, bool]:
    digest = sha256(f"{provider}\n{save_path}\n{link}".encode("utf-8")).hexdigest()[:24]
    execution_key = f"direct:{digest}"
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM transfer_jobs WHERE execution_key=? AND status IN ('running','ready','triggered') ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if existing:
            return int(existing["id"]), True
        return int(
            conn.execute(
                """
                INSERT INTO transfer_jobs(
                    media_type,display_title,target,provider,status,stage,message,share_url,save_path,execution_key
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "direct",
                    "下载链接",
                    "cloud",
                    provider,
                    "running",
                    "provider_submitting",
                    f"正在处理来自 {from_user or '交互指令'} 的下载链接",
                    link,
                    save_path,
                    execution_key,
                ),
            ).lastrowid
        ), False


def _finish_job(job_id: int, status: str, stage: str, message: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE transfer_jobs SET status=?,stage=?,message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, stage, message[:1000], job_id),
        )


def _transfer_qas_share(link: str, save_path: str) -> int:
    client = QasClient()
    if not client.configured():
        raise RuntimeError("QAS 未配置")
    inspection = inspect_share(client, link)
    files = [item.name for item in inspection.files if item.name] if inspection.valid else []
    if not files:
        raise RuntimeError(inspection.error or "分享链接内没有可转存文件")
    task_base = {
        "taskname": f"MediaIndex.下载链接.{sha256(link.encode('utf-8')).hexdigest()[:10]}",
        "shareurl": inspection.share_url or link,
        "savepath": save_path,
        "extract_code": "",
        "runweek": [time.localtime().tm_wday + 1],
    }
    for name in files:
        task = dict(task_base)
        task["pattern"] = f"^{re.escape(name)}$"
        task["replace"] = name
        output = client.run_task(task)
        if not qas_trigger_accepted(output):
            raise RuntimeError("QAS 未接受直接链接任务")
    return len(files)


def _transfer_p115_share(link: str, save_path: str) -> int:
    client = P115Client()
    if not client.configured():
        raise P115Error("115 Cookie 未配置")
    snapshot = client.inspect_share(link)
    files = [item for item in snapshot.files if not item.is_dir and item.file_id]
    if not files:
        raise P115Error("分享链接内没有可转存文件")
    cid = client.ensure_directory(save_path)
    client.receive_share_files(snapshot.share, [item.file_id for item in files], cid)
    return len(files)


def _transfer_p115_cloud_download(link: str, save_path: str) -> P115CloudDownloadResult:
    return P115Client().add_cloud_download(link, save_path)


def _finish_p115_cloud_download_job(
    job_id: int,
    result: P115CloudDownloadResult,
    save_path: str,
) -> DirectLinkResult:
    if result.status == "done":
        message = f"115 云下载已完成，文件已保存到 {save_path}"
        if result.message and result.message not in message:
            message = f"{message}（{result.message}）"
        _finish_job(job_id, "done", "provider_completed", message)
        add_notification(f"direct-link:{job_id}:done", "success", "115 云下载完成", message, "history")
        return DirectLinkResult(True, job_id, message)
    if result.status == "failed":
        message = result.message or "115 云下载失败"
        _finish_job(job_id, "failed", "provider_failed", message)
        add_notification(f"direct-link:{job_id}:failed", "error", "115 云下载失败", message, "history")
        return DirectLinkResult(False, job_id, message)
    message = f"115 离线下载任务已提交到 {save_path}，115 仍在处理中"
    if result.message and result.message not in message:
        message = f"{message}（{result.message}）"
    _finish_job(job_id, "triggered", "provider_submitting", message)
    add_notification(f"direct-link:{job_id}:triggered", "success", "115 离线下载已提交", message, "history")
    return DirectLinkResult(True, job_id, message)


def _offline_failure_message(exc: Exception) -> str:
    detail = _user_error_message(exc)
    if detail.startswith("115 离线下载任务提交失败"):
        return detail
    return f"115 离线下载任务提交失败：{detail}"


def _user_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message and message != type(exc).__name__:
        return message[:300]
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, Exception):
        cause_message = str(cause).strip()
        if cause_message and cause_message != type(cause).__name__:
            return cause_message[:300]
    return type(exc).__name__
