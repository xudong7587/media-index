import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import weakref
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings
from app.clients.http import open_url


_SEARCH_CACHE_TTL_SECONDS = 15.0
_REFRESH_COALESCE_SECONDS = 2.0
_SEARCH_CACHE_GUARD = threading.Lock()
_SEARCH_CACHE: dict[tuple, tuple[float, "PansouSearchResponse", object, bool]] = {}
_SEARCH_LOCKS: weakref.WeakValueDictionary = weakref.WeakValueDictionary()


class PansouClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def configured(self) -> bool:
        return bool(self.settings.pansou_url)

    def search(self, keyword: str, limit: int = 10, timeout: int = 20) -> list[dict]:
        return self.search_detailed(keyword, limit, timeout, result_mode="merge").items

    def search_detailed(
        self,
        keyword: str,
        limit: int = 20,
        timeout: int = 20,
        *,
        title_en: str = "",
        refresh: bool = False,
        result_mode: str = "all",
        exclude: tuple[str, ...] = (),
    ) -> "PansouSearchResponse":
        """Search once per short-lived query snapshot.

        Discovery probes for 115 and Quark run independently, but PanSou is a
        shared discovery source.  A tiny single-flight window lets those lanes
        consume one network response without turning tracking into a stale
        long-lived cache. An explicit refresh starts a new snapshot while
        concurrent provider refreshes still share that same generation.
        """
        base = self.settings.pansou_url.rstrip("/")
        cache_key = (
            id(self.settings),
            base,
            keyword.strip().casefold(),
            int(limit),
            int(timeout),
            str(title_en or "").strip().casefold(),
            str(result_mode or "all"),
            tuple(str(item) for item in exclude),
        )
        cached = _cached_search(cache_key, require_refresh=refresh)
        if cached is not None:
            return cached
        lock = _search_lock(cache_key)
        with lock:
            cached = _cached_search(cache_key, require_refresh=refresh)
            if cached is not None:
                return cached
            result = self._search_detailed_uncached(
                keyword,
                limit,
                timeout,
                title_en=title_en,
                refresh=refresh,
                result_mode=result_mode,
                exclude=exclude,
            )
            with _SEARCH_CACHE_GUARD:
                _prune_search_cache(time.monotonic())
                # Cache an exhausted empty poll window too. Otherwise the two
                # provider lanes repeat the same slow negative query back to
                # back. Explicit refresh still bypasses this short snapshot.
                # Keep settings alive so its identity cannot be recycled.
                _SEARCH_CACHE[cache_key] = (time.monotonic(), result, self.settings, refresh)
            return _copy_search_response(result)

    def _search_detailed_uncached(
        self,
        keyword: str,
        limit: int = 20,
        timeout: int = 20,
        *,
        title_en: str = "",
        refresh: bool = False,
        result_mode: str = "all",
        exclude: tuple[str, ...] = (),
    ) -> "PansouSearchResponse":
        base = self.settings.pansou_url.rstrip("/")
        if not keyword.strip():
            return PansouSearchResponse(keyword, [], "empty_keyword")
        if not base:
            return PansouSearchResponse(keyword, [], "not_configured")
        # Let PanSou apply the source configuration maintained by the PanSou
        # instance itself.  Supplying a partial copy of its channel/plugin
        # selection changes its cache key and can return an empty snapshot.
        options = {"kw": keyword}

        attempts = max(1, min(int(self.settings.pansou_result_poll_attempts), 4))
        poll_seconds = max(0.0, min(float(self.settings.pansou_result_poll_seconds), 5.0))
        # `timeout` is the complete caller-facing budget, not a budget for
        # every poll.  Reusing it per request turns a 45-second search into
        # a multi-minute card spinner whenever PanSou is slow to respond.
        request_budget = max(1.0, float(timeout) - poll_seconds * (attempts - 1))
        collected: dict[tuple[str, str], dict] = {}
        last_error = ""
        last_method = "GET"
        previous_count: int | None = None

        for attempt in range(attempts):
            remaining_attempts = attempts - attempt
            request_timeout = max(1, math.ceil(request_budget / remaining_attempts))
            data, error, method = self._search_once(base, options, request_timeout)
            request_budget = max(0.0, request_budget - request_timeout)
            last_method = method
            if data is None:
                last_error = error or last_error or "request_failed"
            else:
                api_error = str(data.get("error") or data.get("message") or "") if data.get("code") else ""
                if api_error:
                    last_error = api_error
                for item in normalize_pansou_results(data, limit=1000):
                    key = (str(item.get("cloud_type") or ""), normalize_share_url(str(item.get("share_url") or "")))
                    if key[0] and key[1] and key not in collected:
                        collected[key] = item

            # Otherwise a later call can contain links from PanSou async plugins.
            if attempt + 1 >= attempts:
                break
            if data is not None:
                # The count check is intentionally based on the aggregate set.
                # A stable successful response means the async result stream
                # settled; an error never converts prior evidence into a miss.
                current_count = len(collected)
                # A pair of empty snapshots is normal while PanSou starts
                # asynchronous channel/plugin searches.  It is not evidence
                # that the search has settled, so keep polling the configured
                # window until at least one resource has arrived.
                if current_count > 0 and previous_count == current_count:
                    break
                previous_count = current_count
            if poll_seconds:
                time.sleep(poll_seconds)

        # Do not expose a transient error as a negative result when an earlier
        # poll already produced usable evidence.
        if collected:
            balanced = _fair_limit_by_cloud_type(list(collected.values()), limit)
            return PansouSearchResponse(keyword, balanced, "", last_method)
        return PansouSearchResponse(keyword, [], last_error or "request_failed", last_method)

    def list_telegram_channels(self, timeout: int = 20) -> "PansouChannelListResponse":
        """Read the Telegram channels configured by the PanSou instance."""
        base = self.settings.pansou_url.rstrip("/")
        if not base:
            return PansouChannelListResponse([], "not_configured")
        data, error = self._read_health(base, max(1, int(timeout)))
        if data is None:
            return PansouChannelListResponse([], error or "request_failed")
        if not isinstance(data.get("channels"), list):
            return PansouChannelListResponse([], "channels_not_exposed")
        return PansouChannelListResponse(collect_pansou_configured_channels(data), "")

    def _read_health(self, base: str, timeout: int) -> tuple[dict | None, str]:
        try:
            req = urllib.request.Request(f"{base}/api/health", headers=self._headers(), method="GET")
            with open_url(req, timeout=timeout) as resp:
                return _load_pansou_json(resp.read()), ""
        except urllib.error.HTTPError as exc:
            return None, f"http_{exc.code}"
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return None, "timeout"
            return None, f"connection_error:{type(exc.reason).__name__}"
        except TimeoutError:
            return None, "timeout"
        except json.JSONDecodeError:
            return None, "invalid_json"
        except Exception as exc:
            return None, f"request_error:{type(exc).__name__}"

    def _search_once(self, base: str, options: dict, timeout: int) -> tuple[dict | None, str, str]:
        data, get_error = self._search_native_get(base, options, timeout)
        method = "GET"
        error = get_error
        if data is None and _should_retry_post(get_error):
            data, error = self._search_native_post(base, options, timeout)
            method = "POST"
        return data, error, method

    def _headers(self, content_type: bool = False) -> dict:
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = "application/json"
        if self.settings.pansou_token:
            headers["Authorization"] = f"Bearer {self.settings.pansou_token}"
        return headers

    def _search_native_get(self, base: str, options: dict, timeout: int) -> tuple[dict | None, str]:
        params = {}
        for key, value in options.items():
            if isinstance(value, list):
                params[key] = ",".join(str(item) for item in value)
            elif isinstance(value, dict):
                params[key] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(value, bool):
                params[key] = str(value).lower()
            else:
                params[key] = value
        url = f"{base}/api/search?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers=self._headers(), method="GET")
            with open_url(req, timeout=timeout) as resp:
                return _load_pansou_json(resp.read()), ""
        except urllib.error.HTTPError as exc:
            return None, f"http_{exc.code}"
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return None, "timeout"
            return None, f"connection_error:{type(exc.reason).__name__}"
        except TimeoutError:
            return None, "timeout"
        except json.JSONDecodeError:
            return None, "invalid_json"
        except Exception as exc:
            return None, f"request_error:{type(exc).__name__}"

    def _search_native_post(self, base: str, options: dict, timeout: int) -> tuple[dict | None, str]:
        body = json.dumps(options, ensure_ascii=False).encode("utf-8")
        try:
            req = urllib.request.Request(
                f"{base}/api/search",
                data=body,
                headers=self._headers(content_type=True),
                method="POST",
            )
            with open_url(req, timeout=timeout) as resp:
                return _load_pansou_json(resp.read()), ""
        except urllib.error.HTTPError as exc:
            return None, f"http_{exc.code}"
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return None, "timeout"
            return None, f"connection_error:{type(exc.reason).__name__}"
        except TimeoutError:
            return None, "timeout"
        except json.JSONDecodeError:
            return None, "invalid_json"
        except Exception as exc:
            return None, f"request_error:{type(exc).__name__}"


@dataclass(frozen=True)
class PansouSearchResponse:
    query: str
    items: list[dict]
    error: str = ""
    method: str = "GET"


def _search_lock(cache_key: tuple) -> threading.Lock:
    with _SEARCH_CACHE_GUARD:
        return _SEARCH_LOCKS.setdefault(cache_key, threading.Lock())


def _cached_search(cache_key: tuple, *, require_refresh: bool = False) -> PansouSearchResponse | None:
    now = time.monotonic()
    with _SEARCH_CACHE_GUARD:
        _prune_search_cache(now)
        cached = _SEARCH_CACHE.get(cache_key)
        if cached is None:
            return None
        created_at, response, _settings, refreshed = cached
        if require_refresh and (not refreshed or now - created_at > _REFRESH_COALESCE_SECONDS):
            return None
    return _copy_search_response(response)


def _prune_search_cache(now: float) -> None:
    expired = [
        key
        for key, (created_at, _response, _settings, _refreshed) in _SEARCH_CACHE.items()
        if now - created_at > _SEARCH_CACHE_TTL_SECONDS
    ]
    for key in expired:
        _SEARCH_CACHE.pop(key, None)


def _copy_search_response(response: PansouSearchResponse) -> PansouSearchResponse:
    return PansouSearchResponse(
        response.query,
        [dict(item) for item in response.items],
        response.error,
        response.method,
    )


@dataclass(frozen=True)
class PansouChannelListResponse:
    sources: list[dict]
    error: str = ""


def _should_retry_post(error: str) -> bool:
    return error in {"http_400", "http_404", "http_405", "http_415", "http_422"}


def _load_pansou_json(raw: bytes) -> dict:
    """PanSou results may contain isolated invalid bytes from scraped source text."""
    return json.loads(raw.decode("utf-8", errors="replace"))


def normalize_pansou_results(data: dict, limit: int) -> list[dict]:
    items = collect_pansou_items(data)
    results = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("share_url") or item.get("shareurl") or "").strip()
        cloud_type, provider = infer_share_provider(url, str(item.get("type") or item.get("cloud_type") or ""))
        normalized_url = normalize_share_url(url)
        dedupe_key = (cloud_type, normalized_url)
        if not cloud_type or not normalized_url or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        results.append(
            {
                "share_url": url,
                "cloud_type": cloud_type,
                "provider": provider,
                "title": item.get("note") or item.get("work_title") or item.get("title") or item.get("name") or "",
                "content": item.get("content") or "",
                "source": item.get("source") or item.get("channel") or "",
                "datetime": item.get("datetime") or "",
            }
        )
    return _fair_limit_by_cloud_type(results, limit)


def _fair_limit_by_cloud_type(results: list[dict], limit: int) -> list[dict]:
    """Keep a large result type from starving another enabled provider.

    PanSou's merged response is grouped by cloud type.  A simple global slice
    can therefore consume the whole limit with Quark links before any 115 link
    is seen.  Round-robin selection preserves PanSou's ordering within each
    cloud type while guaranteeing representation for every returned type.
    """
    if limit <= 0:
        return []
    if len(results) <= limit:
        return results

    buckets: dict[str, list[dict]] = {}
    for item in results:
        cloud_type = str(item.get("cloud_type") or "")
        buckets.setdefault(cloud_type, []).append(item)

    selected: list[dict] = []
    offsets = {cloud_type: 0 for cloud_type in buckets}
    while len(selected) < limit:
        added = False
        for cloud_type, bucket in buckets.items():
            offset = offsets[cloud_type]
            if offset >= len(bucket):
                continue
            selected.append(bucket[offset])
            offsets[cloud_type] = offset + 1
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
    return selected


def collect_pansou_items(data: object) -> list[dict]:
    if not isinstance(data, dict):
        return []
    payload = data.get("data", data)
    if not isinstance(payload, dict):
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    items: list[dict] = []
    # Raw results carry message title/content and work_title. Keep them before
    # merged links so URL de-duplication preserves the richer evidence.
    raw_results = payload.get("results") or []
    if isinstance(raw_results, list):
        for result in raw_results:
            if not isinstance(result, dict):
                continue
            for link in result.get("links") or []:
                if not isinstance(link, dict) or str(link.get("type") or "").casefold() not in {"quark", "115"}:
                    continue
                items.append(
                    {
                        **link,
                        "title": link.get("work_title") or result.get("title") or "",
                        "content": result.get("content") or "",
                        "source": f"tg:{result.get('channel') or ''}".rstrip(":"),
                        "datetime": link.get("datetime") or result.get("datetime") or "",
                    }
                )

    merged = payload.get("merged_by_type") or payload.get("mergedByType") or {}
    if isinstance(merged, dict):
        for cloud_type, aliases in (("quark", ("quark", "Quark")), ("115", ("115",))):
            values = next((merged.get(alias) for alias in aliases if merged.get(alias)), [])
            if isinstance(values, list):
                items.extend({**item, "type": item.get("type") or cloud_type} for item in values if isinstance(item, dict))

    for key in ("list", "items", "records"):
        values = payload.get(key)
        if isinstance(values, list):
            items.extend(item for item in values if isinstance(item, dict))
    return items


def collect_pansou_configured_channels(data: object) -> list[dict]:
    """Collect only PanSou's configured ``/api/health`` channel list."""
    if not isinstance(data, dict):
        return []
    values = data.get("channels")
    if not isinstance(values, list):
        return []
    sources: list[dict] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        sources.append({"raw_value": value, "evidence_field": "health.channels"})
    return sources


def enabled_pansou_cloud_types() -> list[str]:
    providers = set(get_settings().enabled_provider_keys())
    values: list[str] = []
    if "quark" in providers or "qas" in providers:
        values.append("quark")
    if "p115" in providers or "moviepilot_115" in providers:
        values.append("115")
    return values or ["quark"]


def infer_share_provider(url: str, hint: str = "") -> tuple[str, str]:
    try:
        hostname = (urlsplit(url).hostname or "").casefold()
    except ValueError:
        hostname = ""
    if hostname == "pan.quark.cn" or hostname.endswith(".pan.quark.cn"):
        return "quark", "quark"
    if (
        hostname in {"115.com", "115cdn.com"}
        or hostname.endswith(".115.com")
        or hostname.endswith(".115cdn.com")
    ):
        return "115", "p115"
    return "", ""


def normalize_share_url(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.casefold()
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), f"{host}{port}", path, parsed.query, parsed.fragment))
