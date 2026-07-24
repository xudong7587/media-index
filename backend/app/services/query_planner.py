from __future__ import annotations

from app.domain.media import MediaTarget, SearchQuery
from app.services.episode_tokens import extract_variety_issue_label


_CHINESE_SEASONS = ("", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十")


def build_search_queries(target: MediaTarget, max_queries: int = 8) -> tuple[SearchQuery, ...]:
    queries: list[SearchQuery] = []
    all_titles = target.search_titles
    titles = (
        (all_titles[0],)
        + tuple(title for title in all_titles[1:] if _safe_alternate_title(title))
        if all_titles
        else ()
    )[:4]
    if not titles:
        return ()

    if target.media_type in {"tv", "variety"} and target.season_number is not None:
        season = target.season_number
        if target.media_type == "variety" and len(target.episodes) > 1:
            air_dates = tuple(
                dict.fromkeys(
                    episode.air_date
                    for episode in target.episodes
                    if episode.air_date and len(episode.air_date) >= 10
                )
            )
            for air_date in air_dates[:2]:
                queries.append(
                    SearchQuery(
                        f"{titles[0]} {air_date[5:10].replace('-', '')}",
                        "target_air_date",
                        168,
                    )
                )
        if len(target.episodes) == 1:
            episode = target.episodes[0]
            queries.append(
                SearchQuery(
                    f"{titles[0]} S{season:02d}E{episode.episode_number:02d}",
                    "target_episode_sxxexx",
                    170,
                )
            )
            if target.media_type == "variety":
                issue_label = extract_variety_issue_label(episode.title) or f"第{episode.episode_number}期"
                queries.append(
                    SearchQuery(
                        f"{titles[0]} {issue_label}",
                        "target_variety_issue",
                        165,
                    )
                )
                queries.append(SearchQuery(titles[0], "canonical_title_fallback", 162))
            elif target.series_year:
                queries.append(SearchQuery(f"{titles[0]} {target.series_year}", "canonical_title_year_fallback", 162))
            for alias in titles[1:3]:
                issue_label = extract_variety_issue_label(episode.title) or f"第{episode.episode_number}期"
                keyword = (
                    f"{alias} {issue_label}"
                    if target.media_type == "variety"
                    else f"{alias} S{season:02d}E{episode.episode_number:02d}"
                )
                queries.append(SearchQuery(keyword, "target_episode_alias", 160))
            if episode.air_date:
                month_day = episode.air_date[5:].replace("-", "")
                queries.append(
                    SearchQuery(
                        f"{titles[0]} {month_day}",
                        "target_air_date",
                        155,
                    )
                )
        for title_index, title in enumerate(titles):
            if 0 < season < len(_CHINESE_SEASONS):
                localized_priority = 115 if title_index == 1 else 110 - title_index
                if any("\u4e00" <= char <= "\u9fff" for char in title):
                    queries.append(SearchQuery(f"{title}第{_CHINESE_SEASONS[season]}季", "title_season_chinese_compact", localized_priority - 1))
                queries.append(SearchQuery(f"{title} 第{_CHINESE_SEASONS[season]}季", "title_season_chinese", localized_priority))
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
    limited = result[:max_queries]
    broad = next(
        (
            query
            for query in result
            if query.reason in {"canonical_title_broad", "canonical_title_fallback"}
        ),
        None,
    )
    if broad is not None and broad not in limited and limited:
        limited[-1] = broad
    return tuple(limited)


def _safe_alternate_title(value: str) -> bool:
    compact = "".join(char for char in value.strip() if char.isalnum())
    chinese_count = sum("\u4e00" <= char <= "\u9fff" for char in compact)
    # Two-character nicknames such as “喜单” and “脱友” are useful in human
    # conversation but far too broad for a global resource index. The full
    # canonical title and release date already provide a precise first query.
    return chinese_count >= 3 or (chinese_count == 0 and len(compact) >= 5)
