from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.domain.media import MediaTarget
from app.services.media_target import resolve_media_target


def resolve_wishlist_target(
    tmdb_id: int,
    media_type: str,
    season_number: int | None = None,
    *,
    tmdb: TmdbClient | None = None,
) -> MediaTarget:
    client = tmdb or TmdbClient()
    resolved_season = season_number
    if media_type in {"tv", "variety"} and resolved_season is None:
        detail = client.details(media_type, tmdb_id)
        seasons = [
            int(item.get("season_number") or 0)
            for item in detail.get("seasons", [])
            if int(item.get("season_number") or 0) > 0
        ]
        if not seasons:
            raise ValueError("TMDB 没有可用的季度信息")
        resolved_season = max(seasons)
    return resolve_media_target(tmdb_id, media_type, resolved_season, client)


def compute_wishlist_next_check(
    target: MediaTarget,
    check_hour: int = 9,
    now: datetime | None = None,
    *,
    timezone_name: str | None = None,
) -> tuple[str, str]:
    settings = get_settings()
    zone = ZoneInfo(timezone_name or settings.tracking_timezone)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(zone)
    hour = max(0, min(int(check_hour), 23))

    tmdb_dates: list[date] = []
    if target.media_type == "movie":
        parsed = _parse_date(target.release_date)
        if parsed:
            tmdb_dates.append(parsed)
    else:
        tmdb_dates.extend(
            parsed
            for episode in target.episodes
            if (parsed := _parse_date(episode.air_date)) is not None
        )

    future_dates = sorted(value for value in tmdb_dates if value > local_now.date())
    has_due_content = not tmdb_dates or any(value <= local_now.date() for value in tmdb_dates)
    if has_due_content:
        check_date = local_now.date()
        local_check = datetime.combine(check_date, time(hour=hour), tzinfo=zone)
        if local_check <= local_now:
            local_check += timedelta(days=1)
        tmdb_date = max((value for value in tmdb_dates if value <= local_now.date()), default=None)
    elif future_dates:
        check_date = future_dates[0]
        local_check = datetime.combine(check_date, time(hour=hour), tzinfo=zone)
        tmdb_date = check_date
    else:
        local_check = datetime.combine(local_now.date() + timedelta(days=1), time(hour=hour), tzinfo=zone)
        tmdb_date = None

    return (
        local_check.astimezone(timezone.utc).isoformat(timespec="seconds"),
        tmdb_date.isoformat() if tmdb_date else "",
    )


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None
