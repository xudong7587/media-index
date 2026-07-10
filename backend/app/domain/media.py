from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EpisodeTarget:
    season_number: int
    episode_number: int
    air_date: str = ""
    title: str = ""
    match_tokens: tuple[str, ...] = ()
    desc_hint: str = ""


@dataclass(frozen=True)
class MediaTarget:
    tmdb_id: int
    media_type: str
    title: str
    original_title: str = ""
    aliases: tuple[str, ...] = ()
    series_year: str = ""
    season_number: int | None = None
    season_year: str = ""
    status: str = ""
    poster_url: str = ""
    overview: str = ""
    release_date: str = ""
    episodes: tuple[EpisodeTarget, ...] = ()

    @property
    def search_titles(self) -> tuple[str, ...]:
        values = (self.title, self.original_title, *self.aliases)
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(value.strip())
        return tuple(result)


@dataclass(frozen=True)
class SourceFile:
    name: str
    size: int = 0
    path: str = ""


@dataclass(frozen=True)
class EpisodeMatch:
    episode: EpisodeTarget
    source: SourceFile
    score: int
    confidence: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenamePair:
    source_name: str
    pattern: str
    replacement: str
    episode_number: int | None = None
    confidence: str = "high"
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SearchQuery:
    keyword: str
    reason: str
    priority: int


@dataclass(frozen=True)
class ResourceCandidate:
    share_url: str
    title: str = ""
    content: str = ""
    source: str = ""
    published_at: str = ""
    query: str = ""
    score: int = 0
    rejected: bool = False
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinkResolution:
    ok: bool
    stage: str
    message: str
    share_url: str = ""
    source: str = ""
    matches: tuple[EpisodeMatch, ...] = ()
    rename_pairs: tuple[RenamePair, ...] = ()
    reviewed_candidates: tuple[ResourceCandidate, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class QasExecutionResult:
    ok: bool
    stage: str
    message: str
    taskname: str = ""
    executed_pairs: int = 0
    confirmed: bool = False
    outputs: tuple[dict, ...] = ()
