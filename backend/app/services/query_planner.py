from __future__ import annotations

from app.domain.media import MediaTarget, SearchQuery
def build_search_queries(target: MediaTarget, max_queries: int = 8) -> tuple[SearchQuery, ...]:
    """Build a small, stable plan around the canonical TMDB title.

    Resource indexes are strongest for the localized canonical title.  Alias,
    English-title, traditional-title and per-episode permutations used to
    multiply PanSou requests without adding reliable evidence.  Episodic
    media now uses only the title, a Chinese season suffix and an Sxx suffix;
    file inspection remains responsible for deciding the actual episodes.
    """
    title = str(target.title or "").strip()
    if not title or max_queries <= 0:
        return ()
    queries: list[SearchQuery] = []
    if target.media_type in {"tv", "variety"} and target.season_number is not None:
        season = max(0, int(target.season_number))
        queries.extend((
            SearchQuery(title, "title_broad_first", 190),
            SearchQuery(f"{title} 第{season}季", "title_season_cn", 180),
            SearchQuery(f"{title} S{season:02d}", "title_season_sxx", 170),
        ))
    else:
        queries.append(SearchQuery(title, "title_broad", 100))
        if target.series_year:
            queries.append(SearchQuery(f"{title} {target.series_year}", "title_year", 95))

    seen: set[str] = set()
    result: list[SearchQuery] = []
    for query in sorted(queries, key=lambda item: item.priority, reverse=True):
        key = " ".join(query.keyword.casefold().split())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(query)
    return tuple(result[:max_queries])
