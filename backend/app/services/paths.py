from app.core.config import get_settings


def media_folder(media_type: str) -> str:
    settings = get_settings()
    path = settings.category_paths().get(media_type, f"/{media_type}")
    return path.strip("/")


def build_save_path(target: str, media_type: str, title: str, year: str = "", season: int | None = None) -> str:
    roots = get_settings().roots()
    root = roots.local if target == "local" else roots.cloud
    base = f"{root}/{media_folder(media_type)}/{title}"
    if year:
        base += f" ({year})"
    if media_type in ("tv", "variety") and season:
        base += f"/Season {season:02d}"
    return base
