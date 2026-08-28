from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Iterable

from app.domain.media import MediaTarget


MEDIA_PLAN_VERSION = "media-plan/v1"


def positive_episode_numbers(values: Iterable[int | str] = ()) -> tuple[int, ...]:
    """Return one stable, positive episode-number set for every entrypoint."""
    result: set[int] = set()
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.add(number)
    return tuple(sorted(result))


@dataclass(frozen=True)
class EpisodeCoverage:
    total_episode_numbers: tuple[int, ...] = ()
    aired_episode_numbers: tuple[int, ...] = ()
    available_episode_numbers: tuple[int, ...] = ()
    transferred_episode_numbers: tuple[int, ...] = ()

    @property
    def missing_episode_numbers(self) -> tuple[int, ...]:
        return tuple(sorted(set(self.aired_episode_numbers) - set(self.available_episode_numbers)))

    @property
    def pending_transfer_episode_numbers(self) -> tuple[int, ...]:
        return tuple(sorted(set(self.available_episode_numbers) - set(self.transferred_episode_numbers)))

    def as_dict(self) -> dict:
        return {
            "total": len(self.total_episode_numbers),
            "aired": len(self.aired_episode_numbers),
            "available": len(self.available_episode_numbers),
            "transferred": len(self.transferred_episode_numbers),
            "missing": len(self.missing_episode_numbers),
            "pending_transfer": len(self.pending_transfer_episode_numbers),
            "total_episode_numbers": list(self.total_episode_numbers),
            "aired_episode_numbers": list(self.aired_episode_numbers),
            "available_episode_numbers": list(self.available_episode_numbers),
            "transferred_episode_numbers": list(self.transferred_episode_numbers),
            "missing_episode_numbers": list(self.missing_episode_numbers),
            "pending_transfer_episode_numbers": list(self.pending_transfer_episode_numbers),
        }


def build_episode_coverage(
    *,
    total: Iterable[int | str] = (),
    aired: Iterable[int | str] = (),
    available: Iterable[int | str] = (),
    transferred: Iterable[int | str] = (),
) -> EpisodeCoverage:
    total_numbers = positive_episode_numbers(total)
    aired_numbers = positive_episode_numbers(aired)
    available_numbers = positive_episode_numbers(available)
    transferred_numbers = positive_episode_numbers(transferred)
    # Inputs from a source inspection can reveal episodes missing from an old
    # TMDB season payload. Never hide that evidence from the read model.
    total_numbers = positive_episode_numbers((*total_numbers, *aired_numbers, *available_numbers, *transferred_numbers))
    aired_numbers = positive_episode_numbers((*aired_numbers, *transferred_numbers))
    available_numbers = positive_episode_numbers((*available_numbers, *transferred_numbers))
    return EpisodeCoverage(total_numbers, aired_numbers, available_numbers, transferred_numbers)


def target_episode_coverage(
    target: MediaTarget,
    *,
    available: Iterable[int | str] = (),
    transferred: Iterable[int | str] = (),
    today: date | None = None,
) -> EpisodeCoverage:
    current_date = (today or date.today()).isoformat()
    total = (episode.episode_number for episode in target.episodes)
    aired = (
        episode.episode_number
        for episode in target.episodes
        if not episode.air_date or episode.air_date <= current_date
    )
    return build_episode_coverage(total=total, aired=aired, available=available, transferred=transferred)


def media_identity(
    target: MediaTarget | None = None,
    *,
    tmdb_id: int = 0,
    media_type: str = "movie",
    category: str = "",
    title: str = "",
    year: str = "",
    season_number: int | None = None,
) -> dict:
    if target is not None:
        tmdb_id = target.tmdb_id
        media_type = target.media_type
        category = target.category
        title = target.title
        year = target.season_year or target.series_year
        season_number = target.season_number
    return {
        "tmdb_id": int(tmdb_id or 0),
        "media_type": str(media_type or "movie").strip().lower(),
        "category": str(category or "").strip().lower(),
        "title": str(title or "").strip(),
        "year": str(year or "").strip()[:4],
        "season_number": int(season_number) if season_number is not None else None,
    }


def build_media_plan(
    *,
    entrypoint: str,
    provider: str = "",
    target: MediaTarget | None = None,
    identity: dict | None = None,
    episode_numbers: Iterable[int | str] = (),
    preferred_share_urls: Iterable[str] = (),
    coverage: EpisodeCoverage | None = None,
    ttl_seconds: int | None = None,
) -> dict:
    now = datetime.now(UTC)
    normalized_urls = list(dict.fromkeys(str(value or "").strip() for value in preferred_share_urls if str(value or "").strip()))[:100]
    normalized_identity = media_identity(target, **(identity or {})) if target is not None or identity else media_identity()
    plan = {
        "version": MEDIA_PLAN_VERSION,
        "entrypoint": str(entrypoint or "unknown").strip().lower(),
        "provider": str(provider or "").strip().lower(),
        "identity": normalized_identity,
        "episode_numbers": list(positive_episode_numbers(episode_numbers)),
        "preferred_share_urls": normalized_urls,
        "coverage": (coverage or EpisodeCoverage()).as_dict(),
        "generated_at": now.isoformat(),
    }
    if ttl_seconds is not None and int(ttl_seconds) > 0:
        plan["expires_at"] = (now + timedelta(seconds=int(ttl_seconds))).isoformat()
    return plan
