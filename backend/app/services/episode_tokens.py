from __future__ import annotations

import re

from app.domain.media import EpisodeTarget


_PREFIX_SPLIT = re.compile(r"[：:（(]")
_ISSUE_PREFIX = re.compile(r"^(第\d+期[上中下]?)")
_LEADING_ISSUE = re.compile(r"^第\d+期[上中下]?\s*[：:（(]?\s*")


def build_episode_targets(season_number: int, episodes: list[dict]) -> tuple[EpisodeTarget, ...]:
    prefixes = [_chinese_prefix(str(item.get("name") or "")) for item in episodes]
    counts = {prefix: prefixes.count(prefix) for prefix in set(prefixes) if prefix}
    targets: list[EpisodeTarget] = []

    for item, prefix in zip(episodes, prefixes):
        episode_number = int(item.get("episode_number") or 0)
        if episode_number <= 0:
            continue
        air_date = str(item.get("air_date") or "")
        title = str(item.get("name") or "")
        tokens = [
            f"S{season_number:02d}E{episode_number:02d}",
            f"E{episode_number:02d}",
            f"EP{episode_number:02d}",
            f"第{episode_number}集",
        ]
        if air_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", air_date):
            tokens.extend((air_date, air_date.replace("-", ""), air_date.replace("-", ".")))
        if prefix and counts.get(prefix) == 1:
            tokens.append(prefix)

        targets.append(
            EpisodeTarget(
                season_number=season_number,
                episode_number=episode_number,
                air_date=air_date,
                title=title,
                match_tokens=tuple(dict.fromkeys(tokens)),
                desc_hint=_description_hint(title),
            )
        )
    return tuple(targets)


def _chinese_prefix(title: str) -> str:
    if not title:
        return ""
    prefix = _PREFIX_SPLIT.split(title, maxsplit=1)[0].strip()
    if prefix and prefix != title:
        return prefix
    match = _ISSUE_PREFIX.match(title)
    if match:
        return match.group(1)
    return ""


def _description_hint(title: str) -> str:
    if not title:
        return ""
    remainder = _LEADING_ISSUE.sub("", title).strip()
    if remainder == title:
        parts = title.split(None, 1)
        remainder = parts[1] if len(parts) == 2 else ""
    compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", remainder)
    return compact[:8] if len(compact) >= 4 else ""

