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
    return _inspect_share_tree(qas, share_url, max_directory_depth=max_directory_depth)


def _inspect_share_tree(qas, share_url: str, *, max_directory_depth: int, depth: int = 0, seen: set[str] | None = None) -> ShareInspection:
    visited = seen if seen is not None else set()
    if share_url in visited:
        return ShareInspection(False, share_url, error="share_directory_cycle")
    visited.add(share_url)
    try:
        detail = qas.share_detail(share_url)
    except Exception as exc:
        return ShareInspection(False, share_url, error=f"share_detail_failed:{exc}")

    inspection = parse_share_detail(detail, share_url)
    if depth >= max_directory_depth:
        return inspection

    child_urls = _share_directory_urls(detail, share_url)
    if not child_urls:
        return inspection

    leaves: list[ShareInspection] = []
    # Keep direct files and child folders together. This is useful for a
    # share that has a few root files plus a 4K/1080P directory.
    if inspection.valid:
        leaves.append(inspection)
    for child_url in child_urls:
        child = _inspect_share_tree(qas, child_url, max_directory_depth=max_directory_depth, depth=depth + 1, seen=visited)
        if child.valid:
            leaves.append(child)

    if not leaves:
        return inspection
    deduplicated: dict[tuple[str, str], ShareInspection] = {}
    for leaf in leaves:
        deduplicated.setdefault((leaf.share_url, ",".join(sorted(source.name for source in leaf.files))), leaf)
    leaves = list(deduplicated.values())
    if len(leaves) == 1:
        return leaves[0]
    # A single QAS task must point at one executable folder. Prefer the branch
    # with the most video files, then the highest quality. This keeps a share
    # root containing 4K/1080P folders from mixing duplicate episodes or
    # causing QAS to scan every quality directory.
    return max(leaves, key=_leaf_score)


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
        obj_category = str(item.get("obj_category") or item.get("category") or "").strip()
        files.append(SourceFile(name=name, size=size, path=path, obj_category=obj_category))

    fid = data.get("first_fid") or (share.get("first_fid") if isinstance(share, dict) else "") or first_file.get("fid") or ""
    is_dir = bool(first_file.get("dir")) if isinstance(first_file, dict) else False
    resolved_url = share_url
    if is_dir and fid and "#/list/share/" not in share_url:
        resolved_url = share_url.split("#", 1)[0] + f"#/list/share/{fid}"
    if not files:
        return ShareInspection(False, resolved_url, error="share_contains_no_files")
    return ShareInspection(True, resolved_url, tuple(files))


def _share_directory_urls(detail: object, share_url: str) -> tuple[str, ...]:
    base_url = share_url.split("#", 1)[0]
    urls: list[str] = []
    for item in _share_items(detail):
        if not item.get("dir") or not item.get("fid"):
            continue
        urls.append(f"{base_url}#/list/share/{item['fid']}")
    payload = detail.get("data", detail) if isinstance(detail, dict) else {}
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    first_file = data.get("first_file") if isinstance(data, dict) else None
    first_fid = data.get("first_fid") if isinstance(data, dict) else None
    if isinstance(first_file, dict) and first_file.get("dir") and first_file.get("fid"):
        urls.append(f"{base_url}#/list/share/{first_file['fid']}")
    elif first_fid:
        urls.append(f"{base_url}#/list/share/{first_fid}")
    return tuple(dict.fromkeys(urls))


def _leaf_score(inspection: ShareInspection) -> tuple[int, int, int]:
    videos = [source for source in inspection.files if source.obj_category in {"", "video"} and "." in source.name]
    quality = sum(
        (8 if "2160p" in source.name.casefold() or "4k" in source.name.casefold() else 5 if "1080p" in source.name.casefold() else 0)
        for source in videos
    )
    return (len(videos), quality, sum(source.size for source in videos))
