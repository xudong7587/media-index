from __future__ import annotations

from app.domain.media import MediaTarget, SearchQuery


def build_search_queries(target: MediaTarget, max_queries: int = 8) -> tuple[SearchQuery, ...]:
    """Search PanSou with TMDB's canonical title, then its English title only.

    PanSou recall drops sharply when a year, season or episode marker is added
    to the keyword.  Those values remain validation evidence, but never become
    part of the query.  Callers stop after the first query that returns items,
    so the English title is strictly an empty-result fallback.
    """
    title = str(target.title or "").strip()
    if not title or max_queries <= 0:
        return ()
    queries = [SearchQuery(title, "tmdb_canonical_zh", 190)]
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
