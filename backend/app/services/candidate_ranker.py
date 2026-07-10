from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from app.domain.media import MediaTarget, ResourceCandidate


DERIVATIVE_WORDS = ("预告", "花絮", "纯享", "reaction", "ost", "原声", "片段", "cut")
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


def rank_resource_candidates(
    target: MediaTarget,
    items: list[dict],
    query: str = "",
) -> list[ResourceCandidate]:
    candidates = [score_resource_candidate(target, item, query) for item in items]
    candidates.sort(key=lambda item: (item.rejected, -item.score, -_published_rank(item.published_at)))
    return candidates


def score_resource_candidate(target: MediaTarget, item: dict, query: str = "") -> ResourceCandidate:
    title = str(item.get("title") or item.get("note") or "")
    content = str(item.get("content") or "")
    raw_haystack = unicodedata.normalize("NFKC", f"{title} {content}").casefold()
    haystack = compact(raw_haystack)
    score = 0
    rejected = False
    reasons: list[str] = []

    title_scores = [_title_similarity(compact(alias), haystack) for alias in target.search_titles]
    title_score = max(title_scores, default=0)
    score += title_score
    if title_score >= 30:
        reasons.append("title_exact_or_contained")
    elif title_score >= 15:
        reasons.append("title_partial")
    else:
        score -= 30
        reasons.append("title_weak")

    if target.season_number is not None:
        seasons = extract_seasons(raw_haystack)
        if target.season_number in seasons:
            score += 40
            reasons.append("season_exact")
        elif seasons:
            score -= 90
            rejected = True
            reasons.append("season_conflict")

    accepted_years = {year for year in (target.series_year, target.season_year) if year}
    found_years = set(_YEAR.findall(raw_haystack))
    if found_years and accepted_years:
        if found_years & accepted_years:
            score += 12
            reasons.append("year_match")
        else:
            score -= 55
            rejected = True
            reasons.append("year_conflict")

    if any(word in haystack for word in DERIVATIVE_WORDS):
        score -= 45
        reasons.append("derivative_content")

    if len(target.episodes) == 1:
        episode = target.episodes[0]
        evidence = [
            compact(token)
            for token in episode.match_tokens
            if token and len(compact(token)) >= 3
        ]
        if any(token in haystack for token in evidence):
            score += 35
            reasons.append("target_episode_evidence")

    return ResourceCandidate(
        share_url=str(item.get("share_url") or item.get("url") or ""),
        title=title,
        content=content,
        source=str(item.get("source") or ""),
        published_at=str(item.get("datetime") or item.get("published_at") or ""),
        query=query,
        score=score,
        rejected=rejected,
        reasons=tuple(reasons),
    )


def compact(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)


def _published_rank(value: str) -> int:
    if not value:
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(parsed.timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


def extract_seasons(value: str) -> set[int]:
    seasons = {int(number) for number in re.findall(r"第(\d{1,2})季", value)}
    seasons.update(int(number) for number in re.findall(r"(?<![a-z0-9])s0*(\d{1,2})(?!\d)", value))
    seasons.update(int(number) for number in re.findall(r"season0*(\d{1,2})(?!\d)", value))
    for number, chinese in enumerate("一二三四五六七八九", start=1):
        if f"第{chinese}季" in value:
            seasons.add(number)
    if "第十季" in value:
        seasons.add(10)
    return seasons


def _title_similarity(alias: str, haystack: str) -> int:
    if not alias:
        return 0
    if alias in haystack:
        return 35
    if len(alias) < 4:
        return 0
    chunks = {alias[index : index + 2] for index in range(len(alias) - 1)}
    if not chunks:
        return 0
    overlap = sum(1 for chunk in chunks if chunk in haystack)
    ratio = overlap / len(chunks)
    return int(ratio * 24) if ratio >= 0.5 else 0
