from __future__ import annotations

from app.domain.media import MediaTarget, SearchQuery


def build_search_queries(target: MediaTarget, max_queries: int = 8) -> tuple[SearchQuery, ...]:
    queries: list[SearchQuery] = []
    titles = target.search_titles[:4]
    if not titles:
        return ()

    if target.media_type in {"tv", "variety"} and target.season_number is not None:
        season = target.season_number
        if len(target.episodes) == 1:
            episode = target.episodes[0]
            queries.append(
                SearchQuery(
                    f"{titles[0]} S{season:02d}E{episode.episode_number:02d}",
                    "target_episode_sxxexx",
                    150,
                )
            )
            if target.media_type == "variety":
                queries.append(
                    SearchQuery(
                        f"{titles[0]} 第{episode.episode_number}期",
                        "target_variety_issue",
                        145,
                    )
                )
            if episode.air_date:
                queries.append(
                    SearchQuery(
                        f"{titles[0]} {episode.air_date.replace('-', '')}",
                        "target_air_date",
                        140,
                    )
                )
        for title in titles:
            queries.append(SearchQuery(f"{title} 第{season}季", "title_season_cn", 100))
            queries.append(SearchQuery(f"{title} S{season:02d}", "title_season_sxx", 95))
        queries.append(SearchQuery(titles[0], "canonical_title_broad", 70))
        if target.season_year:
            queries.append(SearchQuery(f"{titles[0]} {target.season_year}", "title_season_year", 65))
    else:
        for title in titles:
            if target.series_year:
                queries.append(SearchQuery(f"{title} {target.series_year}", "title_year", 100))
            queries.append(SearchQuery(title, "title_broad", 80))

    seen: set[str] = set()
    result: list[SearchQuery] = []
    for query in sorted(queries, key=lambda item: item.priority, reverse=True):
        key = " ".join(query.keyword.casefold().split())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(query)
        if len(result) >= max_queries:
            break
    return tuple(result)
