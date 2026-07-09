import json
import urllib.parse
import urllib.request

from app.core.config import get_settings


class PansouClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def configured(self) -> bool:
        return bool(self.settings.pansou_url)

    def search(self, keyword: str, limit: int = 10, timeout: int = 20) -> list[dict]:
        base = self.settings.pansou_url.rstrip("/")
        body = json.dumps(
            {
                "kw": keyword,
                "cloud_types": ["quark"],
                "res": "merge",
                "conc": 4,
                "refresh": False,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.settings.pansou_token:
            headers["Authorization"] = f"Bearer {self.settings.pansou_token}"
        try:
            req = urllib.request.Request(f"{base}/api/search", data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            try:
                url = f"{base}/api/search?kw={urllib.parse.quote(keyword)}"
                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                return []
        return normalize_pansou_results(data, limit)


def normalize_pansou_results(data: dict, limit: int) -> list[dict]:
    payload = data.get("data", data)
    merged = payload.get("merged_by_type", {}) if isinstance(payload, dict) else {}
    items = merged.get("quark", [])
    if not items and isinstance(payload, dict):
        items = payload.get("results") or payload.get("list") or []
    results = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("shareurl") or ""
        if "pan.quark.cn" not in url or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "share_url": url,
                "title": item.get("note") or item.get("title") or item.get("name") or "",
                "source": item.get("source") or "",
            }
        )
        if len(results) >= limit:
            break
    return results
