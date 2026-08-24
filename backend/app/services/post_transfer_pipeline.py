from __future__ import annotations

import hashlib
from datetime import date

from app.core.config import get_settings
from app.db.database import db
from app.services.cloud_inventory import scan_p115_inventory, scan_quark_inventory
from app.services.emby_library_refresh import refresh_emby_library_after_strm
from app.services.media_workflow import update_media_workflow_step
from app.services.notifications import add_notification
from app.services.strm_reconciler import reconcile_strm


def run_post_transfer_pipeline(
    job_id: int,
    *,
    provider: str,
    title: str,
    poster_url: str = "",
    openlist_message: str = "",
) -> None:
    """Run configured post-transfer steps without hiding partial failures.

    Provider scans read directory metadata only. Incremental runs deliberately
    do not mark missing assets unavailable; destructive reconciliation remains
    exclusive to an explicit full scan.
    """
    settings = get_settings()
    if settings.openlist_enabled and settings.openlist_auto_sync:
        if "未完成" in openlist_message or "失败" in openlist_message:
            openlist_status = "failed"
        elif "提交" in openlist_message or "后台复制任务" in openlist_message:
            openlist_status = "running"
        elif openlist_message:
            openlist_status = "done"
        else:
            openlist_status = "skipped"
        update_media_workflow_step(
            job_id,
            "openlist_sync",
            openlist_status,
            openlist_message or "本次转存无需 OpenList 跨盘同步",
        )

    normalized_provider = "p115" if provider == "p115" else "quark" if provider == "quark" else ""
    enabled = (
        settings.p115_strm_enabled if normalized_provider == "p115"
        else settings.quark_strm_enabled if normalized_provider == "quark"
        else False
    )
    if not normalized_provider or not enabled:
        update_media_workflow_step(job_id, "strm_generate", "skipped", "当前网盘未启用自动 STRM 生成")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "没有需要入库的 STRM 变化")
        _notify_if_enabled(job_id, title=title, poster_url=poster_url, message="网盘转存已完成")
        return

    root_path = settings.provider_strm_source_root(normalized_provider)
    if not root_path or not settings.strm_output_root:
        update_media_workflow_step(job_id, "strm_generate", "failed", "STRM 来源目录或输出目录未配置完整")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 未生成，未通知 Emby")
        return

    try:
        update_media_workflow_step(job_id, "strm_generate", "running", "正在增量读取网盘目录元数据")
        scan = (
            scan_p115_inventory(root_path, mark_missing=False)
            if normalized_provider == "p115"
            else scan_quark_inventory(root_path, mark_missing=False)
        )
        result = reconcile_strm(
            output_root=settings.strm_output_root,
            provider=normalized_provider,
            source_root_path=scan.root_path,
        )
        update_media_workflow_step(
            job_id,
            "strm_generate",
            "done",
            f"增量扫描 {scan.files_indexed} 个文件；新增 {result.created}，更新 {result.replaced}",
        )
    except Exception as exc:
        update_media_workflow_step(job_id, "strm_generate", "failed", f"STRM 自动生成失败（{type(exc).__name__}）")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 未完成，未通知 Emby")
        return

    if settings.emby_library_refresh_enabled:
        try:
            update_media_workflow_step(job_id, "emby_refresh", "running", "正在通知 Emby 刷新媒体库")
            emby_message = refresh_emby_library_after_strm()
            update_media_workflow_step(job_id, "emby_refresh", "done", emby_message or "Emby 媒体库刷新已提交")
        except Exception as exc:
            update_media_workflow_step(job_id, "emby_refresh", "failed", f"Emby 入库通知失败（{type(exc).__name__}）")
            return
    _notify_if_enabled(job_id, title=title, poster_url=poster_url, message="STRM 已生成并提交 Emby 入库")


def _notify_if_enabled(job_id: int, *, title: str, poster_url: str, message: str) -> None:
    settings = get_settings()
    if not settings.notification_external_enabled:
        update_media_workflow_step(job_id, "library_notification", "skipped", "未启用外部入库通知")
        return
    try:
        update_media_workflow_step(job_id, "library_notification", "running", "正在发送入库图文通知")
        group = _notification_group(job_id, title)
        inserted = add_notification(
            f"library-ready:{group}:{date.today().isoformat()}",
            "success",
            f"{title or '媒体'} 已入库",
            message,
            action_page="media-server",
            poster_url=poster_url,
            deliver=False,
        )
        update_media_workflow_step(
            job_id,
            "library_notification",
            "done",
            "入库通知已聚合，等待 Emby 入库后发送" if inserted else "同一媒体文件夹已有待发送通知，未重复创建",
        )
    except Exception as exc:
        update_media_workflow_step(job_id, "library_notification", "failed", f"入库通知发送失败（{type(exc).__name__}）")


def _notification_group(job_id: int, title: str) -> str:
    with db() as conn:
        row = conn.execute("SELECT provider,save_path,tmdb_id,media_type FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
    values = dict(row) if row else {}
    save_path = str(values.get("save_path") or "").replace("\\", "/").rstrip("/")
    if "/season " in save_path.casefold():
        save_path = save_path.rsplit("/", 1)[0]
    raw = "|".join((str(values.get("provider") or ""), str(values.get("tmdb_id") or ""), str(values.get("media_type") or ""), save_path or title.strip()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
