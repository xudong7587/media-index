from __future__ import annotations

from dataclasses import dataclass
import re

from app.domain.media import SourceFile


@dataclass(frozen=True)
class ShareInspection:
    valid: bool
    share_url: str
    files: tuple[SourceFile, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class SeasonShareFolder:
    season_number: int
    name: str
    share_url: str


def find_season_share_folders(qas, share_url: str, *, max_depth: int = 2) -> tuple[SeasonShareFolder, ...]:
    """Discover season directories without downloading or exposing share contents."""
    base_url = share_url.split("#", 1)[0]
    queue = [(share_url, 0)]
    seen_urls: set[str] = set()
    found: dict[int, SeasonShareFolder] = {}
    while queue:
        current_url, depth = queue.pop(0)
        if current_url in seen_urls:
            continue
        seen_urls.add(current_url)
        try:
            detail = qas.share_detail(current_url)
        except Exception:
            continue
        for item in _share_items(detail):
            if not item.get("dir") or not item.get("fid"):
                continue
            name = str(item.get("file_name") or item.get("name") or "").strip()
            child_url = f"{base_url}#/list/share/{item['fid']}"
            season_number = parse_season_folder_number(name)
            if season_number is not None:
                found.setdefault(season_number, SeasonShareFolder(season_number, name, child_url))
            elif depth < max_depth:
                queue.append((child_url, depth + 1))
    return tuple(found[number] for number in sorted(found))


def _share_items(detail: object) -> list[dict]:
    if not isinstance(detail, dict) or detail.get("success") is False:
        return []
    payload = detail.get("data", detail)
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict) or data.get("error"):
        return []
    items = data.get("list") or data.get("files") or []
    return [item for item in items if isinstance(item, dict)]


_ARABIC_SEASON = re.compile(r"(?i)(?:^|[^a-z0-9])(?:s|season)[ ._-]*0*(\d{1,2})(?!\d)")
_CHINESE_SEASON = re.compile(r"第\s*([一二三四五六七八九十两\d]{1,3})\s*季")
_SEASON_RANGE = re.compile(r"(?i)(?:s|season)\s*0*\d{1,2}\s*[-~至到]\s*(?:s|season)?\s*0*\d{1,2}")


def parse_season_folder_number(name: str) -> int | None:
    if _SEASON_RANGE.search(name):
        return None
    arabic = _ARABIC_SEASON.search(name)
    if arabic:
        return int(arabic.group(1))
    chinese = _CHINESE_SEASON.search(name)
    if not chinese:
        return None
    token = chinese.group(1)
    if token.isdigit():
        return int(token)
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if token == "十":
        return 10
    if "十" in token:
        left, right = token.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(token)


def inspect_share(qas, share_url: str, *, max_directory_depth: int = 2) -> ShareInspection:
    if not share_url:
        return ShareInspection(False, share_url, error="empty_share_url")
    try:
        detail = qas.share_detail(share_url)
    except Exception as exc:
        return ShareInspection(False, share_url, error=f"share_detail_failed:{exc}")
    inspection = parse_share_detail(detail, share_url)
    depth = 0
    while (
        not inspection.valid
        and inspection.error == "share_contains_no_files"
        and inspection.share_url != share_url
        and depth < max_directory_depth
    ):
        share_url = inspection.share_url
        depth += 1
        try:
            detail = qas.share_detail(share_url)
        except Exception as exc:
            return ShareInspection(False, share_url, error=f"share_detail_failed:{exc}")
        inspection = parse_share_detail(detail, share_url)
    return inspection


def parse_share_detail(detail: object, share_url: str) -> ShareInspection:
    if not isinstance(detail, dict):
        return ShareInspection(False, share_url, error="invalid_share_response")
    payload = detail.get("data", detail)
    if detail.get("success") is False:
        nested_error = payload.get("error") if isinstance(payload, dict) else ""
        return ShareInspection(
            False,
            share_url,
            error=f"share_error:{nested_error or detail.get('message') or 'share_invalid'}",
        )
    if isinstance(payload, dict) and payload.get("error"):
        return ShareInspection(False, share_url, error=f"share_error:{payload['error']}")
    if isinstance(payload, dict) and payload.get("success") is False:
        return ShareInspection(False, share_url, error=str(payload.get("message") or "share_invalid"))
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return ShareInspection(False, share_url, error="invalid_share_payload")

    share = data.get("share") or {}
    first_file = data.get("first_file") or (share.get("first_file") if isinstance(share, dict) else {}) or {}
    raw_files = data.get("files") or data.get("list") or []
    if not raw_files and first_file:
        raw_files = [first_file]

    files: list[SourceFile] = []
    for item in raw_files:
        if not isinstance(item, dict) or item.get("dir"):
            continue
        name = str(item.get("file_name") or item.get("name") or "").strip()
        if not name:
            continue
        try:
            size = int(item.get("size") or item.get("file_size") or 0)
        except (TypeError, ValueError):
            size = 0
        path = str(item.get("path") or item.get("file_path") or name)
        files.append(SourceFile(name=name, size=size, path=path))

    fid = data.get("first_fid") or (share.get("first_fid") if isinstance(share, dict) else "") or first_file.get("fid") or ""
    is_dir = bool(first_file.get("dir")) if isinstance(first_file, dict) else False
    resolved_url = share_url
    if is_dir and fid and "#/list/share/" not in share_url:
        resolved_url = share_url.split("#", 1)[0] + f"#/list/share/{fid}"
    if not files:
        return ShareInspection(False, resolved_url, error="share_contains_no_files")
    return ShareInspection(True, resolved_url, tuple(files))
