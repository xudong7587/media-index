from __future__ import annotations


# TMDB titles are the naming authority, but PanSou indexes community release
# names. These verified aliases affect discovery and validation only;
# canonical folders and filenames still use the TMDB title.
RESOURCE_SEARCH_ALIASES: dict[tuple[int, str], tuple[str, ...]] = {
    (94997, "tv"): ("龙之家族",),
}


def merge_resource_aliases(
    tmdb_id: int,
    media_type: str,
    tmdb_aliases: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    normalized_type = "tv" if media_type in {"tv", "variety"} else media_type
    values = (*RESOURCE_SEARCH_ALIASES.get((tmdb_id, normalized_type), ()), *tmdb_aliases)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)
