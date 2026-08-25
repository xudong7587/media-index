from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import time
from urllib.parse import urlsplit

from app.clients.pansou import infer_share_provider
from app.clients.p115 import P115Client, P115CloudDownloadResult, P115Error
from app.clients.openlist import OpenListClient, OpenListError
from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.db.database import db
from app.domain.media import MediaTarget, SourceFile
from app.services.notifications import add_notification
from app.services.qas_executor import qas_trigger_accepted
from app.services.share_inspector import inspect_share
from app.services.openlist_sync import sync_transfer_outputs
from app.services.episode_matcher import VIDEO_EXTENSIONS, quality_score, sanitize_filename_component
from app.services.movie_matcher import build_movie_rename_pair
from app.services.paths import build_save_path


_LINK_RE = re.compile(r"(magnet:\?xt=[^\s]+|ed2k://[^\s]+|https?://[^\s]+)", re.IGNORECASE)
_OFFLINE_SCHEMES = {"magnet", "ed2k"}


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
    if provider not in {"qas", "p115"}:
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
        else:
            count, filenames = _transfer_qas_share_with_files(
                link,
                save_path,
                title=title,
                year=year,
                category=category,
            )
            message = f"转存已执行：夸克分享链接已提交到 {save_path}，共 {count} 个文件"
            if filenames or count:
                message = f"{message}；等待夸克完成改名后自动提交 OpenList 复制任务"
                if filenames:
                    _mark_direct_qas_triggered(job_id, filenames, message)
                else:
                    _mark_direct_qas_triggered(job_id, [], message, expected_count=count)
                from app.services.qas_reconciler import request_qas_reconciliation

                request_qas_reconciliation()
                _add_direct_notification(job_id, "triggered", "qas_triggered", "success", "下载链接转存已提交", message)
                return DirectLinkResult(True, job_id, message)
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
        response = QasClient().savepath_detail(root_path)
        return sorted(_qas_directory_names(response))
    except P115Error:
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
    _finish_job(job_id, "done", "provider_submitted", message)
    _add_direct_notification(job_id, "done", "provider_submitted", "success", "115 离线下载已提交", message)
    return DirectLinkResult(True, job_id, message)


def _offline_failure_message(exc: Exception) -> str:
    detail = _user_error_message(exc)
    if detail.startswith("115 离线下载任务提交失败"):
        return detail
    return f"115 离线下载任务提交失败：{detail}"


def _user_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if "10060" in message or "timed out" in message.casefold() or "timed out" in repr(exc).casefold():
        return "连接上游网盘服务超时（WinError 10060），请检查 QAS/网盘地址和本地网络后重试"
    if message and message != type(exc).__name__:
        return message[:300]
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, Exception):
        cause_message = str(cause).strip()
        if cause_message and cause_message != type(cause).__name__:
            return cause_message[:300]
    return type(exc).__name__
