from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import threading
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.clients.qas import QasClient
from app.clients.pansou import PansouClient
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.movie_resolver import resolve_movie_source
from app.services.standard_resolver import resolve_standard_tv_source
from app.services.episode_matcher import is_video, match_episode_files
from app.services.media_planning import build_episode_coverage, build_media_plan
from app.services.cache import FileCache
from app.services.share_inspector import find_season_share_folders, inspect_share
from app.clients.pansou import infer_share_provider
from app.providers.registry import get_transfer_provider, resolve_provider_key
from app.services.provider_compat import provider_accepts_share


class _RecordingPansouClient:
    """Keep the candidate pool that produced one resource-card snapshot."""

    def __init__(self) -> None:
        self._client = PansouClient()
        self._items: list[dict] = []
        self._items_lock = threading.Lock()

    def configured(self) -> bool:
        return self._client.configured()

    @property
    def searched_items(self) -> tuple[dict, ...]:
        with self._items_lock:
            return tuple(dict(item) for item in self._items)

    def search_detailed(self, *args, **kwargs):
        response = self._client.search_detailed(*args, **kwargs)
        with self._items_lock:
            self._items.extend(dict(item) for item in response.items)
        return response


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
        provider_key in {"qas", "quark"}
        and media_type == "tv"
        and result.get("found")
        and root_share_url
        and infer_share_provider(root_share_url)[0] == "quark"
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
    pansou = _RecordingPansouClient()
    preferred_share_urls: tuple[str, ...] = ()
    if title.strip() and pansou.configured():
        # The card already knows the localized title.  Start PanSou while TMDB
        # resolves seasons and aired episodes, then combine both into one
        # provider-specific executable snapshot.
        with ThreadPoolExecutor(max_workers=2) as executor:
            target_future = executor.submit(resolve_media_target, tmdb_id, media_type, season_number)
            search_future = executor.submit(
                pansou.search_detailed,
                title.strip(),
                100,
                get_settings().pansou_search_timeout_seconds,
                result_mode="all",
                refresh=refresh,
            )
            target = target_future.result()
            first_search = search_future.result()
        preferred_share_urls = tuple(
            dict.fromkeys(
                str(item.get("share_url") or "").strip()
                for item in first_search.items
                if item.get("share_url") and provider_accepts_share(provider, str(item.get("share_url") or ""))
            )
        )[:100]
    else:
        target = resolve_media_target(tmdb_id, media_type, season_number)
    total_episode_numbers, aired_episode_numbers = _episode_progress(target)
    aired_episodes = tuple(
        episode for episode in target.episodes if episode.episode_number in aired_episode_numbers
    )
    transfer_provider = get_transfer_provider(provider)
    if media_type == "movie":
        resolution = resolve_movie_source(
            target,
            preferred_share_urls,
            qas=transfer_provider,
            pansou=pansou,
            max_queries=6,
            max_verify=10,
            refresh=refresh,
            provider_filter=provider,
        )
    elif media_type == "tv":
        resolution = resolve_standard_tv_source(
            replace(target, episodes=aired_episodes),
            preferred_share_urls,
            qas=transfer_provider,
            pansou=pansou,
            max_queries=6,
            max_verify=10,
            refresh=refresh,
            provider_filter=provider,
        )
    else:
        if not aired_episodes:
            coverage = build_episode_coverage(total=total_episode_numbers)
            return {
                "ok": True,
                "found": False,
                "message": "TMDB 标记的首集尚未播出",
                "next_air_date": min((episode.air_date for episode in target.episodes if episode.air_date), default=""),
                "total_episode_count": len(total_episode_numbers),
                "aired_episode_count": 0,
                "aired_episode_numbers": [],
                "available_episode_count": 0,
                "coverage": coverage.as_dict(),
                "plan": build_media_plan(
                    entrypoint="discovery",
                    provider=provider,
                    target=target,
                    coverage=coverage,
                    ttl_seconds=getattr(get_settings(), "resource_probe_cache_ttl_seconds", 300),
                ),
            }
        resolution = resolve_episode_source(
            replace(target, episodes=aired_episodes),
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
            or "provider_inspection_unavailable" in candidate.reasons
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
    transfer_share_urls = _transfer_share_urls(resolution, pansou.searched_items, provider)
    coverage = build_episode_coverage(
        total=total_episode_numbers,
        aired=aired_episode_numbers,
        available=matched_episodes,
    )
    plan = build_media_plan(
        entrypoint="discovery",
        provider=provider,
        target=target,
        episode_numbers=coverage.available_episode_numbers,
        preferred_share_urls=transfer_share_urls,
        coverage=coverage,
        ttl_seconds=getattr(get_settings(), "resource_probe_cache_ttl_seconds", 300),
    )
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
        "total_episode_count": len(total_episode_numbers),
        "aired_episode_count": len(aired_episode_numbers),
        "aired_episode_numbers": list(aired_episode_numbers),
        "available_episode_count": len(set(matched_episodes) & set(aired_episode_numbers)),
        "coverage": coverage.as_dict(),
        "plan": plan,
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
        "transfer_share_urls": list(transfer_share_urls),
        "plan_reusable": bool(resolution.ok and transfer_share_urls),
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
                    "total_episode_count": len(target.episodes),
                    "aired_episode_count": len(aired),
                    "aired_episode_numbers": [episode.episode_number for episode in aired],
                    "available_episode_count": len(
                        {episode for match in matches for episode in match.episode_numbers}
                        & {episode.episode_number for episode in aired}
                    ),
                    "stage": "multi_season_folder",
                    "candidate_count": 1,
                    "transfer_share_urls": [inspection.share_url],
                    "plan_reusable": True,
                    "cloud_types": ["quark"],
                    "provider": "qas",
                },
            )
        except Exception:
            continue


def _cache_key(media_type: str, tmdb_id: int, season_number: int | None, provider: str) -> str:
    # Matching semantics changed: cached candidates from the old resolver may
    # have treated a PanSou listing title as proof of the media identity.
    # Bump the namespace so results generated before the relaxed identity
    # matching rules cannot surface as confirmed.
    return f"v5:{media_type}:{tmdb_id}:{season_number or 0}:{provider}"


def _transfer_share_urls(resolution, searched_items: tuple[dict, ...], provider: str) -> tuple[str, ...]:
    values = [str(resolution.share_url or "").strip()]
    values.extend(
        str(candidate.share_url or "").strip()
        for candidate in resolution.reviewed_candidates
        if not candidate.rejected
    )
    values.extend(str(item.get("share_url") or "").strip() for item in searched_items)
    return tuple(
        dict.fromkeys(
            value
            for value in values
            if value and provider_accepts_share(provider, value)
        )
    )[:100]


def _episode_progress(target) -> tuple[tuple[int, ...], tuple[int, ...]]:
    total = tuple(sorted({int(episode.episode_number) for episode in target.episodes if int(episode.episode_number) > 0}))
    if not total:
        return (), ()
    timezone = str(getattr(get_settings(), "tracking_timezone", "Asia/Shanghai") or "Asia/Shanghai")
    today = datetime.now(ZoneInfo(timezone)).date().isoformat()
    aired = tuple(sorted({
        int(episode.episode_number)
        for episode in target.episodes
        if int(episode.episode_number) > 0 and (not episode.air_date or episode.air_date <= today)
    }))
    return total, aired
