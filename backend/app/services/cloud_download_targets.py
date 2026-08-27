from __future__ import annotations

from dataclasses import dataclass

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.core.config import get_settings
from app.services.paths import cloud_download_scope_from_child, normalize_cloud_root


@dataclass(frozen=True)
class CloudDownloadTarget:
    provider: str
    child_name: str
    path: str


def list_cloud_download_targets(provider: str) -> tuple[CloudDownloadTarget, ...]:
    """List the real direct children of one configured cloud-download root."""
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider not in {"p115", "quark"}:
        raise ValueError("互动云下载目录只支持 115 或夸克")
    settings = get_settings()
    root = normalize_cloud_root(settings.provider_cloud_download_path(normalized_provider))
    library_root = settings.provider_save_root(normalized_provider)
    try:
        if normalized_provider == "p115":
            client = P115Client()
            directory_id = client.directory_id(root)
            if directory_id == "0" and root != "/":
                return ()
            entries = client.list_directory_complete(directory_id)
        else:
            client = QuarkClient()
            directory_id = client.directory_id(root)
            if not directory_id:
                return ()
            entries = client.list_directory_complete(directory_id)
    except (P115Error, QuarkError) as exc:
        raise RuntimeError(str(exc)) from exc

    from app.services.cloud_download_organizer import _scope_mapping_is_safe

    targets: list[CloudDownloadTarget] = []
    seen: set[str] = set()
    for entry in entries:
        child_name = str(getattr(entry, "name", "") or "").strip()
        if not bool(getattr(entry, "is_dir", False)) or child_name in seen:
            continue
        path = cloud_download_scope_from_child(normalized_provider, child_name, settings=settings)
        if not path:
            continue
        # Keep the choice contract aligned with the organizer's source/target
        # overlap guard.  Offering a directory that can never be organized
        # would strand a successful interaction transfer in staging.
        if not _scope_mapping_is_safe(root, library_root, path):
            continue
        seen.add(child_name)
        targets.append(CloudDownloadTarget(normalized_provider, child_name, path))
    return tuple(sorted(targets, key=lambda item: item.child_name.casefold()))
