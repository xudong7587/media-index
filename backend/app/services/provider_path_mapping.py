from __future__ import annotations

from pathlib import PurePosixPath


def map_provider_save_path(save_path: str, source_provider: str, target_provider: str, settings) -> str:
    """Map one logical provider path to the corresponding path on another provider."""
    source_root = PurePosixPath(str(settings.provider_save_root(source_provider) or "/")).as_posix().rstrip("/") or "/"
    target_root = PurePosixPath(str(settings.provider_save_root(target_provider) or "/")).as_posix().rstrip("/") or "/"
    normalized_save_path = PurePosixPath(str(save_path or "/")).as_posix()
    if source_root != "/" and (
        normalized_save_path == source_root or normalized_save_path.startswith(f"{source_root}/")
    ):
        relative = normalized_save_path[len(source_root):].lstrip("/")
    else:
        relative = normalized_save_path.lstrip("/")
    if relative and target_root != "/":
        return f"{target_root.rstrip('/')}/{relative}"
    return f"/{relative}" if relative else target_root
