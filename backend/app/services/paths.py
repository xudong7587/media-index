from string import Formatter

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
    folder_name = build_media_folder_name(title, year)
    base = f"{root}/{media_folder(media_type, provider)}/{folder_name}"
    if settings.season_subdirectory_enabled and season and media_type != "movie":
        base += f"/{build_season_folder_name(season)}"
    return base


def build_cloud_download_staging_path(
    provider: str,
    child_name: str,
    media_type: str,
    title: str,
    year: str = "",
    season: int | None = None,
) -> str:
    """Build one media-specific path below a selected download-root child.

    ``child_name`` is deliberately one provider-listed path segment, not an
    arbitrary destination supplied by an API caller.  The server rebuilds the
    configured root/child path before adding a media-specific folder, which
    prevents episode progress checks from reading unrelated loose files that
    share the category directory.
    """
    selected = cloud_download_scope_from_child(provider, child_name)
    if not selected:
        raise ValueError("cloud download scope must be a configured direct child")
    base = f"{selected.rstrip('/')}/{build_media_folder_name(title, year)}"
    if get_settings().season_subdirectory_enabled and season and media_type != "movie":
        base += f"/{build_season_folder_name(season)}"
    return normalize_save_root(base)


def build_media_folder_name(title: str, year: str = "") -> str:
    settings = get_settings()
    rule = settings.media_folder_naming_rule.strip() or "{title} ({year})"
    if not year:
        rule = rule.replace(" ({year})", "").replace("({year})", "").replace("{year}", "")
    values = {
        "title": sanitize_filename_component(title),
        "year": sanitize_filename_component(year) if year else "",
    }
    return _format_rule(rule, values, fallback=f"{values['title']}{f' ({values['year']})' if values['year'] else ''}")


def build_season_folder_name(season: int) -> str:
    settings = get_settings()
    rule = settings.season_folder_naming_rule.strip() or "Season {season}"
    values = {
        "season": int(season),
    }
    return _format_rule(rule, values, fallback=f"Season {int(season)}")


def validate_naming_rule(rule: str, allowed_fields: set[str]) -> None:
    try:
        parsed = tuple(Formatter().parse(rule))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    fields = {field.split(".", 1)[0].split("[", 1)[0] for _, field, _, _ in parsed if field}
    unknown = fields - allowed_fields
    if unknown:
        raise ValueError(f"unsupported variable: {', '.join(sorted(unknown))}")
    samples = {
        "title": "测试",
        "year": "2026",
        "season": 3,
        "episode": 4,
    }
    try:
        rule.format(**{key: samples[key] for key in allowed_fields if key in samples})
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _format_rule(rule: str, values: dict, fallback: str) -> str:
    try:
        formatted = rule.format(**values)
    except Exception:
        formatted = fallback
    formatted = sanitize_filename_component(str(formatted).strip(" ."))
    return formatted or sanitize_filename_component(fallback)


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


def cloud_download_direct_child_scope(
    provider: str,
    value: str,
    *,
    settings: object | None = None,
) -> str:
    """Return a normalized configured cloud-download direct child or ``""``.

    This is the shared path boundary used by the interaction workflow and the
    native providers.  It intentionally validates structure/configuration only;
    callers that present directory choices must additionally list the real
    provider directory.
    """
    if provider not in {"p115", "quark"}:
        return ""
    resolved_settings = settings or get_settings()
    resolver = getattr(resolved_settings, "provider_cloud_download_path", None)
    if not callable(resolver):
        return ""
    try:
        root = normalize_cloud_root(resolver(provider))
        selected = normalize_save_root(value)
    except (TypeError, ValueError):
        return ""
    prefix = "/" if root == "/" else f"{root.rstrip('/')}/"
    if not selected.startswith(prefix):
        return ""
    relative = selected[len(prefix):]
    return selected if relative and "/" not in relative else ""


def cloud_download_child_name(
    provider: str,
    value: str,
    *,
    settings: object | None = None,
) -> str:
    """Return the single direct-child segment represented by ``value``."""
    resolved_settings = settings or get_settings()
    selected = cloud_download_direct_child_scope(provider, value, settings=resolved_settings)
    resolver = getattr(resolved_settings, "provider_cloud_download_path", None)
    if not selected or not callable(resolver):
        return ""
    try:
        root = normalize_cloud_root(resolver(provider))
    except (TypeError, ValueError):
        return ""
    prefix = "/" if root == "/" else f"{root.rstrip('/')}/"
    return selected[len(prefix):]


def cloud_download_scope_from_child(
    provider: str,
    child_name: str,
    *,
    settings: object | None = None,
) -> str:
    """Rebuild a configured direct-child scope from one safe child segment."""
    child = str(child_name or "").strip()
    if not child or child in {".", ".."} or "/" in child or "\\" in child:
        return ""
    resolved_settings = settings or get_settings()
    resolver = getattr(resolved_settings, "provider_cloud_download_path", None)
    if not callable(resolver):
        return ""
    try:
        root = normalize_cloud_root(resolver(provider))
        candidate = normalize_save_root(f"/{child}" if root == "/" else f"{root.rstrip('/')}/{child}")
    except (TypeError, ValueError):
        return ""
    return cloud_download_direct_child_scope(provider, candidate, settings=resolved_settings)


def is_cloud_download_staging_path(
    provider: str,
    save_path: str,
    child_name: str,
    *,
    settings: object | None = None,
) -> bool:
    """Validate an internally marked plan below one download direct child."""
    selected = cloud_download_scope_from_child(provider, child_name, settings=settings)
    if not selected:
        return False
    try:
        target = normalize_save_root(save_path)
    except ValueError:
        return False
    return target == selected or target.startswith(f"{selected.rstrip('/')}/")


def _absolute_root(value: str) -> str:
    return normalize_save_root(value)


def normalize_save_root(value: str) -> str:
    normalized = _absolute_path(value)
    if normalized == "/":
        raise ValueError("save root cannot be filesystem root")
    return normalized


def normalize_cloud_root(value: str) -> str:
    """Normalize a remote source root, including the provider root itself."""
    return _absolute_path(value)


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
