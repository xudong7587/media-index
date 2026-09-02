from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from app.clients.pansou import infer_share_provider
from app.clients.p115 import P115Client, P115CloudDownloadResult, P115Error
from app.clients.openlist import OpenListClient, OpenListError
from app.clients.qas import QasClient
from app.clients.quark import QuarkClient, QuarkError
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.db.database import db
from app.domain.media import LinkResolution, MediaTarget, RenamePair, SourceFile
from app.providers.base import TransferPlan
from app.providers.p115 import P115TransferProvider
from app.providers.quark import QuarkTransferProvider
from app.providers.cloud_download_organizer import QuarkOrganizerProvider
from app.services.notifications import add_notification
from app.services.cloud_download_targets import list_cloud_download_targets
from app.services.qas_executor import qas_trigger_accepted
from app.services.share_inspector import inspect_share
from app.services.p115_completion import complete_quark_to_p115
from app.services.episode_matcher import VIDEO_EXTENSIONS, quality_score, sanitize_filename_component
from app.services.movie_matcher import build_movie_rename_pair
from app.services.media_workflow import (
    complete_transfer_workflow_step,
    initialize_media_workflow,
    update_media_workflow_step,
)
from app.services.paths import (
    build_save_path,
    cloud_download_child_name,
    cloud_download_direct_child_scope,
    is_allowed_save_path,
    normalize_cloud_root,
    normalize_save_root,
)
from app.services.post_transfer_pipeline import run_post_transfer_pipeline, try_targeted_cloud_download_organization


_LINK_RE = re.compile(r"(magnet:\?xt=[^\s]+|ed2k://[^\s]+|https?://[^\s]+)", re.IGNORECASE)
_OFFLINE_SCHEMES = {"magnet", "ed2k"}
_p115_cloud_download_workers: set[int] = set()
_p115_cloud_download_workers_lock = threading.Lock()


@dataclass(frozen=True)
class DirectLinkResult:
    ok: bool
    job_id: int | None
    message: str
    unsupported: bool = False


class DirectLinkTransferPartial(RuntimeError):
    """A provider write was accepted but its final read receipt is unavailable."""


@dataclass(frozen=True)
class DirectTargetProbe:
    state: str
    path: str = ""
    message: str = ""


@dataclass(frozen=True)
class DirectLinkTargetOption:
    provider: str
    path: str
    label: str
    category: str = ""


@dataclass(frozen=True)
class DirectLinkRequest:
    link: str
    provider: str
    root_path: str
    options: tuple[DirectLinkTargetOption, ...]
    title: str = ""
    year: str = ""
    category: str = "movie"


@dataclass(frozen=True)
class DirectLinkRenamePreview:
    link: str
    provider: str
    save_path: str
    title: str
    year: str
    category: str
    pairs: tuple[RenamePair, ...]


def extract_download_link(text: str) -> str:
    links = extract_download_links(text)
    return links[0] if links else ""


def extract_download_links(text: str, *, limit: int = 20) -> tuple[str, ...]:
    """Extract bounded, de-duplicated links without persisting surrounding text."""
    values: list[str] = []
    seen: set[str] = set()
    for match in _LINK_RE.finditer(str(text or "")):
        value = match.group(1).strip().rstrip("，。；、,.!！？）)")
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        values.append(value)
        if len(values) >= max(1, min(int(limit), 100)):
            break
    return tuple(values)


def looks_like_download_link(text: str) -> bool:
    return bool(extract_download_link(text))


def resolve_direct_link_resource_name(command: str, provider: str) -> str:
    """Best-effort display name for an interaction prompt."""
    raw = str(command or "").strip()
    link = extract_download_link(raw)
    if not link:
        return ""
    parsed = urlsplit(link)
    candidate = ""
    if parsed.scheme.lower() == "magnet":
        candidate = str((parse_qs(parsed.query).get("dn") or [""])[0])
    elif parsed.scheme.lower() == "ed2k":
        parts = link.split("|")
        if len(parts) > 2 and parts[1].casefold() == "file":
            candidate = unquote(parts[2])
    candidate = candidate or re.sub(
        r"^(?:转存|下载|保存|链接)\s*[：:]?\s*",
        "",
        raw.replace(link, " "),
    )
    if candidate.strip():
        return re.sub(r"\s+", " ", candidate).strip(" .\t\r\n")[:160]
    try:
        if provider == "p115":
            client = P115Client()
            if not client.configured():
                return ""
            snapshot = client.inspect_share(link)
            paths = [str(item.path or item.name).strip("/") for item in snapshot.files if item.name]
            if paths:
                first = paths[0].split("/", 1)[0]
                return first[:160] if all(path == first or path.startswith(f"{first}/") for path in paths) else paths[0].rsplit(".", 1)[0][:160]
        if provider == "quark":
            client = QuarkClient()
            if not client.configured():
                return ""
            return str(client.inspect_share(link).title or "").strip()[:160]
    except (P115Error, QuarkError, ValueError):
        pass
    return ""


def prepare_direct_link_request(
    command: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
    include_target_options: bool = True,
) -> DirectLinkRequest:
    link, provider = _resolve_direct_link_provider(command)
    normalized_title = title.strip()
    normalized_year = _resolve_direct_year(normalized_title, year, category)
    # Link transfers always stage in the configured cloud-download root.  A
    # supplied title/year is an identity hint for the organizer, not authority
    # to bypass staging and write into the formal media library.
    root_path = _direct_save_path(provider)
    _validate_provider_path(provider, root_path)

    return DirectLinkRequest(
        link=link,
        provider=provider,
        root_path=root_path,
        options=_direct_target_options(provider, root_path) if include_target_options else (),
        title=normalized_title,
        year=normalized_year,
        category=_direct_media_type(category),
    )


def prepare_direct_library_request(
    command: str,
    *,
    title: str,
    year: str = "",
    category: str = "movie",
) -> DirectLinkRequest:
    """Build one canonical formal-library destination without creating it."""
    normalized_title = str(title or "").strip()
    if not normalized_title:
        raise ValueError("直接入正式媒体库前请填写媒体名称")
    link, provider = _resolve_direct_link_provider(command)
    _cloud_type, inferred_provider = infer_share_provider(link)
    if inferred_provider not in {"p115", "quark"}:
        raise ValueError("直接入正式媒体库只支持可识别的 115 或夸克分享链接")
    media_type = _direct_media_type(category)
    normalized_year = _resolve_direct_year(normalized_title, year, media_type)
    root_path = _direct_media_save_path(provider, normalized_title, normalized_year, media_type)
    if not is_allowed_save_path(media_type, root_path, target="cloud", provider=provider):
        raise ValueError("MediaIndex 生成的正式媒体库路径超出允许的保存范围")
    return DirectLinkRequest(
        link=link,
        provider=provider,
        root_path=root_path,
        options=(),
        title=normalized_title,
        year=normalized_year,
        category=media_type,
    )


def preview_direct_link_rename(
    command: str,
    *,
    title: str,
    year: str = "",
    category: str = "movie",
) -> DirectLinkRenamePreview:
    """Inspect a share and return exact default names without side effects."""
    request = prepare_direct_library_request(command, title=title, year=year, category=category)
    if request.provider == "p115":
        provider = P115TransferProvider(P115Client())
        unavailable = "115 Cookie 未配置"
        provider_reason = "native_p115"
    else:
        provider = QuarkTransferProvider(QuarkClient())
        unavailable = "夸克 Cookie 未配置或已失效"
        provider_reason = "native_quark"
    if not provider.configured():
        raise ValueError(unavailable)
    inspection = provider.inspect_share(request.link)
    sources = [item for item in inspection.files if item.name] if inspection.valid else []
    if not sources:
        raise ValueError(inspection.error or "分享链接内没有可生成命名预览的文件")
    pairs = _direct_link_rename_pairs(
        sources,
        request.title,
        request.year,
        request.category,
        provider_reason=provider_reason,
    )
    return DirectLinkRenamePreview(
        request.link,
        request.provider,
        request.root_path,
        request.title,
        request.year,
        request.category,
        pairs,
    )


def _resolve_direct_link_provider(command: str) -> tuple[str, str]:
    settings = get_settings()
    link = extract_download_link(command)
    if not link:
        raise ValueError("没有识别到下载链接")
    provider = settings.direct_download_provider.strip().lower() or settings.default_provider_key()
    if provider == "qas":
        provider = "quark"
    if provider not in {"quark", "p115"}:
        provider = "p115"
    _cloud_type, inferred_provider = infer_share_provider(link)
    if inferred_provider:
        provider = inferred_provider
    elif urlsplit(link).scheme.lower() in {*_OFFLINE_SCHEMES, "http", "https"}:
        provider = "p115"
    return link, provider


def handle_direct_link_transfer(
    command: str,
    from_user: str = "",
    save_path: str = "",
    request_source: str = "wecom",
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
    staging_name: str = "",
    preserve_save_path: bool = False,
    match_rename: bool = True,
    apply_rename_plan: bool = False,
    destination_mode: str = "cloud_download",
) -> DirectLinkResult:
    library_mode = destination_mode == "library"
    try:
        request = (
            prepare_direct_library_request(command, title=title, year=year, category=category)
            if library_mode
            else prepare_direct_link_request(
                command,
                title=title,
                year=year,
                category=category,
                include_target_options=False,
            )
        )
    except ValueError as exc:
        return DirectLinkResult(False, None, str(exc))
    link = request.link
    provider = request.provider
    title = request.title or title.strip()
    year = request.year or year.strip()
    category = request.category
    raw_media_hint = staging_name.strip()
    save_path = request.root_path if library_mode else (save_path.strip() or request.root_path)
    selected_cloud_scope = save_path
    if library_mode:
        if not is_allowed_save_path(category, save_path, target="cloud", provider=provider):
            return DirectLinkResult(False, None, "MediaIndex 生成的正式媒体库路径超出允许的保存范围")
    else:
        try:
            _validate_provider_path(provider, selected_cloud_scope, require_child=preserve_save_path)
        except ValueError as exc:
            return DirectLinkResult(False, None, str(exc))
        save_path = _direct_staging_media_path(
            selected_cloud_scope,
            link=link,
            title=title or staging_name,
            year=year if title else "",
        )
    parsed = urlsplit(link)
    if parsed.scheme.lower() in _OFFLINE_SCHEMES:
        if provider == "p115":
            job_id, duplicate = _create_direct_job(
                link,
                provider,
                save_path,
                from_user,
                request_source,
                title=title,
                year=year,
                category=category,
            )
            if duplicate:
                status = _direct_job_status(job_id)
                message = (
                    "相同下载链接已完成，未重复提交 115 离线下载"
                    if status == "done"
                    else "相同下载链接任务已在运行，未重复触发"
                )
                return DirectLinkResult(True, job_id, message)
            try:
                return _finish_p115_cloud_download_job(
                    job_id,
                    _transfer_p115_cloud_download(link, save_path),
                    save_path,
                    title=title,
                    year=year,
                )
            except Exception as exc:
                message = _offline_failure_message(exc)
                _finish_job(job_id, "failed", "provider_failed", message)
                _add_direct_notification(job_id, "failed", "provider_failed", "error", "115 离线下载失败", message)
                return DirectLinkResult(False, job_id, message)
        return DirectLinkResult(False, None, "磁力/电驴链接目前只支持关联网盘选择 115 后提交离线下载", True)

    _cloud_type, inferred_provider = infer_share_provider(link)
    if inferred_provider and inferred_provider != provider:
        provider = inferred_provider
        if library_mode:
            save_path = _direct_media_save_path(provider, title, year, category)
            if not is_allowed_save_path(category, save_path, target="cloud", provider=provider):
                return DirectLinkResult(False, None, "MediaIndex 生成的正式媒体库路径超出允许的保存范围")
        else:
            selected_cloud_scope = selected_cloud_scope if preserve_save_path else _direct_save_path(provider)
            try:
                _validate_provider_path(provider, selected_cloud_scope, require_child=preserve_save_path)
            except ValueError as exc:
                return DirectLinkResult(False, None, str(exc))
            save_path = _direct_staging_media_path(
                selected_cloud_scope,
                link=link,
                title=title or staging_name,
                year=year if title else "",
            )
    if not inferred_provider:
        if provider == "p115":
            job_id, duplicate = _create_direct_job(
                link,
                provider,
                save_path,
                from_user,
                request_source,
                title=title,
                year=year,
                category=category,
            )
            if duplicate:
                return DirectLinkResult(True, job_id, "相同下载链接任务已在运行，未重复触发")
            try:
                return _finish_p115_cloud_download_job(
                    job_id,
                    _transfer_p115_cloud_download(link, save_path),
                    save_path,
                    title=title,
                    year=year,
                )
            except Exception as exc:
                message = _offline_failure_message(exc)
                _finish_job(job_id, "failed", "provider_failed", message)
                _add_direct_notification(job_id, "failed", "provider_failed", "error", "115 离线下载失败", message)
                return DirectLinkResult(False, job_id, message)
        return DirectLinkResult(False, None, "普通 HTTP 下载链接目前只支持关联网盘选择 115 后提交离线下载", True)

    job_id, duplicate = _create_direct_job(
        link,
        provider,
        save_path,
        from_user,
        request_source,
        title=title,
        year=year,
        category=category,
    )
    if duplicate:
        if _direct_job_status(job_id) == "done":
            organizer_path = _direct_organizer_resume_path(provider, save_path, title, year) or save_path
            formal_path = _direct_organizer_formal_path(provider, organizer_path)
            probe = _probe_completed_direct_target(provider, (organizer_path, save_path, formal_path))
            if probe.state == "unknown":
                return DirectLinkResult(
                    False,
                    job_id,
                    f"历史转存记录存在，但当前网盘内容实时核验失败：{probe.message}；未重复提交",
                )
            if probe.state == "missing":
                job_id, duplicate = _create_direct_job(
                    link,
                    provider,
                    save_path,
                    from_user,
                    request_source,
                    title=title,
                    year=year,
                    category=category,
                    reuse_completed=False,
                )
                if duplicate:
                    return DirectLinkResult(True, job_id, "相同下载链接任务已在运行，未重复触发")
            else:
                message = f"已实时确认网盘媒体文件仍存在于 {probe.path}，未重复提交转存"
                if not library_mode and match_rename:
                    organizer_path = organizer_path or probe.path
                    organizer_message = _trigger_targeted_cloud_organizer(
                        job_id,
                        provider,
                        organizer_path,
                        [],
                        title=title,
                        year=year,
                        media_query_hint=raw_media_hint,
                    )
                    if organizer_message:
                        message = f"{message}；{organizer_message}"
                return DirectLinkResult(True, job_id, message)
        else:
            return DirectLinkResult(True, job_id, "相同下载链接任务已在运行，未重复触发")
    if library_mode:
        initialize_media_workflow(job_id)
        complete_transfer_workflow_step(job_id, "running", "provider_submitting", "正在转存到正式媒体库")
    try:
        exact_outputs: tuple[dict, ...] = ()
        if provider == "p115":
            count, filenames, exact_outputs = _transfer_p115_share_with_outputs(
                link,
                save_path,
                title=title,
                year=year,
                category=category,
            )
            sync_message = ""
            message = f"转存已执行：115 分享链接已转存到 {save_path}，共 {count} 个文件"
            if sync_message:
                message = f"{message}；{sync_message}"
        elif provider == "quark":
            # The cloud-download organizer is the sole owner of media file
            # naming and season layout.  At this stage Quark only receives the
            # TMDB-verified media folder, avoiding a second competing rename
            # implementation before the complete episode set is available.
            transfer_title = title if library_mode else ""
            transfer_year = year if library_mode else ""
            count, filenames, exact_outputs = _transfer_quark_share_with_files(
                link,
                save_path,
                title=transfer_title,
                year=transfer_year,
                category=category,
            )
            # Cloud-download targets are not valid OpenList sources yet.  The
            # organizer owns that hand-off after standard naming/folder landing.
            sync_message = ""
            action = "验真、改名、转存和正式媒体库目标确认" if library_mode else "验真、转存和云下载目录确认"
            message = f"转存已执行：原生夸克已完成{action}，共 {count} 个文件"
            if sync_message:
                message = f"{message}；{sync_message}"
        else:
            raise RuntimeError("新任务只支持原生夸克或原生 115")
        if library_mode:
            message = f"{message}；已交给正式媒体库的 STRM 与 Emby 后续处理"
            try:
                run_post_transfer_pipeline(
                    job_id,
                    provider=provider,
                    title=title,
                    openlist_message=sync_message,
                    target_path=save_path,
                    target_files=exact_outputs,
                )
            except Exception as exc:
                update_media_workflow_step(job_id, "strm_generate", "failed", f"正式媒体库后处理异常（{type(exc).__name__}）")
                update_media_workflow_step(job_id, "emby_refresh", "skipped", "STRM 后处理异常，未通知 Emby")
                update_media_workflow_step(job_id, "library_notification", "skipped", "正式媒体库后处理异常，未发送入库通知")
            if provider == "quark":
                sync_message = _direct_openlist_sync_message(
                    provider,
                    save_path,
                    filenames,
                    job_id=job_id,
                    category=category,
                    title=title,
                    year=year,
                )
                if sync_message:
                    update_media_workflow_step(job_id, "openlist_sync", _direct_openlist_workflow_status(sync_message), sync_message)
                    message = f"{message}；{sync_message}"
            _finish_job(job_id, "done", "provider_completed", message)
            complete_transfer_workflow_step(job_id, "done", "provider_completed", message)
            _add_direct_notification(job_id, "done", "provider_completed", "success", "下载链接转存完成", message)
            return DirectLinkResult(True, job_id, message)
        if match_rename:
            organizer_message = _trigger_targeted_cloud_organizer(
                job_id,
                provider,
                save_path,
                filenames,
                exact_files=exact_outputs or None,
                title=title,
                year=year,
                media_query_hint=raw_media_hint,
            )
            if organizer_message:
                message = f"{message}；{organizer_message}"
            if provider == "quark" and organizer_message:
                message = f"{message}；115 补齐未提前触发，只会在标准命名、建目录和目标核验完成后由整理任务触发"
        elif apply_rename_plan and title.strip():
            message = f"{message}；已按预览命名转存，未触发云下载整理、STRM 或 Emby 入库"
        else:
            message = f"{message}；未触发云下载整理、STRM 或 Emby 入库"
        _finish_job(job_id, "done", "provider_completed", message)
        _add_direct_notification(job_id, "done", "provider_completed", "success", "下载链接转存完成", message)
        return DirectLinkResult(True, job_id, message)
    except Exception as exc:
        partial = isinstance(exc, DirectLinkTransferPartial)
        message = (
            f"下载链接转存已提交但确认中断：{_user_error_message(exc)}"
            if partial
            else f"下载链接转存失败：{_user_error_message(exc)}"
        )
        failure_stage = "provider_partial" if partial else "provider_failed"
        _finish_job(job_id, "failed", failure_stage, message)
        if library_mode:
            complete_transfer_workflow_step(job_id, "failed", failure_stage, message)
        _add_direct_notification(
            job_id,
            "failed",
            failure_stage,
            "error",
            "下载链接转存待核对" if partial else "下载链接转存失败",
            message,
        )
        return DirectLinkResult(False, job_id, message)


def _direct_save_path(provider: str) -> str:
    settings = get_settings()
    resolver = getattr(settings, "provider_cloud_download_path", None)
    if callable(resolver):
        return resolver(provider)
    return settings.provider_save_root(provider).rstrip("/") or "/"


def _direct_staging_media_path(
    selected_scope: str,
    *,
    link: str,
    title: str = "",
    year: str = "",
) -> str:
    """Create one deterministic media directory below the selected staging scope."""
    normalized_scope = normalize_save_root(selected_scope)
    normalized_title = sanitize_filename_component(str(title or "").strip()) if str(title or "").strip() else ""
    normalized_year = sanitize_filename_component(str(year or "").strip()) if str(year or "").strip() else ""
    if normalized_title:
        folder = normalized_title
        if normalized_year and normalized_year not in normalized_title:
            folder = f"{folder} ({normalized_year})"
    else:
        folder = f"链接-{sha256(str(link or '').encode('utf-8')).hexdigest()[:10]}"
    return normalize_save_root(f"{normalized_scope.rstrip('/')}/{folder[:180]}")


def _direct_media_type(category: str) -> str:
    value = str(category or "movie").strip().lower()
    return value if value in {"movie", "tv", "variety", "concert", "documentary", "anime"} else "movie"


def _direct_media_save_path(provider: str, title: str, year: str, category: str) -> str:
    media_type = _direct_media_type(category)
    episodic_types = {"tv", "variety", "anime"}
    season = 1 if get_settings().season_subdirectory_enabled and media_type in episodic_types else None
    return build_save_path(
        "cloud",
        media_type,
        title.strip(),
        year.strip(),
        season=season,
        provider=provider,
    )


def infer_direct_link_category(provider: str, child_name: str, *, fallback: str = "movie") -> str:
    """Infer a selected download child from saved category paths, then labels."""
    value = str(child_name or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].casefold()
    try:
        paths = get_settings().provider_category_paths(provider)
        matched = {
            _direct_media_type(category)
            for category, path in paths.items()
            if str(path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].casefold() == value
        }
        if len(matched) == 1:
            return matched.pop()
    except (AttributeError, TypeError, ValueError):
        pass
    for category, tokens in (
        ("variety", ("综艺", "variety")),
        ("concert", ("演唱会", "concert")),
        ("documentary", ("纪录", "documentary")),
        ("anime", ("动漫", "动画", "anime")),
        ("tv", ("电视剧", "剧集", "tv")),
    ):
        if any(token in value for token in tokens):
            return category
    return fallback


def _resolve_direct_year(title: str, year: str, category: str) -> str:
    explicit_year = str(year or "").strip()
    if explicit_year:
        return explicit_year
    if not str(title or "").strip():
        return ""

    try:
        client = TmdbClient()
        if not client.configured():
            return ""
        media_type = "movie" if _direct_media_type(category) in {"movie", "concert", "documentary"} else "tv"
        results = client.search(str(title).strip(), media_type=media_type).get("results") or []
    except Exception:
        return ""
    if not isinstance(results, list) or not results:
        return ""

    needle = _compact_direct_title(title)
    exact = next(
        (
            item
            for item in results
            if isinstance(item, dict)
            and needle
            and needle in {
                _compact_direct_title(item.get("title") or item.get("name")),
                _compact_direct_title(item.get("original_title") or item.get("original_name")),
            }
        ),
        None,
    )
    candidate = exact or next((item for item in results if isinstance(item, dict)), None)
    if not candidate:
        return ""
    release_date = str(candidate.get("release_date") or candidate.get("first_air_date") or "")
    candidate_year = str(candidate.get("year") or release_date[:4]).strip()
    return candidate_year if re.fullmatch(r"\d{4}", candidate_year) else ""


def _compact_direct_title(value: object) -> str:
    return re.sub(r"[\W_]+", "", str(value or ""), flags=re.UNICODE).casefold()


def _add_direct_notification(job_id: int, status: str, stage: str, notification_type: str, title: str, message: str) -> None:
    add_notification(
        f"transfer:{job_id}:{status}:{stage}",
        notification_type,
        title,
        message,
        "history",
        deliver=False,
    )


def _direct_target_options(
    provider: str,
    root_path: str,
    *,
    title: str = "",
    year: str = "",
) -> tuple[DirectLinkTargetOption, ...]:
    if provider in {"p115", "quark"}:
        targets = list_cloud_download_targets(provider)
        return tuple(
            DirectLinkTargetOption(
                provider,
                item.path,
                item.child_name,
                infer_direct_link_category(provider, item.child_name),
            )
            for item in targets
        )
    directories = _provider_child_directories(provider, root_path)
    if not directories:
        return ()
    return tuple(
        DirectLinkTargetOption(
            provider,
            f"{root_path.rstrip('/')}/{name}",
            name,
            infer_direct_link_category(provider, name),
        )
        for name in directories
    )


def _provider_child_directories(provider: str, root_path: str) -> list[str]:
    try:
        if provider == "p115":
            client = P115Client()
            cid = client.directory_id(root_path)
            if cid == "0" and root_path != "/":
                return _p115_openlist_child_directories(root_path)
            return sorted(item.name for item in client.list_directory(cid) if item.is_dir and item.name)
        if provider == "quark":
            client = QuarkClient()
            directory_id = client.directory_id(root_path)
            if not directory_id:
                return []
            return sorted(item.name for item in client.list_directory(directory_id) if item.is_dir and item.name)
        response = QasClient().savepath_detail(root_path)
        return sorted(_qas_directory_names(response))
    except (P115Error, QuarkError):
        if provider == "p115":
            return _p115_openlist_child_directories(root_path)
        return []
    except Exception:
        return []


def _p115_openlist_child_directories(root_path: str) -> list[str]:
    """Legacy bridge retained for compatibility; native 115 browsing is Cookie-only."""
    settings = get_settings()
    if not _can_submit_p115_download_via_openlist(settings):
        return []
    try:
        openlist = OpenListClient()
        return sorted(
            str(item.get("name") or "").strip()
            for item in openlist.list_directories(openlist.p115_storage_path(root_path))
            if str(item.get("name") or "").strip()
        )
    except OpenListError:
        return []


def _qas_directory_names(response: object) -> list[str]:
    payload = response.get("data", response) if isinstance(response, dict) else {}
    items = payload.get("list") or payload.get("files") or [] if isinstance(payload, dict) else []
    names: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file_name") or item.get("name") or "").strip()
        is_dir = bool(item.get("dir") or item.get("is_dir") or item.get("isdir"))
        if name and is_dir:
            names.append(name)
    return names


def _validate_provider_path(provider: str, path: str, *, require_child: bool = False) -> None:
    settings = get_settings()
    resolver = getattr(settings, "provider_cloud_download_path", None)
    root_value = resolver(provider) if callable(resolver) else settings.provider_save_root(provider)
    root = normalize_cloud_root(str(root_value or ""))
    normalized = normalize_cloud_root(path)
    if normalized == root and not require_child:
        return
    if cloud_download_direct_child_scope(provider, normalized, settings=settings):
        return
    if normalized == root or root == "/" or normalized.startswith(f"{root.rstrip('/')}/"):
        raise ValueError("下载链接目标必须是云下载路径的直属子文件夹")
    raise ValueError("下载链接目标必须位于已配置的云下载路径内")


def _create_direct_job(
    link: str,
    provider: str,
    save_path: str,
    from_user: str,
    request_source: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
    reuse_completed: bool = True,
) -> tuple[int, bool]:
    execution_key = _direct_execution_key(
        link,
        provider,
        save_path,
        title=title,
        year=year,
        category=category,
    )
    with db() as conn:
        reusable_statuses = "'running','ready','triggered','done'" if reuse_completed else "'running','ready','triggered'"
        existing = conn.execute(
            f"SELECT id FROM transfer_jobs WHERE execution_key=? AND status IN ({reusable_statuses}) ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if existing:
            return int(existing["id"]), True
        return int(
            conn.execute(
                """
                INSERT INTO transfer_jobs(
                    media_type,display_title,target,provider,status,stage,message,share_url,save_path,execution_key,request_source,request_user
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "direct",
                    title.strip() or "下载链接",
                    "cloud",
                    provider,
                    "running",
                    "provider_submitting",
                    f"正在处理来自 {from_user or '交互指令'} 的下载链接",
                    link,
                    save_path,
                    execution_key,
                    request_source if from_user else "",
                    from_user,
                ),
            ).lastrowid
        ), False


def _direct_job_status(job_id: int) -> str:
    with db() as conn:
        row = conn.execute(
            "SELECT status FROM transfer_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()
    return str(row["status"] or "") if row else ""


def _direct_organizer_resume_path(provider: str, save_path: str, title: str, year: str) -> str:
    """Find one exact unfinished organizer source for an already received link."""
    normalized_path = normalize_save_root(save_path)
    parent = normalize_save_root(normalized_path.rsplit("/", 1)[0])
    wanted_title = _compact_direct_title(title)
    wanted_year = str(year or "").strip()[:4]
    if not wanted_title:
        return ""
    with db() as conn:
        rows = conn.execute(
            """SELECT source_file,display_title,external_provider_status FROM transfer_jobs
               WHERE provider=? AND request_source='cloud_download_organizer'
                 AND status IN ('failed','needs_review','retry_wait','ready','running')
               ORDER BY id DESC LIMIT 50""",
            (str(provider or "").strip().lower(),),
        ).fetchall()
    matches: list[str] = []
    for row in rows:
        source = normalize_save_root(str(row["source_file"] or ""))
        if not source or normalize_save_root(source.rsplit("/", 1)[0]) != parent:
            continue
        try:
            state = json.loads(str(row["external_provider_status"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            state = {}
        identity = state.get("confirmed_identity") if isinstance(state, dict) else {}
        identity = identity if isinstance(identity, dict) else {}
        candidate_title = str(identity.get("title") or row["display_title"] or "").strip()
        candidate_year = str(identity.get("year") or "").strip()[:4]
        if _compact_direct_title(candidate_title) != wanted_title:
            continue
        if wanted_year and candidate_year and candidate_year != wanted_year:
            continue
        if source not in matches:
            matches.append(source)
    return matches[0] if len(matches) == 1 else ""


def _direct_organizer_formal_path(provider: str, source_path: str) -> str:
    if not source_path:
        return ""
    with db() as conn:
        rows = conn.execute(
            """SELECT save_path FROM transfer_jobs
               WHERE provider=? AND request_source='cloud_download_organizer' AND source_file=?
               ORDER BY id DESC LIMIT 2""",
            (str(provider or "").strip().lower(), normalize_save_root(source_path)),
        ).fetchall()
    values = [normalize_save_root(str(row["save_path"] or "")) for row in rows if str(row["save_path"] or "").strip()]
    return values[0] if values and len(set(values)) == 1 else ""


def _probe_completed_direct_target(provider: str, paths: tuple[str, ...]) -> DirectTargetProbe:
    """Verify current provider state before trusting a historical done row."""
    if provider != "quark":
        return DirectTargetProbe("unknown", message="当前网盘不支持历史转存实时核验")
    adapter = QuarkOrganizerProvider(QuarkClient())
    checked: set[str] = set()
    try:
        for raw_path in paths:
            if not str(raw_path or "").strip():
                continue
            path = normalize_save_root(raw_path)
            if path in checked:
                continue
            checked.add(path)
            directory_id = adapter.directory_id(path)
            if directory_id and _remote_directory_contains_video(adapter, directory_id):
                return DirectTargetProbe("present", path=path)
    except QuarkError as exc:
        return DirectTargetProbe("unknown", message=str(exc))
    return DirectTargetProbe("missing")


def _remote_directory_contains_video(adapter: QuarkOrganizerProvider, root_id: str) -> bool:
    pending = [root_id]
    seen: set[str] = set()
    inspected = 0
    while pending and inspected < 500:
        directory_id = pending.pop(0)
        if directory_id in seen:
            continue
        seen.add(directory_id)
        entries = adapter.list_directory(directory_id)
        inspected += len(entries)
        for entry in entries:
            if entry.is_dir:
                pending.append(entry.file_id)
                continue
            suffix = "." + entry.name.rsplit(".", 1)[-1].casefold() if "." in entry.name else ""
            if suffix in VIDEO_EXTENSIONS:
                return True
    return False


def _direct_execution_key(
    link: str,
    provider: str,
    save_path: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
) -> str:
    identity = f"{provider}\n{save_path}\n{link}"
    normalized_title = re.sub(r"\s+", " ", str(title or "")).strip().casefold()
    if normalized_title:
        identity += f"\nrename\n{normalized_title}\n{str(year or '').strip()}\n{_direct_media_type(category)}"
    digest = sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"direct:{digest}"


def _finish_job(job_id: int, status: str, stage: str, message: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE transfer_jobs SET status=?,stage=?,message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, stage, message[:1000], job_id),
        )


def _mark_direct_qas_triggered(
    job_id: int,
    filenames: list[str],
    message: str,
    *,
    expected_count: int = 0,
) -> None:
    expected = [
        {"replacement": name}
        for name in dict.fromkeys(str(filename or "").strip() for filename in filenames)
        if name
    ]
    if not expected and expected_count > 0:
        expected = [{"expected_count": int(expected_count)}]
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs
            SET status='triggered',stage='qas_triggered',message=?,rename_pairs_json=?,finished_at=NULL
            WHERE id=?
            """,
            (message[:1000], json.dumps(expected, ensure_ascii=False), job_id),
        )


def _transfer_qas_share(link: str, save_path: str) -> int:
    count, _filenames = _transfer_qas_share_with_files(link, save_path)
    return count


def _transfer_quark_share_with_files(
    link: str,
    save_path: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
) -> tuple[int, list[str], tuple[dict, ...]]:
    """Complete one direct-link transfer through the native Quark provider."""
    client = QuarkClient()
    provider = QuarkTransferProvider(client)
    if not provider.configured():
        raise QuarkError("夸克 Cookie 未配置或已失效")
    inspection = provider.inspect_share(link)
    sources = [item for item in inspection.files if item.name] if inspection.valid else []
    if not sources:
        raise QuarkError(inspection.error or "夸克分享链接内没有可转存文件")

    media_type = _direct_media_type(category)
    selected = sources
    replacements = _direct_identity_hint_replacements(
        sources,
        title,
        year,
        category,
        provider_reason="native_quark",
    )

    pairs = tuple(
        RenamePair(
            source_name=source.name,
            pattern=f"^{re.escape(source.name)}$",
            replacement=replacement,
            confidence="high",
            reasons=("direct_link", "native_quark"),
            source_id=source.provider_file_id,
            source_path=source.path,
            source_size=source.size,
        )
        for source, replacement in zip(selected, replacements, strict=True)
    )
    target = MediaTarget(
        tmdb_id=0,
        media_type=media_type,
        title=title.strip() or "下载链接",
        category=media_type,
        series_year=year.strip(),
    )
    child_name = _cloud_download_child_for_target("quark", save_path)
    result = provider.execute(
        TransferPlan(
            target,
            LinkResolution(True, "ready", "原生夸克分享已验真", share_url=inspection.share_url or link, rename_pairs=pairs),
            save_path,
            destination_scope="cloud_download" if child_name else "",
            cloud_download_child=child_name,
        )
    )
    if not result.ok or not result.confirmed:
        message = result.message or "原生夸克转存未完成目标确认"
        if result.stage == "provider_partial":
            raise DirectLinkTransferPartial(message)
        raise QuarkError(message)
    outputs = tuple(dict(item) for item in result.outputs)
    return result.executed_items, [str(item.get("file_name") or "") for item in outputs], outputs


def _transfer_qas_share_with_files(
    link: str,
    save_path: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
) -> tuple[int, list[str]]:
    client = QasClient()
    if not client.configured():
        raise RuntimeError("QAS 未配置")
    inspection = inspect_share(client, link)
    sources = [item for item in inspection.files if item.name] if inspection.valid else []
    files = [item.name for item in sources]
    if not files:
        raise RuntimeError(inspection.error or "分享链接内没有可转存文件")
    task_base = {
        "taskname": ".".join(
            part
            for part in (
                sanitize_filename_component(title) if title.strip() else "下载链接",
                sanitize_filename_component(year) if year.strip() else "",
            )
            if part
        ),
        "shareurl": inspection.share_url or link,
        "savepath": save_path,
        "extract_code": "",
        "runweek": [time.localtime().tm_wday + 1],
    }
    if _direct_media_type(category) == "movie" and title.strip() and len(files) == 1 and _is_video_file(files[0]):
        return _run_direct_movie_task(client, task_base, sources[0], title, year)
        if False:  # legacy branch retained only for source compatibility
            pass
            raise RuntimeError("QAS 未接受直接链接重命名任务")
    if _direct_media_type(category) == "movie":
        selected = _select_direct_movie_source(sources)
        if selected is None:
            raise RuntimeError("no movie video file in share")
        return _run_direct_movie_task(client, task_base, selected, title, year)
    if _can_use_tv_pro(files, title, category):
        task = dict(task_base)
        task["pattern"] = "$TV_PRO"
        task["replace"] = "{TASKNAME}.{SXX}E{E}.{EXT}"
        output = client.run_task(task)
        if not qas_trigger_accepted(output):
            raise RuntimeError("QAS 未接受 TV_PRO 批量任务")
        return len(files), _tv_pro_output_names(files, task_base["taskname"])
    for name in files:
        task = dict(task_base)
        task["pattern"] = f"^{re.escape(name)}$"
        task["replace"] = name
        output = client.run_task(task)
        if not qas_trigger_accepted(output):
            raise RuntimeError("QAS 未接受直接链接任务")
    return len(files), files


def _select_direct_movie_source(sources: list[SourceFile]) -> SourceFile | None:
    videos = [source for source in sources if _is_video_file(source.name)]
    if not videos:
        return None
    feature_videos = [
        source
        for source in videos
        if not any(
            marker in source.name.casefold()
            for marker in ("sample", "trailer", "bonus", "makingof", "featurette", "interview")
        )
    ]
    candidates = feature_videos or videos
    # quality_score includes the configured quality-priority list. Size is
    # only a stable tie-breaker, so a preferred 1080p release can beat 4K.
    return max(candidates, key=lambda source: (quality_score(source), source.size, source.name.casefold()))


def _run_direct_movie_task(
    client: QasClient,
    task_base: dict,
    source: SourceFile,
    title: str,
    year: str,
) -> tuple[int, list[str]]:
    task = dict(task_base)
    task["pattern"] = f"^{re.escape(source.name)}$"
    if title.strip():
        target = MediaTarget(
            tmdb_id=0,
            media_type="movie",
            title=title.strip(),
            series_year=year.strip(),
        )
        pair = build_movie_rename_pair(target, source, ("direct_link", "quality_selected"))
        task["replace"] = pair.replacement
        output_name = pair.replacement
    else:
        task["replace"] = source.name
        output_name = source.name
    output = client.run_task(task)
    if not qas_trigger_accepted(output):
        raise RuntimeError("QAS movie transfer was not accepted")
    return 1, [output_name]


_EPISODE_TOKEN = re.compile(
    r"(?i)(?:^|[^a-z])(?:s\d{1,2}[ ._-]*)?e\d{1,4}(?:[^a-z]|$)|(?:^|[^0-9])\d{1,3}(?=\.[^.]+$)"
)


def _can_use_tv_pro(files: list[str], title: str, category: str = "movie") -> bool:
    if not title.strip() or len(files) < 2:
        return False
    video_extensions = {extension.lstrip(".").lower() for extension in VIDEO_EXTENSIONS}
    if not all(_is_video_file(name, video_extensions) for name in files):
        return False
    normalized_category = str(category or "movie").strip().lower()
    if normalized_category != "tv":
        return False
    return True


def _is_video_file(name: str, extensions: set[str] | None = None) -> bool:
    allowed = extensions or {extension.lstrip(".").lower() for extension in VIDEO_EXTENSIONS}
    return "." in name and name.rsplit(".", 1)[-1].lower() in allowed


_SEASON_EPISODE = re.compile(r"(?i)(?:^|[^a-z])s\s*0*(\d{1,2})\s*e\s*0*(\d{1,4})")
_EPISODE_ONLY = re.compile(r"(?i)(?:^|[^a-z])e\s*0*(\d{1,4})")
_LEADING_EPISODE = re.compile(r"^\s*0*(\d{1,3})(?=\s*[. _-]|$)")
_NAMED_EPISODE = re.compile(r"(?i)(?:episode|ep|第)\s*0*(\d{1,4})")


def _looks_like_episode_file(name: str) -> bool:
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return bool(
        _SEASON_EPISODE.search(stem)
        or _EPISODE_ONLY.search(stem)
        or stem.strip().isdigit()
        or _LEADING_EPISODE.match(stem)
        or _NAMED_EPISODE.search(stem)
    )


def _tv_pro_output_names(files: list[str], taskname: str) -> list[str]:
    output: list[str] = []
    for name in files:
        extension = name.rsplit(".", 1)[-1]
        stem = name.rsplit(".", 1)[0]
        season_episode = _SEASON_EPISODE.search(stem)
        episode_only = _EPISODE_ONLY.search(stem)
        if season_episode:
            season, episode = (int(value) for value in season_episode.groups())
        elif episode_only:
            season, episode = 1, int(episode_only.group(1))
        elif stem.isdigit():
            season, episode = 1, int(stem)
        else:
            leading_episode = _LEADING_EPISODE.match(stem)
            named_episode = _NAMED_EPISODE.search(stem)
            if leading_episode:
                season, episode = 1, int(leading_episode.group(1))
            elif named_episode:
                season, episode = 1, int(named_episode.group(1))
            else:
                return []
        output.append(f"{taskname}.S{season:02d}E{episode:02d}.{extension}")
    return output


def _transfer_p115_share(link: str, save_path: str) -> int:
    count, _filenames = _transfer_p115_share_with_files(link, save_path)
    return count


def _transfer_p115_share_with_files(
    link: str,
    save_path: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
) -> tuple[int, list[str]]:
    count, filenames, _outputs = _transfer_p115_share_with_outputs(
        link,
        save_path,
        title=title,
        year=year,
        category=category,
    )
    return count, filenames


def _transfer_p115_share_with_outputs(
    link: str,
    save_path: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
) -> tuple[int, list[str], tuple[dict, ...]]:
    client = P115Client()
    if not client.configured():
        raise P115Error("115 Cookie 未配置")
    if title.strip():
        provider = P115TransferProvider(client)
        inspection = provider.inspect_share(link)
        sources = [item for item in inspection.files if item.name] if inspection.valid else []
        if not sources:
            raise P115Error(inspection.error or "115 分享链接内没有可转存文件")
        pairs = _p115_direct_rename_pairs(sources, title, year, category)
        target = MediaTarget(
            tmdb_id=0,
            media_type=_direct_media_type(category),
            title=title.strip(),
            category=_direct_media_type(category),
            series_year=year.strip(),
        )
        child_name = _cloud_download_child_for_target("p115", save_path)
        result = provider.execute(
            TransferPlan(
                target,
                LinkResolution(
                    True,
                    "ready",
                    "115 分享已验真",
                    share_url=inspection.share_url or link,
                    rename_pairs=pairs,
                ),
                save_path,
                destination_scope="cloud_download" if child_name else "",
                cloud_download_child=child_name,
            )
        )
        if not result.ok or not result.confirmed:
            raise P115Error(result.message or "115 转存未完成目标确认")
        outputs = tuple(dict(item) for item in result.outputs)
        return result.executed_items, [str(item.get("file_name") or "") for item in outputs], outputs
    snapshot = client.inspect_share(link)
    files = [item for item in snapshot.files if not item.is_dir and item.file_id]
    if not files:
        raise P115Error("分享链接内没有可转存文件")
    cid = client.ensure_directory(save_path)
    client.receive_share_files(snapshot.share, [item.file_id for item in files], cid)
    filenames = [item.name for item in files if item.name]
    return len(files), filenames, tuple({"file_name": name, "path": save_path} for name in filenames)


def _p115_direct_rename_pairs(
    sources: list[SourceFile],
    title: str,
    year: str,
    category: str,
) -> tuple[RenamePair, ...]:
    return _direct_link_rename_pairs(
        sources,
        title,
        year,
        category,
        provider_reason="native_p115",
    )


def _cloud_download_child_for_target(provider: str, save_path: str) -> str:
    """Resolve the authorized direct child for either a scope or its media directory."""
    settings = get_settings()
    direct = cloud_download_child_name(provider, save_path, settings=settings)
    if direct:
        return direct
    parent = str(save_path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[0] or "/"
    return cloud_download_child_name(provider, parent, settings=settings)


def _direct_link_rename_pairs(
    sources: list[SourceFile],
    title: str,
    year: str,
    category: str,
    *,
    provider_reason: str,
) -> tuple[RenamePair, ...]:
    replacements = _direct_identity_hint_replacements(
        sources,
        title,
        year,
        category,
        provider_reason=provider_reason,
    )
    return tuple(
        RenamePair(
            source.name,
            f"^{re.escape(source.name)}$",
            replacement,
            confidence="high",
            reasons=("direct_link", provider_reason),
            source_id=source.provider_file_id,
            source_path=source.path,
            source_size=source.size,
        )
        for source, replacement in zip(sources, replacements, strict=True)
    )


def _direct_identity_hint_replacements(
    sources: list[SourceFile],
    title: str,
    year: str,
    category: str,
    *,
    provider_reason: str,
) -> list[str]:
    """Apply only provable hint names while preserving the complete share."""
    replacements = [source.name for source in sources]
    normalized_title = str(title or "").strip()
    if not normalized_title:
        return replacements
    video_indexes = [index for index, source in enumerate(sources) if _is_video_file(source.name)]
    if not video_indexes:
        return replacements

    video_replacements: dict[int, str] = {}
    media_type = _direct_media_type(category)
    if media_type in {"movie", "concert", "documentary"}:
        videos = [sources[index] for index in video_indexes]
        selected = _select_direct_movie_source(videos)
        if selected is not None:
            selected_index = next(index for index in video_indexes if sources[index] is selected)
            target = MediaTarget(0, "movie", normalized_title, series_year=str(year or "").strip())
            video_replacements[selected_index] = build_movie_rename_pair(
                target,
                selected,
                ("direct_link", provider_reason),
            ).replacement
    else:
        task_name = ".".join(
            part
            for part in (
                sanitize_filename_component(normalized_title),
                sanitize_filename_component(year) if str(year or "").strip() else "",
            )
            if part
        )
        standardized = _tv_pro_output_names(
            [sources[index].name for index in video_indexes],
            task_name,
        )
        # No guessed S/E values: if even one video is ambiguous, keep every
        # original name and let the explicitly identified organizer review it.
        if len(standardized) == len(video_indexes):
            video_replacements.update(zip(video_indexes, standardized, strict=True))

    for index, replacement in video_replacements.items():
        replacements[index] = replacement
    _apply_direct_companion_replacements(sources, replacements, video_replacements)
    return _unique_direct_replacements(sources, replacements)


def _apply_direct_companion_replacements(
    sources: list[SourceFile],
    replacements: list[str],
    video_replacements: dict[int, str],
) -> None:
    renamed_stems = [
        (
            index,
            sources[index].name.rsplit(".", 1)[0],
            replacement.rsplit(".", 1)[0],
        )
        for index, replacement in video_replacements.items()
        if "." in sources[index].name and "." in replacement
    ]
    for source_index, source in enumerate(sources):
        if source_index in video_replacements:
            continue
        matches = [
            (len(source_stem), replacement_stem, source.name[len(source_stem):])
            for _video_index, source_stem, replacement_stem in renamed_stems
            if source.name.casefold().startswith(f"{source_stem}.".casefold())
        ]
        matches.sort(reverse=True)
        if matches and (len(matches) == 1 or matches[0][0] > matches[1][0]):
            _length, replacement_stem, suffix = matches[0]
            replacements[source_index] = f"{replacement_stem}{suffix}"


def _unique_direct_replacements(sources: list[SourceFile], replacements: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for replacement in replacements:
        key = replacement.casefold()
        counts[key] = counts.get(key, 0) + 1
    output: list[str] = []
    used: set[str] = set()
    for source, replacement in zip(sources, replacements, strict=True):
        candidate = replacement
        key = candidate.casefold()
        if counts.get(key, 0) > 1 or key in used:
            identity = str(source.provider_file_id or source.path or source.name)
            suffix = sha256(identity.encode("utf-8")).hexdigest()[:8]
            stem, dot, extension = candidate.rpartition(".")
            candidate = f"{stem or candidate}.mi-{suffix}{dot}{extension}" if dot else f"{candidate}.mi-{suffix}"
            key = candidate.casefold()
        used.add(key)
        output.append(candidate)
    return output


def _direct_openlist_sync_message(
    provider: str,
    save_path: str,
    filenames: list[str],
    *,
    job_id: int = 0,
    category: str = "movie",
    title: str = "",
    year: str = "",
) -> str:
    settings = get_settings()
    if not getattr(settings, "openlist_enabled", False) or not getattr(settings, "openlist_auto_sync", False):
        return ""
    if str(provider or "").strip().lower() != "quark":
        return ""
    try:
        result = complete_quark_to_p115(
            job_id=job_id,
            save_path=save_path,
            filenames=filenames,
            media_type=_direct_media_type(category),
            title=title.strip(),
            year=year.strip(),
            category=_direct_media_type(category),
        )
    except Exception as exc:
        return f"115 补齐未完成：{_user_error_message(exc)}"
    return result.message


def _direct_openlist_workflow_status(message: str) -> str:
    if "未完成" in message or "失败" in message:
        return "failed"
    if "提交" in message or "等待" in message or "后台" in message:
        return "running"
    return "done" if message else "skipped"


def _transfer_p115_cloud_download(link: str, save_path: str) -> P115CloudDownloadResult:
    settings = get_settings()
    try:
        return P115Client(settings).add_cloud_download(link, save_path)
    except P115Error as exc:
        if not _can_submit_p115_download_via_openlist(settings):
            raise
        try:
            openlist = OpenListClient()
            payload = openlist.offline_download_115(openlist.p115_storage_path(save_path), link)
        except OpenListError as fallback_exc:
            raise P115Error(f"{exc}；OpenList 115 Cloud 提交也失败：{fallback_exc}") from fallback_exc
        return P115CloudDownloadResult(
            payload=payload,
            target_cid=save_path,
            status="submitted",
            message="已通过 OpenList 的 115 Cloud 提交离线下载",
        )


def _can_submit_p115_download_via_openlist(settings) -> bool:
    """Legacy Open fallback is intentionally disabled for native 115 jobs."""
    return False


def _finish_p115_cloud_download_job(
    job_id: int,
    result: P115CloudDownloadResult,
    save_path: str,
    *,
    title: str = "",
    year: str = "",
) -> DirectLinkResult:
    if result.status == "done":
        message = f"115 云下载已完成，文件已保存到 {save_path}"
        if result.message and result.message not in message:
            message = f"{message}（{result.message}）"
        target_name = _cloud_download_task_name(result.task)
        organizer_message = _trigger_targeted_cloud_organizer(
            job_id,
            "p115",
            save_path,
            [target_name] if target_name else [],
            title=title,
            year=year,
        )
        if organizer_message:
            message = f"{message}；{organizer_message}"
        _finish_job(job_id, "done", "provider_completed", message)
        _add_direct_notification(job_id, "done", "provider_completed", "success", "115 云下载完成", message)
        return DirectLinkResult(True, job_id, message)
    if result.status == "failed":
        message = result.message or "115 云下载失败"
        _finish_job(job_id, "failed", "provider_failed", message)
        _add_direct_notification(job_id, "failed", "provider_failed", "error", "115 云下载失败", message)
        return DirectLinkResult(False, job_id, message)
    message = f"115 离线下载任务已提交到 {save_path}，后续进度请在 115 中查看"
    if result.message and result.message not in message:
        message = f"{message}（{result.message}）"
    if _start_p115_cloud_download_monitor(job_id, result, save_path, message, title=title, year=year):
        monitored_message = f"{message}；MediaIndex 将只跟踪这个任务，完成后尝试定点整理；STRM 仅在整理进入正式媒体库后生成"
        _add_direct_notification(job_id, "triggered", "provider_target_monitoring", "success", "115 离线下载已提交", monitored_message)
        return DirectLinkResult(True, job_id, monitored_message)
    if title.strip():
        message = f"{message}；115 未返回可跟踪任务标识，名称和年份将作为后续整理提示"
    message = f"{message}；等待云下载目录后续整理，未对原始文件生成 STRM"
    _finish_job(job_id, "done", "provider_submitted", message)
    _add_direct_notification(job_id, "done", "provider_submitted", "success", "115 离线下载已提交", message)
    return DirectLinkResult(True, job_id, message)


def _start_p115_cloud_download_monitor(
    job_id: int,
    result: P115CloudDownloadResult,
    save_path: str,
    message: str,
    *,
    title: str = "",
    year: str = "",
) -> bool:
    try:
        candidate = normalize_save_root(save_path)
    except ValueError:
        return False
    if not (result.info_hash or result.task_id):
        return False
    state = {
        "kind": "p115_cloud_download_target",
        "info_hash": result.info_hash,
        "task_id": result.task_id,
        "save_path": candidate,
        "title": title.strip(),
        "year": year.strip(),
    }
    with db() as conn:
        conn.execute(
            """UPDATE transfer_jobs SET status='triggered',stage='provider_target_monitoring',message=?,
               external_provider_status=?,finished_at=NULL WHERE id=?""",
            (
                f"{message}；正在定点跟踪该 115 离线下载任务"[:1000],
                json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                int(job_id),
            ),
        )
    return request_p115_cloud_download_monitor(job_id)


def request_p115_cloud_download_monitor(job_id: int) -> bool:
    with _p115_cloud_download_workers_lock:
        if int(job_id) in _p115_cloud_download_workers:
            return False
        _p115_cloud_download_workers.add(int(job_id))
    threading.Thread(
        target=_monitor_p115_cloud_download,
        args=(int(job_id),),
        name=f"media-index-p115-cloud-download-{int(job_id)}",
        daemon=True,
    ).start()
    return True


def recover_p115_cloud_download_monitors() -> int:
    with db() as conn:
        rows = conn.execute(
            """SELECT id FROM transfer_jobs WHERE provider='p115' AND status='triggered'
               AND stage='provider_target_monitoring' ORDER BY id LIMIT 50"""
        ).fetchall()
    return sum(1 for row in rows if request_p115_cloud_download_monitor(int(row["id"])))


def _monitor_p115_cloud_download(job_id: int) -> None:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT external_provider_status,save_path FROM transfer_jobs WHERE id=?",
                (int(job_id),),
            ).fetchone()
        if not row:
            return
        try:
            state = json.loads(str(row["external_provider_status"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            state = {}
        if not isinstance(state, dict) or state.get("kind") != "p115_cloud_download_target":
            return
        settings = get_settings()
        deadline = time.monotonic() + max(5, int(settings.qas_confirmation_timeout_minutes)) * 60
        client = P115Client(settings)
        while time.monotonic() < deadline:
            with db() as conn:
                current = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
            if not current or str(current["status"] or "") != "triggered":
                return
            try:
                result = client.cloud_download_task_status(
                    str(state.get("info_hash") or ""),
                    str(state.get("task_id") or ""),
                )
            except P115Error:
                time.sleep(10)
                continue
            if result.status == "failed":
                _finish_job(job_id, "failed", "provider_failed", result.message or "115 离线下载失败")
                return
            if result.status == "done":
                name = _cloud_download_task_name(result.task)
                title = str(state.get("title") or "").strip()
                organizer_message = _trigger_targeted_cloud_organizer(
                    job_id,
                    "p115",
                    str(state.get("save_path") or row["save_path"] or ""),
                    [name] if name else [],
                    title=title,
                    year=str(state.get("year") or ""),
                )
                message = result.message or "115 离线下载已完成"
                if organizer_message:
                    message = f"{message}；{organizer_message}"
                _finish_job(job_id, "done", "provider_completed", message)
                return
            time.sleep(10)
        _finish_job(job_id, "failed", "provider_confirmation_timeout", "115 离线下载长时间未确认完成；未扫描目标目录")
    finally:
        with _p115_cloud_download_workers_lock:
            _p115_cloud_download_workers.discard(int(job_id))


def _cloud_download_task_name(value: object) -> str:
    if isinstance(value, dict):
        for key in ("name", "file_name", "title"):
            candidate = str(value.get(key) or "").strip()
            if candidate:
                return candidate
        for child in value.values():
            candidate = _cloud_download_task_name(child)
            if candidate:
                return candidate
    elif isinstance(value, list):
        for child in value[:20]:
            candidate = _cloud_download_task_name(child)
            if candidate:
                return candidate
    return ""


def _trigger_targeted_cloud_organizer(
    job_id: int,
    provider: str,
    save_path: str,
    filenames: list[str],
    *,
    exact_files: tuple[dict, ...] | None = None,
    title: str = "",
    year: str = "",
    media_query_hint: str = "",
) -> str:
    """Offer exact staging outputs to the organizer without indexing raw files."""
    targets = exact_files or tuple(
        {"file_name": name, "path": save_path}
        for name in filenames
        if str(name or "").strip()
    )
    if not targets and not title.strip():
        return "任务未返回精确目标，等待云下载目录后续整理；未扫描目录，也未对原始文件生成 STRM"
    handled, message = try_targeted_cloud_download_organization(
        provider=provider,
        target_path=save_path,
        target_files=targets,
        media_title=title,
        media_year=year,
        media_query_hint=media_query_hint,
        explicit_request=bool(title.strip()),
    )
    if handled:
        return message
    if message:
        return message
    return "已保存到云下载目录，等待后续整理；请确认已启用并授权该子目录，未对原始文件生成 STRM"


def _offline_failure_message(exc: Exception) -> str:
    detail = _user_error_message(exc)
    if detail.startswith("115 离线下载任务提交失败"):
        return detail
    return f"115 离线下载任务提交失败：{detail}"


def _user_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if "10060" in message or "timed out" in message.casefold() or "timed out" in repr(exc).casefold():
        return "连接上游网盘服务超时（WinError 10060），请检查网盘连接和本地网络后重试"
    if message and message != type(exc).__name__:
        return message[:300]
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, Exception):
        cause_message = str(cause).strip()
        if cause_message and cause_message != type(cause).__name__:
            return cause_message[:300]
    return type(exc).__name__
