from __future__ import annotations

from dataclasses import dataclass

from app.domain.media import SourceFile


@dataclass(frozen=True)
class ShareInspection:
    valid: bool
    share_url: str
    files: tuple[SourceFile, ...] = ()
    error: str = ""


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
