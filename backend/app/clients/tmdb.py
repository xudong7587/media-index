import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

from app.core.config import get_settings
from app.clients.http import open_url
from app.services.resource_aliases import preferred_resource_title
from app.services.cache import FileCache


TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p"


class TmdbClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cache = FileCache("tmdb")

    def configured(self) -> bool:
        return bool(self.settings.tmdb_api_key)

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.settings.tmdb_api_key:
            return {"error": "TMDB API key is not configured"}
        query = dict(params or {})
        query["api_key"] = self.settings.tmdb_api_key
        query.setdefault("language", "zh-CN")
        url = f"{TMDB_BASE}{path}?{urllib.parse.urlencode(query)}"
        last_error = ""
        for attempt in range(3):
            try:
                with open_url(url, timeout=15) as resp:
                    import json

                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.4 * (attempt + 1))
        return {"error": last_error}

    def _cached_get(self, path: str, params: dict | None = None, ttl_seconds: int = 3600, *, refresh: bool = False) -> dict:
        query = dict(params or {})
        key = json_cache_key(path, query)
        if not refresh:
            cached = self.cache.get(key, ttl_seconds)
            if cached is not None:
                return cached
        data = self._get(path, query)
        if not data.get("error"):
            self.cache.set(key, data)
        return data

    def discover(
        self,
        media_type: str,
        page: int = 1,
        region: str = "",
        sort: str = "hot",
        genre: str = "",
        vote_min: float = 0,
        watch_provider: str = "",
        watch_region: str = "US",
        refresh: bool = False,
    ) -> dict:
        path_type = discovery_media_type(media_type)
        sort_by = {
            "latest": "primary_release_date.desc" if path_type == "movie" else "first_air_date.desc",
            "rating": "vote_average.desc",
            "hot": "popularity.desc",
        }.get(sort, "popularity.desc")
        common_params = {"page": page, "include_adult": self.settings.tmdb_adult_content_enabled}
        if sort == "latest":
            today = date.today().isoformat()
            recent = (date.today() - timedelta(days=240)).isoformat()
            if path_type == "movie":
                common_params["primary_release_date.lte"] = today
                common_params["primary_release_date.gte"] = recent
            else:
                common_params["air_date.lte"] = today
                common_params["air_date.gte"] = recent
                sort_by = "popularity.desc"
        if genre:
            common_params["with_genres"] = genre
        if vote_min:
            common_params["vote_average.gte"] = vote_min
            common_params["vote_count.gte"] = 20
        if sort == "rating":
            common_params["vote_count.gte"] = max(200, int(common_params.get("vote_count.gte", 0)))
        if watch_provider:
            common_params["with_watch_providers"] = watch_provider
            common_params["watch_region"] = watch_region or "US"
        if path_type == "movie":
            params = {**common_params, "sort_by": sort_by}
            if media_type == "concert":
                params["with_genres"] = genre or "10402"
            elif media_type == "documentary":
                params["with_genres"] = genre or "99"
            if region == "cn":
                params["with_original_language"] = "zh"
            if media_type == "movie" and sort == "hot" and not genre and not region and not vote_min and not watch_provider:
                data = self._cached_get(
                    "/trending/movie/week",
                    {"page": page},
                    self.settings.tmdb_discover_cache_ttl_seconds,
                    refresh=refresh,
                )
                return self._filter_adult(data)
            return self._filter_discover_results(self._cached_get("/discover/movie", params, self.settings.tmdb_discover_cache_ttl_seconds, refresh=refresh), sort)
        if media_type == "variety":
            params = {
                **common_params,
                "with_genres": genre or "10764|10767",
                "sort_by": sort_by,
            }
            if region == "cn" or sort == "latest":
                params["with_original_language"] = "zh"
            return self._filter_discover_results(self._cached_get("/discover/tv", params, self.settings.tmdb_discover_cache_ttl_seconds, refresh=refresh), sort)
        params = {**common_params, "sort_by": sort_by}
        if media_type == "anime":
            params["with_genres"] = genre or "16"
            params["with_original_language"] = "ja"
        if region == "cn":
            params["with_original_language"] = "zh"
        if not genre:
            params["without_genres"] = "10764,10767"
        if media_type == "tv" and sort == "hot" and not genre and not region and not vote_min and not watch_provider:
            data = self._cached_get(
                "/trending/tv/week",
                {"page": page},
                self.settings.tmdb_discover_cache_ttl_seconds,
                refresh=refresh,
            )
            return self._filter_adult(data)
        return self._filter_discover_results(self._cached_get("/discover/tv", params, self.settings.tmdb_discover_cache_ttl_seconds, refresh=refresh), sort)

    def _filter_adult(self, data: dict) -> dict:
        if self.settings.tmdb_adult_content_enabled or not isinstance(data.get("results"), list):
            return data
        return {**data, "results": [item for item in data["results"] if not item.get("adult", False)]}

    def _filter_discover_results(self, data: dict, sort: str) -> dict:
        filtered = self._filter_adult(data)
        if sort not in {"rating", "latest"} or not isinstance(filtered.get("results"), list):
            return filtered
        results = [
            item
            for item in filtered["results"]
            if item.get("poster_path")
            and (item.get("release_date") or item.get("first_air_date"))
            and (sort != "rating" or int(item.get("vote_count") or 0) >= 200)
        ]
        return {**filtered, "results": results}

    def genres(self, media_type: str) -> list[dict]:
        path_type = discovery_media_type(media_type)
        data = self._cached_get(f"/genre/{path_type}/list", {}, self.settings.tmdb_genres_cache_ttl_seconds)
        genres = data.get("genres", [])
        if media_type == "variety":
            genres = [g for g in genres if g.get("id") in {10764, 10767}]
        return genres

    def search(self, query: str, media_type: str = "all", page: int = 1) -> dict:
        tokens = [value for value in query.strip().split() if value][:4]
        if len(tokens) > 1:
            return self._contextual_search(tokens, media_type, page)
        if media_type == "all":
            params = {"query": query, "page": page, "include_adult": self.settings.tmdb_adult_content_enabled}
            movie = self._filter_adult(self._get("/search/movie", params))
            tv = self._filter_adult(self._get("/search/tv", params))
            results = []
            for item in movie.get("results", [])[:10]:
                results.append(normalize_tmdb_item(item, "movie"))
            for item in tv.get("results", [])[:10]:
                mt = "variety" if set(item.get("genre_ids", [])) & {10764, 10767} else "tv"
                results.append(normalize_tmdb_item(item, mt))
            if not any(marker in compact_search_title(query) for marker in _DERIVATIVE_SEARCH_MARKERS):
                needle = compact_search_title(query)
                results = [
                    item
                    for item in results
                    if not (
                        needle != compact_search_title(str(item.get("title") or ""))
                        and any(marker in compact_search_title(str(item.get("title") or "")) for marker in _DERIVATIVE_SEARCH_MARKERS)
                    )
                ]
            return {"results": results, "page": page, "total_pages": 1}
        path = "/search/movie" if media_type == "movie" else "/search/tv"
        data = self._filter_adult(self._get(path, {"query": query, "page": page, "include_adult": self.settings.tmdb_adult_content_enabled}))
        raw = data.get("results", [])
        if media_type == "variety":
            raw = [r for r in raw if set(r.get("genre_ids", [])) & {10764, 10767}]
        return {
            "results": [normalize_tmdb_item(item, media_type) for item in raw],
            "page": data.get("page", page),
            "total_pages": data.get("total_pages", 1),
        }

    def _contextual_search(self, tokens: list[str], media_type: str, page: int) -> dict:
        allowed_types = ("movie", "tv") if media_type == "all" else (("movie",) if media_type == "movie" else ("tv",))
        candidates: dict[tuple[str, int], dict] = {}
        token_matches: list[set[tuple[str, int]]] = []
        for token in tokens:
            matches: set[tuple[str, int]] = set()
            for path_type in allowed_types:
                data = self._filter_adult(self._get(
                    f"/search/{path_type}",
                    {"query": token, "page": 1, "include_adult": self.settings.tmdb_adult_content_enabled},
                ))
                for item in data.get("results", [])[:20]:
                    key = (path_type, int(item.get("id") or 0))
                    if key[1]:
                        matches.add(key)
                        candidates.setdefault(key, item)
            if not token.isdecimal():
                people = self._get("/search/person", {"query": token, "page": 1, "include_adult": False})
                for person in people.get("results", [])[:3]:
                    person_id = int(person.get("id") or 0)
                    if not person_id:
                        continue
                    credits = self._get(f"/person/{person_id}/combined_credits", {})
                    for item in [*(credits.get("cast") or []), *(credits.get("crew") or [])]:
                        path_type = str(item.get("media_type") or "")
                        if path_type not in allowed_types:
                            continue
                        key = (path_type, int(item.get("id") or 0))
                        if key[1]:
                            matches.add(key)
                            candidates.setdefault(key, item)
            token_matches.append(matches)

        strict = set.intersection(*token_matches) if token_matches else set()
        if not strict:
            strict = {
                key for key in candidates
                if sum(key in matches for matches in token_matches) == len(token_matches)
            }
        ordered = sorted(
            strict,
            key=lambda key: (
                float(candidates[key].get("popularity") or 0),
                int(candidates[key].get("vote_count") or 0),
            ),
            reverse=True,
        )[:20]
        results = []
        for path_type, tmdb_id in ordered:
            item = candidates[(path_type, tmdb_id)]
            item_type = "variety" if path_type == "tv" and set(item.get("genre_ids", [])) & {10764, 10767} else path_type
            if media_type == "variety" and item_type != "variety":
                continue
            results.append(normalize_tmdb_item(item, item_type if media_type == "all" else media_type))
        return {"results": results, "page": page, "total_pages": 1}

    def details(self, media_type: str, tmdb_id: int) -> dict:
        path_type = "tv" if media_type in ("tv", "variety") else "movie"
        data = self._cached_get(
            f"/{path_type}/{tmdb_id}",
            {"append_to_response": "alternative_titles,translations"},
            self.settings.tmdb_details_cache_ttl_seconds,
        )
        if data.get("error"):
            return data
        return normalize_tmdb_details(data, media_type)

    def season(self, tmdb_id: int, season_number: int) -> dict:
        return self._cached_get(
            f"/tv/{tmdb_id}/season/{season_number}",
            {},
            self.settings.tmdb_tracking_cache_ttl_seconds,
        )


def image_url(path: str | None, size: str) -> str:
    return f"{TMDB_IMAGE}/{size}{path}" if path else ""


def json_cache_key(path: str, params: dict) -> str:
    return f"{path}:{json_dumps_sorted(params)}"


def json_dumps_sorted(value: dict) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_DERIVATIVE_SEARCH_MARKERS = ("幕后", "特辑", "纪录片", "花絮", "预告")


def compact_search_title(value: str) -> str:
    import re

    return re.sub(r"[\W_]+", "", str(value or ""), flags=re.UNICODE).casefold()


def normalize_tmdb_item(item: dict, media_type: str) -> dict:
    date = item.get("release_date") or item.get("first_air_date") or ""
    title = item.get("title") or item.get("name") or ""
    title = preferred_resource_title(int(item.get("id") or 0), media_type, title)
    return {
        "id": item.get("id"),
        "tmdb_id": item.get("id"),
        "media_type": media_type,
        "title": title,
        "year": date[:4],
        "release_date": date,
        "poster_url": image_url(item.get("poster_path"), "w342"),
        "backdrop_url": image_url(item.get("backdrop_path"), "w780"),
        "overview": item.get("overview") or "",
        "vote_average": item.get("vote_average") or 0,
        "vote_count": item.get("vote_count") or 0,
        "popularity": item.get("popularity") or 0,
    }


def normalize_tmdb_details(data: dict, media_type: str) -> dict:
    item = normalize_tmdb_item(data, media_type)
    item.update(
        {
            "original_title": data.get("original_title") or data.get("original_name") or "",
            "aliases": collect_title_aliases(data),
            "status": data.get("status") or "",
            "genres": [g.get("name", "") for g in data.get("genres", [])],
            "runtime": data.get("runtime") or next(iter(data.get("episode_run_time", [])), 0),
            "seasons": [
                {
                    "season_number": s.get("season_number"),
                    "name": s.get("name") or "",
                    "episode_count": s.get("episode_count") or 0,
                    "air_date": s.get("air_date") or "",
                }
                for s in data.get("seasons", [])
                if s.get("season_number", 0) > 0
            ],
        }
    )
    item["poster_url"] = image_url(data.get("poster_path"), "w500")
    item["backdrop_url"] = image_url(data.get("backdrop_path"), "w1280")
    return item


def collect_title_aliases(data: dict) -> list[str]:
    values: list[str] = []
    alternatives = data.get("alternative_titles") or {}
    for item in alternatives.get("titles", []) or alternatives.get("results", []):
        if isinstance(item, dict):
            values.append(str(item.get("title") or ""))
    translations = data.get("translations") or {}
    for item in translations.get("translations", []):
        if not isinstance(item, dict):
            continue
        translated = item.get("data") or {}
        if isinstance(translated, dict):
            values.append(str(translated.get("title") or translated.get("name") or ""))

    canonical = {
        str(data.get("title") or data.get("name") or "").strip().casefold(),
        str(data.get("original_title") or data.get("original_name") or "").strip().casefold(),
    }
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if not cleaned or key in canonical or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= 20:
            break
    return result


def discovery_media_type(media_type: str) -> str:
    return "movie" if media_type in {"movie", "concert", "documentary"} else "tv"
