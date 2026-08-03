from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from app.clients.pansou import infer_share_provider
from app.domain.media import LinkResolution, MediaTarget, ResourceCandidate, SourceFile
from app.services.candidate_ranker import compact
from app.services.episode_matcher import is_source_video
from app.services.movie_matcher import build_movie_rename_pair, choose_movie_file, choose_movie_files
from app.services.share_inspector import ShareInspection


_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_SEASON_EPISODE = re.compile(r"(?i)(?<![a-z0-9])s\d{1,2}[ ._-]*e(?:p|x)?\d{1,4}(?!\d)")
_EPISODE = re.compile(r"(?i)(?<![a-z0-9])e(?:p|x)?\d{1,4}(?!\d)")
_SEASON_MARKER = re.compile(r"第\s*[0-9一二三四五六七八九十]+\s*[季集期]")
_MOVIE_MARKERS = (
    "综艺",
    "纪录片",
    "幕后",
    "特辑",
    "花絮",
    "预告",
    "合集",
    "全集",
    "更新至",
    "幕后特辑",
    "电视剧",
    "剧集",
    "真人秀",
    "脱口秀",
)
_TECHNICAL_MARKERS = re.compile(
    r"(?i)(?:2160p|1080p|720p|4k|8k|uhd|hdr10\+?|hdr|dv|dolby[ ._-]?vision|"
    r"web[-_. ]?dl|webrip|bluray|blu[-_. ]?ray|remux|x26[45]|h[ ._-]?26[45]|"
    r"hevc|avc|10bit|8bit|aac|dts|atmos|中字|国语|英语|双语|字幕)"
)


@dataclass(frozen=True)
class StandardMovieIdentity:
    title: str
    year: str


@dataclass(frozen=True)
class DirectMovieResolution:
    identity: StandardMovieIdentity
    resolution: LinkResolution
    candidate: ResourceCandidate


def parse_standard_movie_identity(value: str, query: str = "") -> StandardMovieIdentity | None:
    """Extract a movie title/year only from an unambiguous PanSou result title."""
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not raw or _looks_non_movie(raw) or (query and _looks_non_movie(query)):
        return None
    years = list(dict.fromkeys(_YEAR.findall(raw)))
    if len(years) != 1:
        return None
    year = years[0]
    year_match = _YEAR.search(raw)
    if not year_match:
        return None
    parts = (raw[: year_match.start()], raw[year_match.end() :])
    titles = [_clean_title(part) for part in parts]
    titles = [title for title in titles if _valid_title(title)]
    if not titles:
        return None
    title = max(titles, key=lambda item: (len(compact(item)), len(item)))
    query_key = compact(query)
    title_key = compact(title)
    if query_key and title_key and query_key not in title_key and title_key not in query_key:
        return None
    return StandardMovieIdentity(title=title, year=year)


def parse_standard_movie_title(value: str, query: str = "") -> str | None:
    """Extract a title when PanSou leaves the year to the verified file name."""
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not raw or _YEAR.search(raw) or _looks_non_movie(raw):
        return None
    title = _clean_title(raw)
    if not _valid_title(title):
        return None
    query_key = compact(query)
    title_key = compact(title)
    if query_key and title_key and query_key not in title_key and title_key not in query_key:
        return None
    return title


def resolve_direct_movie_source(
    query: str,
    candidates: Iterable[dict],
    inspector,
    *,
    provider_key: str = "",
    max_candidates: int = 12,
) -> DirectMovieResolution | None:
    """Verify a high-confidence PanSou movie before any TMDB request."""
    checked = 0
    for item in candidates:
        if checked >= max_candidates:
            break
        share_url = str(item.get("share_url") or "").strip()
        if not share_url:
            continue
        _, candidate_provider = infer_share_provider(share_url, str(item.get("cloud_type") or ""))
        if provider_key and candidate_provider and candidate_provider != provider_key:
            continue
        identity = parse_standard_movie_identity(str(item.get("title") or ""), query)
        if not identity:
            identity = parse_standard_movie_identity(str(item.get("content") or ""), query)
        candidate_title = None if identity else parse_standard_movie_title(str(item.get("title") or ""), query)
        if not identity and not candidate_title:
            continue
        checked += 1
        inspection = _inspect(inspector, share_url)
        if not inspection.valid:
            continue
        year_from_file = False
        if not identity and candidate_title:
            file_years = {
                year
                for source in inspection.files
                if is_source_video(source)
                for year in _YEAR.findall(source.name)
            }
            if len(file_years) != 1:
                continue
            identity = StandardMovieIdentity(candidate_title, next(iter(file_years)))
            year_from_file = True
        target = MediaTarget(
            tmdb_id=0,
            media_type="movie",
            title=identity.title,
            aliases=(query,) if query and compact(query) != compact(identity.title) else (),
            series_year=identity.year,
            category="movie",
        )
        matching_files = tuple(
            source
            for source in inspection.files
            if _file_supports_identity(source, identity, allow_source_title=year_from_file)
        )
        if not matching_files:
            continue
        source, score, reasons, ambiguous = choose_movie_file(
            target,
            list(matching_files),
            str(item.get("title") or ""),
        )
        if not source or ambiguous or score < 35:
            continue
        selected_files, _, selected_reasons = choose_movie_files(
            target,
            list(matching_files),
            str(item.get("title") or ""),
        )
        if not selected_files:
            continue
        pairs = tuple(build_movie_rename_pair(target, file, (*reasons, *selected_reasons)) for file in selected_files)
        candidate = ResourceCandidate(
            share_url=share_url,
            title=str(item.get("title") or ""),
            content=str(item.get("content") or ""),
            source=str(item.get("source") or ""),
            published_at=str(item.get("datetime") or ""),
            score=100,
            files=tuple(file.name for file in selected_files),
            cloud_type=str(item.get("cloud_type") or ""),
            provider=candidate_provider,
            reasons=("pansou_standard_movie", "title_year_verified", "feature_file_verified"),
        )
        resolution = LinkResolution(
            True,
            "ready",
            "PanSou 已确认标准电影名称和年份，可直接转存",
            inspection.share_url,
            "pansou_direct",
            rename_pairs=pairs,
            reviewed_candidates=(candidate,),
        )
        return DirectMovieResolution(identity, resolution, candidate)
    return None


def _inspect(inspector, share_url: str) -> ShareInspection:
    method = getattr(inspector, "inspect_share", None)
    if callable(method):
        return method(share_url)
    raise AttributeError("provider does not support share inspection")


def _file_supports_identity(
    source: SourceFile,
    identity: StandardMovieIdentity,
    *,
    allow_source_title: bool = False,
) -> bool:
    if _SEASON_EPISODE.search(source.name) or _EPISODE.search(source.name):
        return False
    if _looks_non_movie(source.name):
        return False
    normalized = compact(unicodedata.normalize("NFKC", source.name))
    return identity.year in normalized and (allow_source_title or compact(identity.title) in normalized)


def _looks_non_movie(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if _SEASON_EPISODE.search(normalized) or _EPISODE.search(normalized) or _SEASON_MARKER.search(normalized):
        return True
    return any(marker in normalized for marker in _MOVIE_MARKERS)


def _clean_title(value: str) -> str:
    cleaned = _TECHNICAL_MARKERS.sub(" ", value)
    cleaned = re.sub(r"(?i)(?:\b(?:part|disc|cd)\s*[0-9]+\b)", " ", cleaned)
    cleaned = re.sub(r"[\[\]【】()（）{}<>]", " ", cleaned)
    cleaned = re.sub(r"[._-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_.,")
    return cleaned


def _valid_title(value: str) -> bool:
    key = compact(value)
    return len(key) >= 2 and not key.isdigit() and not _looks_non_movie(value)
