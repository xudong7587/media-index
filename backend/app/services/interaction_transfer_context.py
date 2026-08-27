from __future__ import annotations

import base64
import binascii
import re

from app.services.paths import cloud_download_scope_from_child


_CLOUD_DOWNLOAD_MARKER = re.compile(r":cloud-download:([A-Za-z0-9_-]+)(?::|$)")
_INTERACTION_SOURCES = {"wecom", "telegram"}


def interaction_cloud_download_execution_marker(child_name: str) -> str:
    child = str(child_name or "").strip()
    if not child:
        raise ValueError("云下载子目录不能为空")
    token = base64.urlsafe_b64encode(child.encode("utf-8")).decode("ascii").rstrip("=")
    return f"cloud-download:{token}"


def resolve_interaction_cloud_download_child(
    *,
    execution_key: str,
    request_source: str,
    provider: str,
) -> str:
    """Recover and revalidate a persisted interaction staging selection."""
    if str(request_source or "").strip().lower() not in _INTERACTION_SOURCES:
        return ""
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider not in {"p115", "quark"}:
        return ""
    match = _CLOUD_DOWNLOAD_MARKER.search(str(execution_key or ""))
    if not match:
        return ""
    token = match.group(1)
    try:
        padded = token + "=" * (-len(token) % 4)
        child = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8").strip()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""
    return child if cloud_download_scope_from_child(normalized_provider, child) else ""
