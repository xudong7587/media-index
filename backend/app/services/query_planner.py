from __future__ import annotations

import re

from app.domain.media import MediaTarget, SearchQuery
from app.services.candidate_ranker import rank_resource_candidates
from app.services.provider_compat import provider_accepts_candidate


def build_search_queries(target: MediaTarget, max_queries: int = 8) -> tuple[SearchQuery, ...]:
    """Search PanSou by bare Chinese title first, then a foreign fallback.

    PanSou recall drops sharply when a year, season or episode marker is added
    to the keyword. Those values remain validation evidence, but never become
    part of the query. The Chinese title may be TMDB's canonical title or one
    of its verified aliases. Because callers stop after the first query with
    compatible, non-rejected title evidence, Chinese names precede English;
    otherwise generic English hits can prevent the actual indexed title from
    ever being searched. Year, season and episode evidence is applied only
    after PanSou returns candidates.
    """
    title = str(target.title or "").strip()
    if not title or max_queries <= 0:
        return ()

    localized_aliases = [
        str(value or "").strip()
        for value in target.aliases
        if str(value or "").strip() and _contains_cjk(str(value))
    ]
    title_is_localized = _contains_cjk(title)
    queries: list[SearchQuery] = []
    if title_is_localized:
        queries.append(SearchQuery(title, "tmdb_canonical_zh", 190))
        queries.extend(
            SearchQuery(value, "tmdb_localized_alias", 180 - index)
            for index, value in enumerate(localized_aliases[:3])
            if value != title and not _has_episode_marker(value)
        )
    else:
        queries.extend(
            SearchQuery(value, "tmdb_localized_alias", 195 - index)
            for index, value in enumerate(localized_aliases[:3])
        )
        queries.append(SearchQuery(title, "tmdb_canonical_zh", 170))
    english_title = str(target.english_title or "").strip()
    if english_title:
        queries.append(SearchQuery(english_title, "tmdb_english_fallback", 100))

    seen: set[str] = set()
    result: list[SearchQuery] = []
    for query in sorted(queries, key=lambda item: item.priority, reverse=True):
        key = " ".join(query.keyword.casefold().split())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(query)
    return tuple(result[:max_queries])


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(value or ""))


def _has_episode_marker(value: str) -> bool:
    return bool(re.search(r"第\s*[一二三四五六七八九十百\d]+\s*[季集期]|(?i:\bs\d+|\be\d+)", value))


def has_usable_search_candidates(target: MediaTarget, items: list[dict], provider: str) -> bool:
    """Another provider's hits or rejected/weak titles must not stop fallbacks."""
    return any(
        not candidate.rejected
        and "title_exact_or_contained" in candidate.reasons
        and provider_accepts_candidate(provider, candidate)
        for candidate in rank_resource_candidates(target, items)
    )
