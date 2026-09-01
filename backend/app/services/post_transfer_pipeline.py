from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.core.config import get_settings
from app.services.emby_library_refresh import refresh_emby_library_after_strm
from app.services.media_workflow import update_media_workflow_step
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
    defer_library_notification: bool = False,
) -> bool:
    """Continue one confirmed native transfer and report whether its chain succeeded."""
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
        update_media_workflow_step(job_id, "library_notification", "skipped", "前序流程未完成，未发送入库通知")
        return False
    organizer_handled, organizer_message = try_targeted_cloud_download_organization(
        provider=normalized_provider,
        target_path=save_path,
        target_files=exact_outputs,
        media_title=title,
        media_year=media_year,
    )
    if not organizer_handled and staging_requested:
        update_media_workflow_step(job_id, "strm_generate", "skipped", "云下载原始文件等待整理，不生成 STRM")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "等待云下载整理完成后再通知媒体库")
        update_media_workflow_step(job_id, "library_notification", "skipped", "等待云下载整理链路统一通知")
    elif not organizer_handled:
        return run_post_transfer_pipeline(
            int(job_id),
            provider=normalized_provider,
            title=title,
            poster_url=poster_url,
            target_path=save_path,
            target_files=exact_outputs,
            defer_library_notification=defer_library_notification,
        )
    else:
        delegated_message = organizer_message or "已由云下载整理流程接管"
        update_media_workflow_step(job_id, "strm_generate", "skipped", delegated_message)
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "由云下载整理流程负责后续入库")
        update_media_workflow_step(job_id, "library_notification", "skipped", "由云下载整理流程统一通知")
        return not any(marker in delegated_message for marker in ("失败", "复核"))
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
        label = "115" if normalized == "p115" else "夸克"
        return False, f"{label}云下载整理未启用，本次只完成云下载暂存，未启动标准整理和 115/OpenList 补齐"
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
            return False, "当前云下载目标不在已授权的整理范围，未启动标准整理"
        if not authorized_scope:
            return False, "当前云下载目标与正式媒体库映射无效或未授权，未启动标准整理"
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
        reason = str(result.get("reason") or "")
        return False, {
            "disabled": "云下载整理未启用，未启动标准整理和 115/OpenList 补齐",
            "event_trigger_disabled": "未启用前序动作事件，本次暂存内容等待定时整理",
            "outside_selected_scope": "当前云下载目标不在已授权的整理范围，未启动标准整理",
        }.get(reason, "云下载整理未接管本次暂存结果")
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
    defer_library_notification: bool = False,
) -> bool:
    """Run post-transfer work only for provider objects proven by this job."""
    settings = get_settings()
    if settings.openlist_enabled and settings.openlist_auto_sync:
        if "未完成" in openlist_message or "失败" in openlist_message:
            openlist_status = "failed"
        elif "等待同批" in openlist_message:
            openlist_status = "pending"
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
        update_media_workflow_step(job_id, "library_notification", "skipped", "当前网盘在转存完成后结束流程")
        return True

    exact_files = tuple(dict(item) for item in target_files if isinstance(item, Mapping))
    if not target_path or not exact_files:
        update_media_workflow_step(job_id, "strm_generate", "failed", "前序转存未提供可核验的精确目标，已拒绝回退为目录扫描")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 未生成，未通知 Emby")
        update_media_workflow_step(job_id, "library_notification", "skipped", "STRM 未完成，未创建入库通知")
        return False

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
            return False
        if not (result.created or result.replaced or result.unchanged):
            reason = "目标均被过滤" if result.filtered else "未产生可生成的 STRM 结果"
            update_media_workflow_step(job_id, "strm_generate", "skipped", f"{summary}；{reason}")
            update_media_workflow_step(job_id, "emby_refresh", "skipped", "没有 STRM 变化，未通知 Emby")
            update_media_workflow_step(job_id, "library_notification", "skipped", "没有新的入库内容")
            return True
        update_media_workflow_step(
            job_id,
            "strm_generate",
            "done",
            summary,
        )
    except Exception as exc:
        update_media_workflow_step(job_id, "strm_generate", "failed", f"STRM 自动生成失败（{type(exc).__name__}）")
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 未完成，未通知 Emby")
        update_media_workflow_step(job_id, "library_notification", "skipped", "STRM 未完成，未创建入库通知")
        return False

    if not (result.created or result.replaced):
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 内容无变化，未通知 Emby")
        update_media_workflow_step(job_id, "library_notification", "skipped", "没有新的入库内容")
        return True

    if settings.emby_library_refresh_enabled:
        try:
            update_media_workflow_step(job_id, "emby_refresh", "running", "正在通知 Emby 刷新媒体库")
            emby_message = refresh_emby_library_after_strm(settings.strm_output_root)
            update_media_workflow_step(job_id, "emby_refresh", "done", emby_message or "Emby 媒体库刷新已提交")
        except Exception as exc:
            update_media_workflow_step(job_id, "emby_refresh", "failed", f"Emby 入库通知失败（{type(exc).__name__}）")
            update_media_workflow_step(job_id, "library_notification", "skipped", "Emby 入库未完成，未发送入库通知")
            return False
    else:
        update_media_workflow_step(job_id, "emby_refresh", "skipped", "未启用 Emby 自动入库")
        update_media_workflow_step(job_id, "library_notification", "skipped", "未请求 Emby 刷新，等待实际入库 Webhook 后再通知")
        return True
    if defer_library_notification:
        update_media_workflow_step(
            job_id,
            "library_notification",
            "running",
            "等待 Emby 入库 Webhook；连续剧集确认后合并通知",
        )
        return True
    update_media_workflow_step(
        job_id,
        "library_notification",
        "running",
        "已请求 Emby 刷新，等待入库 Webhook 确认后通知",
    )
    return True
