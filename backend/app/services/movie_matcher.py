from __future__ import annotations

import os
import re
import unicodedata

from app.domain.media import MediaTarget, RenamePair, SourceFile
from app.services.candidate_ranker import compact
from app.services.episode_matcher import EXCLUDED_WORDS, is_video, quality_score, sanitize_filename_component


MOVIE_EXCLUDED_WORDS = (
    *EXCLUDED_WORDS,
    "sample",
    "trailer",
    "bonus",
    "makingof",
    "彩蛋",
    "采访",
    "访谈",
    "解说",
    "影评",
    "混剪",
    "剪辑",
    "短片",
    "vlog",
)
MIN_LIKELY_FEATURE_SIZE = 200 * 1024 * 1024
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


def choose_movie_file(
    target: MediaTarget,
    files: list[SourceFile],
    source_title: str = "",
) -> tuple[SourceFile | None, int, tuple[str, ...], bool]:
    scored: list[tuple[int, SourceFile, tuple[str, ...]]] = []
    video_files = [source for source in files if is_video(source.name)]
    largest_known_size = max((source.size for source in video_files), default=0)
    accepted_years = {year for year in (target.series_year, target.season_year) if year}
    aliases = [
        value
        for title in target.search_titles
        if (value := compact(title)) and len(value) >= 2 and not value.isdigit()
    ]

    for source in video_files:
        # Artwork, NFO and subtitles are already excluded by the video suffix
        # check. Also ignore clearly secondary video clips when a much larger
        # feature file exists in the same share.
        if (
            largest_known_size >= MIN_LIKELY_FEATURE_SIZE
            and source.size > 0
            and source.size < max(MIN_LIKELY_FEATURE_SIZE, largest_known_size * 0.25)
        ):
            continue
        raw_haystack = unicodedata.normalize("NFKC", f"{source.name} {source_title}").casefold()
        haystack = compact(raw_haystack)
        if any(word in haystack for word in MOVIE_EXCLUDED_WORDS):
            continue
        found_years = set(_YEAR.findall(raw_haystack))
        if found_years and accepted_years and not found_years & accepted_years:
            continue
        reasons: list[str] = []
        score = quality_score(source)
        if any(alias in haystack for alias in aliases):
            score += 45
            reasons.append("title")
        elif source_title and any(alias in compact(source_title) for alias in aliases):
            score += 35
            reasons.append("source_title")
        else:
            score -= 25
            reasons.append("title_weak")
        if found_years & accepted_years:
            score += 15
            reasons.append("year")
        if source.size > 0:
            if source.size < MIN_LIKELY_FEATURE_SIZE:
                score -= 45
                reasons.append("file_too_small_for_feature")
            else:
                score += 12
                reasons.append("feature_length_size")
        variant_score, variant_reason = _variant_preference(source.name)
        score += variant_score
        if variant_reason:
            reasons.append(variant_reason)
        scored.append((score, source, tuple(reasons)))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return None, 0, (), False
    best = scored[0]
    ambiguous = len(scored) > 1 and best[0] - scored[1][0] < 8
    if ambiguous and _release_identity(best[1].name) == _release_identity(scored[1][1].name):
        ambiguous = False
    return best[1], best[0], best[2], ambiguous


def choose_movie_files(
    target: MediaTarget,
    files: list[SourceFile],
    source_title: str = "",
) -> tuple[tuple[SourceFile, ...], int, tuple[str, ...]]:
    """Choose feature-length movie files while collapsing quality variants."""
    best, score, reasons, _ambiguous = choose_movie_file(target, files, source_title)
    if best is None:
        return (), score, reasons
    largest = max((item.size for item in files if is_video(item.name)), default=0)
    candidates = [
        item
        for item in files
        if is_video(item.name)
        and not any(word in compact(item.name) for word in MOVIE_EXCLUDED_WORDS)
        and (item.size <= 0 or item.size >= max(MIN_LIKELY_FEATURE_SIZE, largest * 0.25))
    ]
    by_release: dict[str, SourceFile] = {}
    for item in candidates:
        identity = _release_identity(item.name)
        current = by_release.get(identity)
        if current is None or quality_score(item) > quality_score(current):
            by_release[identity] = item
    selected = tuple(sorted(by_release.values(), key=lambda item: _movie_part_sort_key(item.name)))
    return selected or (best,), score, reasons


def _movie_part_sort_key(filename: str) -> tuple[int, str]:
    name = unicodedata.normalize("NFKC", filename).casefold()
    markers = (
        (r"(?:^|[ ._\-])(上|上部|上集)(?:[ ._\-]|$)", 1),
        (r"(?:^|[ ._\-])(?:cd|disc|disk|part)[ ._\-]*0?1(?:[ ._\-]|$)", 1),
        (r"(?:^|[ ._\-])(下|下部|下集)(?:[ ._\-]|$)", 2),
        (r"(?:^|[ ._\-])(?:cd|disc|disk|part)[ ._\-]*0?2(?:[ ._\-]|$)", 2),
    )
    for pattern, order in markers:
        if re.search(pattern, name):
            return order, name
    return 99, name


def _release_identity(filename: str) -> str:
    stem = os.path.splitext(unicodedata.normalize("NFKC", filename).casefold())[0]
    stem = re.sub(
        r"(?i)(?:2160p|1080p|720p|4k|uhd|hdr10\+?|hdr|dv|dolbyvision|web[-_. ]?dl|webrip|bluray|blu[-_. ]?ray|x26[45]|h\.26[45]|hevc|avc|10bit|8bit|aac|dts|atmos)",
        " ",
        stem,
    )
    return compact(stem)


def _variant_preference(filename: str) -> tuple[int, str]:
    name = unicodedata.normalize("NFKC", filename).casefold()
    if re.search(r"(?<![a-z])(?:dv|dolby[ ._-]*vision)(?![a-z])", name):
        return 4, "dolby_vision"
    if "hdr10+" in name or "hdr10plus" in name:
        return 3, "hdr10_plus"
    if "hdr10" in name:
        return 2, "hdr10"
    if "hdr" in name:
        return 1, "hdr"
    return 0, ""


def build_movie_rename_pair(
    target: MediaTarget,
    source: SourceFile,
    reasons: tuple[str, ...],
    part_number: int | None = None,
) -> RenamePair:
    title = sanitize_filename_component(target.title)
    extension = os.path.splitext(source.name)[1].lower() or ".mp4"
    year = f".{target.series_year}" if target.series_year else ""
    return RenamePair(
        source_name=source.name,
        pattern=f"^{re.escape(source.name)}$",
        replacement=f"{title}{year}{f'.Part{part_number:02d}' if part_number else ''}{extension}",
        confidence="high",
        reasons=reasons,
        source_id=source.provider_file_id,
        source_path=source.path,
        source_size=source.size,
    )
