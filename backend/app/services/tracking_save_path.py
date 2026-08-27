from __future__ import annotations

from app.services.paths import build_save_path, is_allowed_save_path, normalize_save_root


def resolve_tracking_save_path(
    current_path: str,
    *,
    save_target: str,
    media_type: str,
    title: str,
    year: str,
    season_number: int,
    provider: str,
) -> str:
    """Keep a safe user-selected path; otherwise rebuild the canonical target."""
    if current_path and is_allowed_save_path(media_type, current_path, save_target, provider):
        return normalize_save_root(current_path)
    return build_save_path(
        save_target,
        media_type,
        title,
        year,
        season_number,
        provider,
    )
