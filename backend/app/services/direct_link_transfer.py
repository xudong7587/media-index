from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import threading
import time
from urllib.parse import urlsplit

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
from app.providers.quark import QuarkTransferProvider
from app.services.notifications import add_notification
from app.services.qas_executor import qas_trigger_accepted
from app.services.share_inspector import inspect_share
from app.services.openlist_sync import sync_transfer_outputs
from app.services.episode_matcher import VIDEO_EXTENSIONS, quality_score, sanitize_filename_component
from app.services.movie_matcher import build_movie_rename_pair
from app.services.paths import build_save_path, normalize_save_root
from app.services.post_transfer_pipeline import try_targeted_cloud_download_organization


_LINK_RE = re.compile(r"(magnet:\?xt=[^\s]+|ed2k://[^\s]+|https?://[^\s]+)", re.IGNORECASE)
_OFFLINE_SCHEMES = {"magnet", "ed2k"}
_p115_cloud_download_workers: set[int] = set()
_p115_cloud_download_workers_lock = threading.Lock()


def _provider_cloud_organizer_enabled(settings: object, provider: str) -> bool:
    resolver = getattr(settings, "provider_cloud_download_organizer_enabled", None)
    if callable(resolver):
        return bool(resolver(provider))
    explicit = getattr(settings, f"{provider}_cloud_download_organizer_enabled", None)
    if explicit is not None:
        return bool(explicit)
    return bool(getattr(settings, "cloud_download_organizer_enabled", False))


@dataclass(frozen=True)
class DirectLinkResult:
    ok: bool
    job_id: int | None
    message: str
    unsupported: bool = False


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


def extract_download_link(text: str) -> str:
    match = _LINK_RE.search(str(text or "").strip())
    return match.group(1).strip() if match else ""


def looks_like_download_link(text: str) -> bool:
    return bool(extract_download_link(text))


def prepare_direct_link_request(
    command: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
    category_options: bool = False,
) -> DirectLinkRequest:
    settings = get_settings()
    link = extract_download_link(command)
    if not link:
        raise ValueError("没有识别到下载链接")
    normalized_title = title.strip()
    normalized_year = _resolve_direct_year(normalized_title, year, category)
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
    root_path = _direct_media_save_path(provider, normalized_title, normalized_year, category) if normalized_title else _direct_save_path(provider)
    _validate_provider_path(provider, root_path)

    return DirectLinkRequest(
        link=link,
        provider=provider,
        root_path=root_path,
        options=_direct_target_options(provider, root_path, title=normalized_title if category_options else "", year=normalized_year),
        title=normalized_title,
        year=normalized_year,
        category=_direct_media_type(category),
    )


def handle_direct_link_transfer(
    command: str,
    from_user: str = "",
    save_path: str = "",
    request_source: str = "wecom",
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
) -> DirectLinkResult:
    try:
        request = prepare_direct_link_request(command, title=title, year=year, category=category)
    except ValueError as exc:
        return DirectLinkResult(False, None, str(exc))
    link = request.link
    provider = request.provider
    title = request.title or title.strip()
    year = request.year or year.strip()
    category = request.category
    save_path = save_path.strip() or request.root_path
    # Web direct-link transfers select a media category, so always use the
    # canonical media-library path when the caller supplied media metadata.
    # This also keeps older clients from reusing the pre-category download path.
    if title.strip():
        save_path = _direct_media_save_path(provider, title, year, category)
    try:
        _validate_provider_path(provider, save_path)
    except ValueError as exc:
        return DirectLinkResult(False, None, str(exc))
    parsed = urlsplit(link)
    if parsed.scheme.lower() in _OFFLINE_SCHEMES:
        if provider == "p115":
            job_id, duplicate = _create_direct_job(link, provider, save_path, from_user, request_source)
            if duplicate:
                return DirectLinkResult(True, job_id, "相同下载链接任务已在运行，未重复触发")
            try:
                return _finish_p115_cloud_download_job(job_id, _transfer_p115_cloud_download(link, save_path), save_path)
            except Exception as exc:
                message = _offline_failure_message(exc)
                _finish_job(job_id, "failed", "provider_failed", message)
                _add_direct_notification(job_id, "failed", "provider_failed", "error", "115 离线下载失败", message)
                return DirectLinkResult(False, job_id, message)
        return DirectLinkResult(False, None, "磁力/电驴链接目前只支持关联网盘选择 115 后提交离线下载", True)

    _cloud_type, inferred_provider = infer_share_provider(link)
    if inferred_provider and inferred_provider != provider:
        provider = inferred_provider
        save_path = _direct_media_save_path(provider, title, year, category) if title.strip() else _direct_save_path(provider)
        try:
            _validate_provider_path(provider, save_path)
        except ValueError as exc:
            return DirectLinkResult(False, None, str(exc))
    if not inferred_provider:
        if provider == "p115":
            job_id, duplicate = _create_direct_job(link, provider, save_path, from_user, request_source)
            if duplicate:
                return DirectLinkResult(True, job_id, "相同下载链接任务已在运行，未重复触发")
            try:
                return _finish_p115_cloud_download_job(job_id, _transfer_p115_cloud_download(link, save_path), save_path)
            except Exception as exc:
                message = _offline_failure_message(exc)
                _finish_job(job_id, "failed", "provider_failed", message)
                _add_direct_notification(job_id, "failed", "provider_failed", "error", "115 离线下载失败", message)
                return DirectLinkResult(False, job_id, message)
        return DirectLinkResult(False, None, "普通 HTTP 下载链接目前只支持关联网盘选择 115 后提交离线下载", True)

    job_id, duplicate = _create_direct_job(link, provider, save_path, from_user, request_source, title=title)
    if duplicate:
        return DirectLinkResult(True, job_id, f"相同下载链接任务已在运行，未重复触发")
    try:
        if provider == "p115":
            count, filenames = _transfer_p115_share_with_files(link, save_path)
            sync_message = _direct_openlist_sync_message(provider, save_path, filenames, category=category, title=title)
            message = f"转存已执行：115 分享链接已转存到 {save_path}，共 {count} 个文件"
            if sync_message:
                message = f"{message}；{sync_message}"
        elif provider == "quark":
            count, filenames, exact_outputs = _transfer_quark_share_with_files(
                link,
                save_path,
                title=title,
                year=year,
                category=category,
            )
            sync_message = _direct_openlist_sync_message(provider, save_path, filenames, category=category, title=title)
            message = f"转存已执行：原生夸克已完成验真、改名、转存和目标确认，共 {count} 个文件"
            if sync_message:
                message = f"{message}；{sync_message}"
        else:
            raise RuntimeError("新任务只支持原生夸克或原生 115")
        organizer_message = _trigger_targeted_cloud_organizer(
            provider,
            save_path,
            filenames,
            exact_files=exact_outputs if provider == "quark" else None,
        )
        if organizer_message:
            message = f"{message}；{organizer_message}"
        _finish_job(job_id, "done", "provider_completed", message)
        _add_direct_notification(job_id, "done", "provider_completed", "success", "下载链接转存完成", message)
        return DirectLinkResult(True, job_id, message)
    except Exception as exc:
        message = f"下载链接转存失败：{_user_error_message(exc)}"
        _finish_job(job_id, "failed", "provider_failed", message)
        _add_direct_notification(job_id, "failed", "provider_failed", "error", "下载链接转存失败", message)
        return DirectLinkResult(False, job_id, message)


def _direct_save_path(provider: str) -> str:
    settings = get_settings()
    resolver = getattr(settings, "provider_cloud_download_path", None)
    if callable(resolver):
        return resolver(provider)
    return settings.provider_save_root(provider).rstrip("/") or "/"


def _direct_media_type(category: str) -> str:
    value = str(category or "movie").strip().lower()
    return value if value in {"movie", "tv", "variety", "concert", "documentary", "anime"} else "movie"


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


def _direct_media_save_path(provider: str, title: str, year: str, category: str) -> str:
    media_type = _direct_media_type(category)
    kwargs = {"provider": provider}
    if get_settings().season_subdirectory_enabled and media_type != "movie":
        kwargs["season"] = 1
    return build_save_path("cloud", media_type, title.strip(), year.strip(), **kwargs)


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
    if title.strip():
        return tuple(
            DirectLinkTargetOption(
                provider,
                _direct_media_save_path(provider, title, year, media_type),
                {"movie": "电影", "tv": "电视剧", "variety": "综艺", "concert": "演唱会", "documentary": "纪录片", "anime": "动漫"}[media_type],
                media_type,
            )
            for media_type in ("movie", "tv", "variety", "concert", "documentary", "anime")
        )
    directories = _provider_child_directories(provider, root_path)
    if not directories:
        return (DirectLinkTargetOption(provider, root_path, "当前目录"),)
    return tuple(
        DirectLinkTargetOption(provider, f"{root_path.rstrip('/')}/{name}", name)
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


def _validate_provider_path(provider: str, path: str) -> None:
    settings = get_settings()
    root = str(
        getattr(settings, "p115_root_path", "") if provider == "p115"
        else getattr(settings, "quark_root_path", "")
    ).rstrip("/") or settings.provider_save_root(provider).rstrip("/")
    normalized = "/" + "/".join(part for part in path.replace("\\", "/").split("/") if part)
    if not root or normalized == "/" or not (normalized == root or normalized.startswith(f"{root}/")):
        raise ValueError("下载链接默认路径必须位于所选网盘保存根目录内")


def _create_direct_job(
    link: str,
    provider: str,
    save_path: str,
    from_user: str,
    request_source: str,
    *,
    title: str = "",
) -> tuple[int, bool]:
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
    sources = [item for item in inspection.files if item.name and _is_video_file(item.name)] if inspection.valid else []
    if not sources:
        raise QuarkError(inspection.error or "夸克分享链接内没有可转存的视频文件")

    media_type = _direct_media_type(category)
    selected = sources
    replacements = [item.name for item in sources]
    if media_type == "movie":
        source = _select_direct_movie_source(sources)
        if source is None:
            raise QuarkError("夸克分享链接内没有可唯一选择的电影文件")
        selected = [source]
        replacements = [
            build_movie_rename_pair(
                MediaTarget(0, "movie", title.strip() or source.name.rsplit(".", 1)[0], series_year=year.strip()),
                source,
                ("direct_link", "native_quark"),
            ).replacement
        ]
    elif media_type == "tv" and title.strip():
        task_name = ".".join(
            part for part in (sanitize_filename_component(title), sanitize_filename_component(year)) if part
        )
        standardized = _tv_pro_output_names([item.name for item in sources], task_name)
        if standardized:
            replacements = standardized

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
    result = provider.execute(
        TransferPlan(
            target,
            LinkResolution(True, "ready", "原生夸克分享已验真", share_url=inspection.share_url or link, rename_pairs=pairs),
            save_path,
        )
    )
    if not result.ok or not result.confirmed:
        raise QuarkError(result.message or "原生夸克转存未完成目标确认")
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


def _transfer_p115_share_with_files(link: str, save_path: str) -> tuple[int, list[str]]:
    client = P115Client()
    if not client.configured():
        raise P115Error("115 Cookie 未配置")
    snapshot = client.inspect_share(link)
    files = [item for item in snapshot.files if not item.is_dir and item.file_id]
    if not files:
        raise P115Error("分享链接内没有可转存文件")
    cid = client.ensure_directory(save_path)
    client.receive_share_files(snapshot.share, [item.file_id for item in files], cid)
    return len(files), [item.name for item in files if item.name]


def _direct_openlist_sync_message(
    provider: str,
    save_path: str,
    filenames: list[str],
    *,
    category: str = "movie",
    title: str = "",
) -> str:
    settings = get_settings()
    if not getattr(settings, "openlist_enabled", False) or not getattr(settings, "openlist_auto_sync", False):
        return ""
    try:
        results = sync_transfer_outputs(
            provider,
            save_path,
            filenames,
            media_type=_direct_media_type(category),
            display_title=title.strip() or "下载链接转存",
        )
    except Exception as exc:
        return f"OpenList 自动同步提交失败：{_user_error_message(exc)}"
    if not results:
        return "OpenList 未找到可同步的目标网盘"
    successful = [item for item in results if item.get("ok")]
    if successful:
        job_ids = [str(item.get("job_id")) for item in successful if item.get("job_id")]
        suffix = f" #{','.join(job_ids)}" if job_ids else ""
        return f"OpenList 已提交后台复制任务{suffix}"
    return f"OpenList 自动同步失败：{results[0].get('message') or '未能提交复制任务'}"


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
) -> DirectLinkResult:
    if result.status == "done":
        message = f"115 云下载已完成，文件已保存到 {save_path}"
        if result.message and result.message not in message:
            message = f"{message}（{result.message}）"
        target_name = _cloud_download_task_name(result.task)
        organizer_message = _trigger_targeted_cloud_organizer(
            "p115",
            save_path,
            [target_name] if target_name else [],
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
    if _start_p115_cloud_download_monitor(job_id, result, save_path, message):
        monitored_message = f"{message}；MediaIndex 将只跟踪这个任务，完成后定点整理"
        _add_direct_notification(job_id, "triggered", "provider_target_monitoring", "success", "115 离线下载已提交", monitored_message)
        return DirectLinkResult(True, job_id, monitored_message)
    _finish_job(job_id, "done", "provider_submitted", message)
    _add_direct_notification(job_id, "done", "provider_submitted", "success", "115 离线下载已提交", message)
    return DirectLinkResult(True, job_id, message)


def _start_p115_cloud_download_monitor(
    job_id: int,
    result: P115CloudDownloadResult,
    save_path: str,
    message: str,
) -> bool:
    settings = get_settings()
    if not _provider_cloud_organizer_enabled(settings, "p115"):
        return False
    trigger_enabled = getattr(settings, "cloud_download_organizer_trigger_enabled", None)
    if callable(trigger_enabled) and not trigger_enabled("event"):
        return False
    try:
        candidate = normalize_save_root(save_path)
        from app.services.cloud_download_organizer import _authorized_scope_for_candidate

        authorized_scope = _authorized_scope_for_candidate(settings, "p115", candidate)
    except ValueError:
        return False
    if not authorized_scope:
        return False
    if not (result.info_hash or result.task_id):
        return False
    state = {
        "kind": "p115_cloud_download_target",
        "info_hash": result.info_hash,
        "task_id": result.task_id,
        "save_path": candidate,
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
            current_settings = get_settings()
            current_trigger_enabled = getattr(current_settings, "cloud_download_organizer_trigger_enabled", None)
            if (
                not _provider_cloud_organizer_enabled(current_settings, "p115")
                or (callable(current_trigger_enabled) and not current_trigger_enabled("event"))
            ):
                _finish_job(job_id, "done", "provider_completed", "115 离线下载仍由网盘执行；115 云下载整理事件触发已关闭，MediaIndex 已停止定点跟踪")
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
                organizer_message = _trigger_targeted_cloud_organizer(
                    "p115",
                    str(state.get("save_path") or row["save_path"] or ""),
                    [name] if name else [],
                )
                message = result.message or "115 离线下载已完成"
                if organizer_message:
                    message = f"{message}；{organizer_message}"
                elif not name:
                    message = f"{message}；任务未返回精确目标名称，已拒绝目录扫描"
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
    provider: str,
    save_path: str,
    filenames: list[str],
    *,
    exact_files: tuple[dict, ...] | None = None,
) -> str:
    """Hand the exact completed transfer to the organizer when in its scope."""
    handled, message = try_targeted_cloud_download_organization(
        provider=provider,
        target_path=save_path,
        target_files=exact_files or ({"file_name": name, "path": save_path} for name in filenames),
    )
    return message if handled else ""


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
