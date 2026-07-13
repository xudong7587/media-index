from fastapi import APIRouter, Depends, Query

from app.clients.tmdb import TmdbClient, normalize_tmdb_item
from app.core.security import require_user
from app.services.resource_probe import get_cached_resource_availability, probe_resource_availability

router = APIRouter(prefix="/api", tags=["media"], dependencies=[Depends(require_user)])


@router.get("/discover")
def discover(
    media_type: str = Query("movie"),
    page: int = 1,
    region: str = "",
    sort: str = "hot",
    genre: str = "",
    vote_min: float = 0,
    page_size: int = Query(24, ge=1, le=40),
):
    client = TmdbClient()
    if not client.configured():
        return {"results": [], "page": page, "total_pages": 1, "error": "tmdb_not_configured"}

    tmdb_page_size = 20
    start_index = max(page - 1, 0) * page_size
    tmdb_page = start_index // tmdb_page_size + 1
    offset = start_index % tmdb_page_size
    collected = []
    total_pages = tmdb_page

    while len(collected) < page_size and tmdb_page <= total_pages:
        data = client.discover(media_type, tmdb_page, region, sort, genre, vote_min)
        total_pages = data.get("total_pages", total_pages) or total_pages
        raw_results = data.get("results", [])
        if offset:
            raw_results = raw_results[offset:]
            offset = 0
        collected.extend(raw_results)
        tmdb_page += 1
        if not raw_results:
            break

    return {
        "results": [normalize_tmdb_item(raw, media_type) for raw in collected[:page_size]],
        "page": page,
        "total_pages": max(1, (total_pages * tmdb_page_size + page_size - 1) // page_size),
    }


@router.get("/search")
def search(q: str, media_type: str = "all", page: int = 1):
    client = TmdbClient()
    if not client.configured():
        return {"results": [], "page": page, "total_pages": 1, "error": "tmdb_not_configured"}
    return client.search(q, media_type, page)


@router.get("/genres")
def genres(media_type: str = "movie"):
    client = TmdbClient()
    if not client.configured():
        return []
    return client.genres(media_type)


@router.get("/media/{media_type}/{tmdb_id}")
def details(media_type: str, tmdb_id: int):
    return TmdbClient().details(media_type, tmdb_id)


@router.get("/media/{media_type}/{tmdb_id}/seasons/{season_number}")
def season(media_type: str, tmdb_id: int, season_number: int):
    return TmdbClient().season(tmdb_id, season_number)


@router.get("/media/{media_type}/{tmdb_id}/resources")
def resources(
    media_type: str,
    tmdb_id: int,
    season_number: int | None = None,
    title: str = "",
    year: str = "",
    refresh: bool = False,
):
    return probe_resource_availability(tmdb_id, media_type, season_number, refresh=refresh)


@router.get("/media/{media_type}/{tmdb_id}/resource-cache")
def resource_cache(media_type: str, tmdb_id: int, season_number: int | None = None):
    return get_cached_resource_availability(tmdb_id, media_type, season_number)
