from __future__ import annotations

import os
import re
import unicodedata

from app.domain.media import MediaTarget, RenamePair, SourceFile
from app.services.candidate_ranker import compact
from app.services.episode_matcher import EXCLUDED_WORDS, is_video, quality_score, sanitize_filename_component


MOVIE_EXCLUDED_WORDS = (*EXCLUDED_WORDS, "sample", "trailer", "bonus", "makingof", "彩蛋")
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


def choose_movie_file(
    target: MediaTarget,
    files: list[SourceFile],
    source_title: str = "",
) -> tuple[SourceFile | None, int, tuple[str, ...], bool]:
    scored: list[tuple[int, SourceFile, tuple[str, ...]]] = []
    accepted_years = {year for year in (target.series_year, target.season_year) if year}
    aliases = [
        value
        for title in target.search_titles
        if (value := compact(title)) and len(value) >= 2 and not value.isdigit()
    ]

    for source in files:
        if not is_video(source.name):
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


def build_movie_rename_pair(target: MediaTarget, source: SourceFile, reasons: tuple[str, ...]) -> RenamePair:
    title = sanitize_filename_component(target.title)
    extension = os.path.splitext(source.name)[1].lower() or ".mp4"
    year = f".{target.series_year}" if target.series_year else ""
    return RenamePair(
        source_name=source.name,
        pattern=f"^{re.escape(source.name)}$",
        replacement=f"{title}{year}{extension}",
        confidence="high",
        reasons=reasons,
    )
