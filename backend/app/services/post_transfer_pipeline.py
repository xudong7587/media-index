from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Iterable, Mapping

from app.core.config import get_settings
from app.db.database import db
from app.services.emby_library_refresh import refresh_emby_library_after_strm
from app.services.media_workflow import update_media_workflow_step
from app.services.notifications import add_notification
from app.services.targeted_strm import index_and_reconcile_targeted_strm
from app.services.paths import is_cloud_download_staging_path


def run_confirmed_native_transfer_post_processing(
    job_id: int,
    *,
    provider: str,
    save_path: str,
    outputs: Iterable[Mapping[str, Any]],
    title: str,
    poster_url: str = "",
    media_year: str = "",
    cloud_download_child: str = "",
) -> bool:
    """Continue one confirmed native transfer without widening its exact scope."""
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider not in {"p115", "quark"}:
        return False
    exact_outputs = tuple(dict(item) for item in outputs if isinstance(item, Mapping))
    if not str(save_path or "").strip() or not exact_outputs:
        return False
    staging_requested = bool(str(cloud_download_child or "").strip())
    if staging_requested and not is_cloud_download_staging_path(
        normalized_provider,
        save_path,
        cloud_download_child,
    ):
        update_media_workflow_step(job_id, "strm_generate", "failed", "互动云下载路径身份已失效，未生成原始文件 STRM")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 未生成，未通知 Emby")
        return True
    organizer_handled, _ = try_targeted_cloud_download_organization(
        provider=normalized_provider,
        target_path=save_path,
        target_files=exact_outputs,
        media_title=title,
        media_year=media_year,
    )
    if not organizer_handled and staging_requested:
        update_media_workflow_step(job_id, "strm_generate", "skipped", "云下载原始文件等待整理，不生成 STRM")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "等待云下载整理完成后再通知媒体库")
    elif not organizer_handled:
        run_post_transfer_pipeline(
            int(job_id),
            provider=normalized_provider,
            title=title,
            poster_url=poster_url,
            target_path=save_path,
            target_files=exact_outputs,
        )
    return True


def try_targeted_cloud_download_organization(
    *,
    provider: str,
    target_path: str,
    target_files: Iterable[Mapping[str, Any]],
    media_title: str = "",
    media_year: str = "",
    explicit_request: bool = False,
) -> tuple[bool, str]:
    """Route one exact native transfer into its selected cloud-download scope."""
    settings = get_settings()
    normalized = str(provider or "").strip().lower()
    if normalized not in {"p115", "quark"}:
        return False, ""
    if not settings.provider_cloud_download_organizer_enabled(normalized):
        return False, ""
    trigger_enabled = getattr(settings, "cloud_download_organizer_trigger_enabled", None)
    if callable(trigger_enabled) and not trigger_enabled("event") and not explicit_request:
        try:
            from app.services.cloud_download_organizer import _authorized_scope_for_candidate
            from app.services.paths import normalize_save_root

            authorized_scope = _authorized_scope_for_candidate(
                settings,
                normalized,
                normalize_save_root(target_path),
            )
        except (RuntimeError, ValueError):
            return False, ""
        if not authorized_scope:
            return False, ""
        return True, "已纳入定时云下载整理，本次不生成云下载原始文件的 STRM"
    exact_files = tuple(dict(item) for item in target_files if isinstance(item, Mapping))
    try:
        from app.services.cloud_download_organizer import run_targeted_cloud_download_organizer

        result = run_targeted_cloud_download_organizer(
            normalized,
            target_path,
            expected_file_ids=[str(item.get("file_id") or "").strip() for item in exact_files if str(item.get("file_id") or "").strip()],
            expected_names=[str(item.get("file_name") or item.get("name") or "").strip() for item in exact_files if str(item.get("file_name") or item.get("name") or "").strip()],
            media_title=media_title,
            media_year=media_year,
            explicit_request=explicit_request,
        )
    except Exception as exc:
        return True, f"定点云下载整理未完成（{type(exc).__name__}），未回退扫描"
    if not result.get("accepted"):
        return False, ""
    outcome = str(result.get("outcome") or "")
    return True, {
        "organized": "已完成定点整理、STRM 生成和入库通知",
        "review": "定点整理需要人工复核，未扫描其他目录",
        "waiting": "定点整理已受理，等待精确任务继续处理",
        "failed": "定点整理失败，未扫描其他目录",
    }.get(outcome, "定点整理已处理，未扫描其他目录")


def run_post_transfer_pipeline(
    job_id: int,
    *,
    provider: str,
    title: str,
    poster_url: str = "",
    openlist_message: str = "",
    target_path: str = "",
    target_files: Iterable[Mapping[str, Any]] = (),
) -> None:
    """Run post-transfer work only for provider objects proven by this job."""
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

    exact_files = tuple(dict(item) for item in target_files if isinstance(item, Mapping))
    if not target_path or not exact_files:
        update_media_workflow_step(job_id, "strm_generate", "failed", "前序转存未提供可核验的精确目标，已拒绝回退为目录扫描")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 未生成，未通知 Emby")
        return

    try:
        update_media_workflow_step(job_id, "strm_generate", "running", "正在核验本次转存的精确目标并生成 STRM")
        targeted = index_and_reconcile_targeted_strm(
            provider=normalized_provider,
            target_path=target_path,
            target_files=exact_files,
            source_transfer_id=job_id,
            settings=settings,
        )
        result = targeted.reconcile
        summary = (
            f"已定点核验 {targeted.indexed} 个文件；新增 {result.created}，更新 {result.replaced}，"
            f"保持 {result.unchanged}，过滤 {result.filtered}，冲突 {result.conflicts}，未扫描其他目录"
        )
        if result.conflicts:
            update_media_workflow_step(job_id, "strm_generate", "failed", f"{summary}；存在 STRM 路径冲突")
            update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 校正存在冲突，未通知 Emby")
            update_media_workflow_step(job_id, "library_notification", "skipped", "STRM 未完成，未创建入库通知")
            return
        if not (result.created or result.replaced or result.unchanged):
            reason = "目标均被过滤" if result.filtered else "未产生可生成的 STRM 结果"
            update_media_workflow_step(job_id, "strm_generate", "skipped", f"{summary}；{reason}")
            update_media_workflow_step(job_id, "emby_refresh", "skipped", "没有 STRM 变化，未通知 Emby")
            update_media_workflow_step(job_id, "library_notification", "skipped", "没有新的入库内容")
            return
        update_media_workflow_step(
            job_id,
            "strm_generate",
            "done",
            summary,
        )
    except Exception as exc:
        update_media_workflow_step(job_id, "strm_generate", "failed", f"STRM 自动生成失败（{type(exc).__name__}）")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 未完成，未通知 Emby")
        return

    if not (result.created or result.replaced):
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 内容无变化，未通知 Emby")
        update_media_workflow_step(job_id, "library_notification", "skipped", "没有新的入库内容")
        return

    if settings.emby_library_refresh_enabled:
        try:
            update_media_workflow_step(job_id, "emby_refresh", "running", "正在通知 Emby 刷新媒体库")
            emby_message = refresh_emby_library_after_strm(settings.strm_output_root)
            update_media_workflow_step(job_id, "emby_refresh", "done", emby_message or "Emby 媒体库刷新已提交")
        except Exception as exc:
            update_media_workflow_step(job_id, "emby_refresh", "failed", f"Emby 入库通知失败（{type(exc).__name__}）")
            return
    else:
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "未启用 Emby 自动入库")
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
