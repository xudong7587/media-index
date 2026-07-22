import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings
from app.clients.http import open_url


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
        base = self.settings.pansou_url.rstrip("/")
        if not keyword.strip():
            return PansouSearchResponse(keyword, [], "empty_keyword")
        if not base:
            return PansouSearchResponse(keyword, [], "not_configured")
        options = {
            "kw": keyword,
            "cloud_types": enabled_pansou_cloud_types(),
            "res": result_mode,
            "conc": max(1, min(self.settings.pansou_concurrency, 100)),
            "refresh": refresh,
        }
        if title_en:
            options["ext"] = {"title_en": title_en, "is_all": True}
        if exclude:
            options["filter"] = {"exclude": list(exclude)}

        data, get_error = self._search_native_get(base, options, timeout)
        method = "GET"
        error = get_error
        if data is None and _should_retry_post(get_error):
            data, error = self._search_native_post(base, options, timeout)
            method = "POST"
        if data is None:
            return PansouSearchResponse(keyword, [], error or "request_failed", method)
        api_error = str(data.get("error") or data.get("message") or "") if data.get("code") else ""
        return PansouSearchResponse(keyword, normalize_pansou_results(data, limit), api_error, method)

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
        if len(results) >= limit:
            break
    return results


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


def enabled_pansou_cloud_types() -> list[str]:
    providers = set(get_settings().enabled_provider_keys())
    values: list[str] = []
    if "qas" in providers:
        values.append("quark")
    if "moviepilot_115" in providers:
        values.append("115")
    return values or ["quark"]


def infer_share_provider(url: str, hint: str = "") -> tuple[str, str]:
    try:
        hostname = (urlsplit(url).hostname or "").casefold()
    except ValueError:
        hostname = ""
    if hostname == "pan.quark.cn" or hostname.endswith(".pan.quark.cn"):
        return "quark", "qas"
    if hostname == "115.com" or hostname.endswith(".115.com") or hostname.endswith(".115cdn.com"):
        return "115", "moviepilot_115"
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
