"""Conservative, context-free episode markers shared by discovery consumers.

Bare numbers and upper/lower parts need TMDB/identity context and intentionally
do not appear in this parser's result.
"""
from dataclasses import dataclass
import re
import unicodedata

_NUM = r"[零〇一二两三四五六七八九十百\d]{1,5}"
_SEP = r"\s*(?:-|~|～|至|到|&|、)\s*"
_SE = re.compile(r"(?i)(?<![a-z0-9])s(\d{1,2})[ ._-]*e(?:p|x)?[ ._]*(\d{1,4})(?:(?:" + _SEP + r"|[ ._]*e(?:p)?)(?:e(?:p)?\s*)?(\d{1,4})(?![a-z0-9]))?(?!\d)")
_X = re.compile(r"(?i)(?<![a-z0-9])(\d{1,2})x(\d{1,4})(?![a-z0-9])")
_EP = re.compile(r"(?i)(?<![a-z0-9])(?:episode|ep|ex|e)[ ._-]*(\d{1,4})(?:" + _SEP + r"(?:episode|ep|e)?\s*(\d{1,4})(?![a-z0-9]))?(?!\d)")
_ZH = re.compile(r"第\s*(" + _NUM + r")(?:" + _SEP + r"(?:第\s*)?(" + _NUM + r"))?\s*[集话話回]")
_ZH_RANGE = re.compile(r"第\s*(" + _NUM + r")\s*[集话話回]" + _SEP + r"(?:第\s*)?(" + _NUM + r")\s*[集话話回]")
_SEASON = re.compile(r"(?i)(?<![a-z0-9])(?:season[ ._-]*|s)(\d{1,2})(?!\d)|第\s*(" + _NUM + r")\s*季")


def episode_integer(value: str) -> int:
    value = unicodedata.normalize("NFKC", value)
    if value.isdecimal():
        return int(value)
    if not re.fullmatch(r"(?:[一二两三四五六七八九]百(?:零?[一二两三四五六七八九]|[一二两三四五六七八九]?十[一二三四五六七八九]?)?|[一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九])", value):
        return 0
    digits = {c: n for n, c in enumerate("零一二三四五六七八九")}
    digits["两"] = 2
    total = digit = 0
    for char in value:
        if char in digits:
            digit = digits[char]
        else:
            total += (digit or 1) * {"十": 10, "百": 100}[char]
            digit = 0
    return total + digit


@dataclass(frozen=True)
class EpisodeMarkers:
    numbers: tuple[int, ...] = ()
    seasons: frozenset[int] = frozenset()
    end: int = 0
    invalid: bool = False
    marked: bool = False


def parse_episode_markers(value: str, expected_season: int | None = None) -> EpisodeMarkers:
    text = unicodedata.normalize("NFKC", str(value or ""))
    seasons = {episode_integer(a or b) for a, b in _SEASON.findall(text)}
    spans: list[tuple[int, int]] = []
    hits: list[tuple[int, ...]] = []
    invalid = False
    end = 0
    for pattern, kind in ((_SE, "season"), (_X, "x"), (_ZH_RANGE, "zh"), (_ZH, "zh"), (_EP, "ep")):
        for match in pattern.finditer(text):
            if any(match.start() < b and match.end() > a for a, b in spans):
                continue
            spans.append(match.span())
            groups = match.groups()
            if kind in {"season", "x"}:
                seasons.add(int(groups[0]))
                groups = groups[1:]
            first = episode_integer(groups[0])
            last = episode_integer(groups[1]) if len(groups) > 1 and groups[1] else first
            # Multi-episode files are bounded; a pack label is not file coverage.
            if first <= 0 or last < first or last - first > 3:
                invalid = True
                continue
            hits.append(tuple(range(first, last + 1)))
            end = max(end, match.end())
    if len(seasons) > 1 or (expected_season is not None and seasons and seasons != {expected_season}):
        invalid = True
    if len(set(hits)) > 1:
        invalid = True
    return EpisodeMarkers(() if invalid or not hits else hits[0], frozenset(seasons), end, invalid, bool(spans))


def bare_episode_number(value: str) -> int | None:
    """Accept a numeric stem or a title separated from a numeric episode only."""
    text = unicodedata.normalize("NFKC", value)
    stem = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", text)
    quality = r"(?:[ ._-]+(?:\d{3,4}p|[248]k|web[ ._-]*dl|bluray|h[ ._-]?26[45]|hevc))*"
    match = re.fullmatch(r"\s*(\d{1,3})" + quality + r"\s*", stem, re.I) or re.fullmatch(r".+?\s+-\s+(\d{1,3})" + quality + r"\s*", stem, re.I)
    if not match:
        return None
    number = int(match.group(1))
    return number if 0 < number < 1900 and number not in {264, 265, 360, 480, 576, 720} else None


def named_part(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    parts = re.findall(r"([上中下])\s*(?:集|篇|部)(?![分])", text)
    return parts[0] if len(parts) == 1 else ""
