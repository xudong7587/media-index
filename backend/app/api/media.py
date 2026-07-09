from fastapi import APIRouter, Depends, Query

from app.clients.tmdb import TmdbClient, normalize_tmdb_item
from app.core.security import require_user
from app.services.transfer_executor import search_resource_availability

router = APIRouter(prefix="/api", tags=["media"], dependencies=[Depends(require_user)])


@router.get("/discover")
def discover(
    media_type: str = Query("movie"),
    page: int = 1,
    region: str = "",
    sort: str = "hot",
    genre: str = "",
    vote_min: float = 0,
):
    client = TmdbClient()
    if not client.configured():
        return {"results": [], "page": page, "total_pages": 1, "error": "tmdb_not_configured"}
    data = client.discover(media_type, page, region, sort, genre, vote_min)
    return {
        "results": [normalize_tmdb_item(raw, media_type) for raw in data.get("results", [])],
        "page": data.get("page", page),
        "total_pages": data.get("total_pages", 1),
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
def resources(media_type: str, tmdb_id: int, season_number: int | None = None, title: str = "", year: str = ""):
    if not title:
        detail = TmdbClient().details(media_type, tmdb_id)
        title = detail.get("title", "")
        year = detail.get("year", "")
    return search_resource_availability(title, year, season_number)
