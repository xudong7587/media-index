from app.core.config import get_settings
from app.services.episode_matcher import sanitize_filename_component


def media_folder(media_type: str, provider: str = "qas") -> str:
    settings = get_settings()
    path = settings.provider_category_paths(provider).get(media_type, f"/{media_type}")
    return _relative_path(path)


def build_save_path(
    target: str,
    media_type: str,
    title: str,
    year: str = "",
    season: int | None = None,
    provider: str = "qas",
) -> str:
    if target not in {"cloud", "local"}:
        raise ValueError(f"unsupported save target: {target}")
    settings = get_settings()
    root = _absolute_root(
        settings.provider_local_root(provider)
        if target == "local"
        else settings.provider_save_root(provider)
    )
    safe_title = sanitize_filename_component(title)
    base = f"{root}/{media_folder(media_type, provider)}/{safe_title}"
    if year:
        base += f"({sanitize_filename_component(year)})"
    return base


def is_allowed_save_path(
    media_type: str,
    path: str,
    target: str | None = None,
    provider: str = "qas",
) -> bool:
    try:
        normalized = _absolute_path(path)
        settings = get_settings()
        category = media_folder(media_type, provider)
        roots_by_target = {
            "cloud": settings.provider_save_root(provider),
            "local": settings.provider_local_root(provider),
        }
        if target is not None and target not in roots_by_target:
            return False
        selected_roots = roots_by_target.values() if target is None else (roots_by_target[target],)
        prefixes = tuple(f"{normalize_save_root(root)}/{category}/" for root in selected_roots)
        return any(normalized.startswith(prefix) and len(normalized) > len(prefix) for prefix in prefixes)
    except ValueError:
        return False


def _absolute_root(value: str) -> str:
    return normalize_save_root(value)


def normalize_save_root(value: str) -> str:
    normalized = _absolute_path(value)
    if normalized == "/":
        raise ValueError("save root cannot be filesystem root")
    return normalized


def _absolute_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw.startswith("/"):
        raise ValueError("save path must be absolute")
    parts = [part for part in raw.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("save path cannot contain dot segments")
    return "/" + "/".join(parts)


def _relative_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("category path must contain safe relative segments")
    return "/".join(parts)
