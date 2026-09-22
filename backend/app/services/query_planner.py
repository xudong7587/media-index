from __future__ import annotations

from app.domain.media import MediaTarget, SearchQuery


def build_search_queries(target: MediaTarget, max_queries: int = 8) -> tuple[SearchQuery, ...]:
    """Search PanSou by bare Chinese title first, then a foreign fallback.

    PanSou recall drops sharply when a year, season or episode marker is added
    to the keyword. Those values remain validation evidence, but never become
    part of the query. The Chinese title may be TMDB's canonical title or one
    of its verified aliases. Because callers stop after the first query that
    returns items, those Chinese names must precede an English canonical title;
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
