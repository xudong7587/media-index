from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.clients.qas import QasClient
from app.clients.pansou import PansouClient
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.movie_resolver import resolve_movie_source
from app.services.standard_resolver import resolve_standard_tv_source
from app.services.episode_matcher import is_video, match_episode_files
from app.services.cache import FileCache
from app.services.share_inspector import find_season_share_folders, inspect_share
from app.clients.pansou import infer_share_provider
from app.providers.registry import get_transfer_provider, resolve_provider_key


def get_cached_resource_availability(
    tmdb_id: int,
    media_type: str,
    season_number: int | None = None,
    provider: str | None = None,
) -> dict | None:
    provider_key = resolve_provider_key("cloud", provider)
    cached = FileCache("resource-probe").get(
        _cache_key(media_type, tmdb_id, season_number, provider_key),
        get_settings().resource_probe_cache_ttl_seconds,
    )
    return {**cached, "cached": True} if isinstance(cached, dict) else None


def probe_resource_availability(
    tmdb_id: int,
    media_type: str,
    season_number: int | None = None,
    *,
    title: str = "",
    year: str = "",
    refresh: bool = False,
    provider: str | None = None,
) -> dict:
    provider_key = resolve_provider_key("cloud", provider)
    cache = FileCache("resource-probe")
    cache_key = _cache_key(media_type, tmdb_id, season_number, provider_key)
    if not refresh:
        cached = cache.get(cache_key, get_settings().resource_probe_cache_ttl_seconds)
        if isinstance(cached, dict):
            return {**cached, "cached": True}

    result = _probe_resource_availability(tmdb_id, media_type, season_number, provider_key, title=title, year=year, refresh=refresh)
    root_share_url = str(result.pop("root_share_url", ""))
    # A slower probe may finish after another request has already cached a
    # verified source.  Never let that stale negative result erase the newer
    # positive result (opening a dialog used to trigger exactly this race).
    concurrent = cache.get(cache_key, get_settings().resource_probe_cache_ttl_seconds)
    if not refresh and not result.get("found") and isinstance(concurrent, dict) and concurrent.get("found"):
        result = concurrent
    else:
        cache.set(cache_key, result)
    if (
        provider_key == "qas"
        and media_type == "tv"
        and result.get("found")
        and root_share_url
        and infer_share_provider(root_share_url)[1] == "qas"
    ):
        _cache_related_season_folders(cache, tmdb_id, root_share_url)
    return {**result, "cached": False}


def _probe_resource_availability(
    tmdb_id: int,
    media_type: str,
    season_number: int | None = None,
    provider: str = "qas",
    *,
    title: str = "",
    year: str = "",
    refresh: bool = False,
) -> dict:
    pansou = PansouClient()
    preferred_share_urls: tuple[str, ...] = ()
    if title.strip() and pansou.configured():
        first_search = pansou.search_detailed(
            " ".join(part for part in (title.strip(), year.strip()) if part),
            limit=100,
            timeout=get_settings().pansou_search_timeout_seconds,
            result_mode="all",
            refresh=refresh,
        )
        preferred_share_urls = tuple(
            dict.fromkeys(str(item.get("share_url") or "").strip() for item in first_search.items if item.get("share_url"))
        )[:20]
        if not preferred_share_urls:
            query_label = " ".join(part for part in (title.strip(), year.strip()) if part)
            return {
                "ok": True,
                "found": False,
                "ready": False,
                "requires_review": False,
                "message": f"PanSou 没有找到“{query_label}”的可用网盘资源",
                "title": title.strip(),
                "share_url": "",
                "source_share_url": "",
                "file_count": 0,
                "episode_numbers": [],
                "stage": "no_resource",
                "candidate_count": 0,
                "candidates": [],
                "cloud_types": [],
                "provider": provider,
                "root_share_url": "",
            }
    target = resolve_media_target(tmdb_id, media_type, season_number)
    transfer_provider = get_transfer_provider(provider)
    if media_type == "movie":
        resolution = resolve_movie_source(
            target,
            preferred_share_urls,
            qas=transfer_provider,
            pansou=pansou,
            max_queries=2,
            max_verify=10,
            refresh=refresh,
            provider_filter=provider,
        )
    elif media_type == "tv":
        aired = tuple(
            episode
            for episode in target.episodes
            if not episode.air_date or episode.air_date <= datetime.now(ZoneInfo(get_settings().tracking_timezone)).date().isoformat()
        )
        resolution = resolve_standard_tv_source(
            replace(target, episodes=aired),
            preferred_share_urls,
            qas=transfer_provider,
            pansou=pansou,
            max_queries=2,
            max_verify=10,
            refresh=refresh,
            provider_filter=provider,
        )
    else:
        today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date().isoformat()
        aired = [episode for episode in target.episodes if not episode.air_date or episode.air_date <= today]
        if not aired:
            return {
                "ok": True,
                "found": False,
                "message": "TMDB 标记的首集尚未播出",
                "next_air_date": min((episode.air_date for episode in target.episodes if episode.air_date), default=""),
            }
        resolution = resolve_episode_source(
            replace(target, episodes=tuple(aired)),
            preferred_share_urls,
            qas=transfer_provider,
            pansou=pansou,
            max_queries=8,
            max_verify=10,
            refresh=refresh,
            provider_filter=provider,
        )
    viable_candidate = any(
        not candidate.rejected
        and (
            any(is_video(name) for name in candidate.files)
            or "external_organize_requires_confirmation" in candidate.reasons
        )
        for candidate in resolution.reviewed_candidates
    )
    found = resolution.ok or viable_candidate
    matched_episodes = sorted({
        episode_number
        for match in resolution.matches
        for episode_number in getattr(match, "episode_numbers", ())
    })
    matched_episodes = sorted(
        set(matched_episodes)
        | {
            int(number)
            for pair in resolution.rename_pairs
            for number in getattr(pair, "episode_numbers", ())
            if int(number) > 0
        }
    )
    root_share_url = next(
        (
            candidate.share_url
            for candidate in reversed(resolution.reviewed_candidates)
            if not candidate.rejected and candidate.share_url
        ),
        "",
    )
    cloud_types = list(
        dict.fromkeys(
            candidate.cloud_type
            for candidate in resolution.reviewed_candidates
            if not candidate.rejected and candidate.cloud_type
        )
    )
    if resolution.ok and resolution.share_url:
        resolved_cloud_type = infer_share_provider(resolution.share_url)[0]
        if resolved_cloud_type and resolved_cloud_type not in cloud_types:
            cloud_types.insert(0, resolved_cloud_type)
    return {
        "ok": True,
        "found": found,
        "ready": resolution.ok,
        "requires_review": found and not resolution.ok,
        "message": resolution.message,
        "title": target.title,
        "share_url": resolution.share_url if resolution.ok else "",
        "source_share_url": resolution.share_url if resolution.ok else root_share_url,
        "file_count": len(resolution.matches or resolution.rename_pairs) if resolution.ok else 0,
        "episode_numbers": matched_episodes,
        "stage": resolution.stage,
        "candidate_count": len(resolution.reviewed_candidates),
        "candidates": [
            {
                "share_url": candidate.share_url,
                "title": candidate.title,
                "source": candidate.source,
                "published_at": candidate.published_at,
                "query": candidate.query,
                "score": candidate.score,
                "reasons": list(candidate.reasons),
                "files": list(candidate.files)[:8],
                "cloud_type": candidate.cloud_type,
                "provider": candidate.provider or provider,
            }
            for candidate in resolution.reviewed_candidates
            if not candidate.rejected and candidate.share_url
        ][:12],
        "cloud_types": cloud_types,
        "provider": provider,
        "root_share_url": root_share_url,
    }


def _cache_related_season_folders(cache: FileCache, tmdb_id: int, root_share_url: str) -> None:
    qas = QasClient()
    for folder in find_season_share_folders(qas, root_share_url):
        try:
            target = resolve_media_target(tmdb_id, "tv", folder.season_number)
            inspection = inspect_share(qas, folder.share_url)
            if not inspection.valid:
                continue
            today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date().isoformat()
            aired = [episode for episode in target.episodes if not episode.air_date or episode.air_date <= today]
            if not aired:
                continue
            matches, ambiguities = match_episode_files(target, list(inspection.files))
            covered = {number for match in matches for number in match.episode_numbers}
            latest = max(aired, key=lambda episode: episode.episode_number)
            if latest.episode_number not in covered or ambiguities or any(match.confidence != "high" for match in matches):
                continue
            cache.set(
                _cache_key("tv", tmdb_id, folder.season_number, "qas"),
                {
                    "ok": True,
                    "found": True,
                    "ready": True,
                    "requires_review": False,
                    "message": f"已从同一分享链接验证 {folder.name}",
                    "title": target.title,
                    "share_url": inspection.share_url,
                    "source_share_url": inspection.share_url,
                    "file_count": len(matches),
                    "episode_numbers": sorted({episode for match in matches for episode in match.episode_numbers}),
                    "stage": "multi_season_folder",
                    "candidate_count": 1,
                    "cloud_types": ["quark"],
                },
            )
        except Exception:
            continue


def _cache_key(media_type: str, tmdb_id: int, season_number: int | None, provider: str) -> str:
    return f"v2:{media_type}:{tmdb_id}:{season_number or 0}:{provider}"
