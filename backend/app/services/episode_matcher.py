from __future__ import annotations

import math
import os
import re
import unicodedata

from app.domain.media import EpisodeMatch, EpisodeTarget, MediaTarget, RenamePair, SourceFile


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".m2ts", ".mov", ".avi", ".wmv", ".flv"}
EXCLUDED_WORDS = (
    "纯享",
    "加更",
    "花絮",
    "预告",
    "先导",
    "番外",
    "幕后",
    "彩排",
    "彩蛋",
    "未播",
    "陪看",
    "会员版",
    "plus版",
    "衍生",
    "片段",
    "集锦",
    "ost",
    "原声",
    "reaction",
)

_SEASON_EPISODE = re.compile(r"(?i)(?<![a-z0-9])S(\d{1,2})[ ._-]*E(?:P|X)?(\d{1,3})(?!\d)")
_EXPLICIT_EPISODE = re.compile(r"(?i)(?<![a-z0-9])E(?:P|X)?(\d{1,3})(?!\d)")
_CHINESE_EPISODE = re.compile(r"第\s*(\d{1,3})\s*集")
_BARE_NUMBER = re.compile(r"(?<![A-Za-z0-9])(\d{2,3})(?![A-Za-z0-9])")
_PART_MARKER = re.compile(r"(?:第\s*\d+\s*期\s*)?[（(]?([上中下])[）)]?(?![\u4e00-\u9fff])")


def match_episode_files(
    target: MediaTarget,
    files: list[SourceFile],
) -> tuple[list[EpisodeMatch], list[dict]]:
    edges: list[EpisodeMatch] = []
    for episode in target.episodes:
        for source in files:
            result = score_episode_file(target, episode, source)
            if result is not None:
                edges.append(result)

    edges.sort(key=lambda item: (item.score, quality_score(item.source)), reverse=True)
    assigned_files: set[str] = set()
    matches: list[EpisodeMatch] = []
    ambiguities: list[dict] = []

    by_episode: dict[int, list[EpisodeMatch]] = {}
    for edge in edges:
        by_episode.setdefault(edge.episode.episode_number, []).append(edge)

    remaining = set(by_episode)
    while remaining:
        available_by_episode = {
            episode_number: [
                item
                for item in by_episode[episode_number]
                if (item.source.path or item.source.name) not in assigned_files
            ]
            for episode_number in remaining
        }
        episode_number = min(
            remaining,
            key=lambda number: (
                len(available_by_episode[number]) or 10**6,
                -(available_by_episode[number][0].score if available_by_episode[number] else 0),
                number,
            ),
        )
        remaining.remove(episode_number)
        available = available_by_episode[episode_number]
        if not available:
            continue
        available.sort(key=lambda item: (item.score, quality_score(item.source)), reverse=True)
        best = available[0]
        second = available[1] if len(available) > 1 else None
        if second and best.score < 95 and best.score - second.score < 10:
            ambiguities.append(
                {
                    "episode_number": episode_number,
                    "reason": "multiple_close_candidates",
                    "files": [best.source.name, second.source.name],
                }
            )
            continue
        key = best.source.path or best.source.name
        assigned_files.add(key)
        matches.append(best)

    matches.sort(key=lambda item: item.episode.episode_number)
    return matches, ambiguities


def score_episode_file(
    target: MediaTarget,
    episode: EpisodeTarget,
    source: SourceFile,
) -> EpisodeMatch | None:
    name = normalize(source.name)
    if not is_video(source.name) or any(word in name for word in EXCLUDED_WORDS):
        return None

    reasons: list[str] = []
    score = 0
    confidence = "low"

    season_hits = [(int(s), int(e)) for s, e in _SEASON_EPISODE.findall(name)]
    if season_hits:
        if (episode.season_number, episode.episode_number) not in season_hits:
            return None
        score = 100
        confidence = "high"
        reasons.append("exact_season_episode")
    else:
        explicit = {int(value) for value in _EXPLICIT_EPISODE.findall(name)}
        explicit.update(int(value) for value in _CHINESE_EPISODE.findall(name))
        if explicit:
            if episode.episode_number not in explicit:
                return None
            score = 92
            confidence = "high"
            reasons.append("explicit_episode")

    if score == 0:
        for token in episode.match_tokens:
            if token.startswith(("S", "E", "EP", "第")):
                if _token_present(name, normalize(token)):
                    score = 90
                    confidence = "high"
                    reasons.append("unique_episode_token")
                    break
            elif token and normalize(token) in name:
                score = 86
                confidence = "high"
                reasons.append("air_date")
                break

    if score == 0 and episode.episode_number >= 10:
        bare = {int(value) for value in _BARE_NUMBER.findall(name)}
        if episode.episode_number in bare:
            score = 68
            confidence = "medium"
            reasons.append("bounded_bare_number")

    if score == 0 and episode.desc_hint:
        hint = normalize(episode.desc_hint)
        longest = _longest_substring_match(hint, name)
        if longest >= 5:
            score = 55 + min(longest, 8)
            confidence = "review"
            reasons.append("description_hint")

    if score == 0:
        return None

    target_part = _part_marker(episode.title)
    source_part = _part_marker(source.name)
    if target_part and source_part and target_part != source_part:
        return None
    if target_part and source_part == target_part:
        score += 10
        reasons.append(f"part_{target_part}")

    if any(normalize(title) in name for title in target.search_titles if len(normalize(title)) >= 2):
        score += 4
        reasons.append("title")
    return EpisodeMatch(episode, source, score, confidence, tuple(reasons))


def build_rename_pair(target: MediaTarget, match: EpisodeMatch) -> RenamePair:
    extension = os.path.splitext(match.source.name)[1].lower() or ".mp4"
    title = sanitize_filename_component(target.title)
    year = target.series_year or target.season_year
    year_part = f".{year}" if year else ""
    replacement = (
        f"{title}{year_part}.S{match.episode.season_number:02d}"
        f"E{match.episode.episode_number:02d}{extension}"
    )
    return RenamePair(
        source_name=match.source.name,
        pattern=f"^{re.escape(match.source.name)}$",
        replacement=replacement,
        episode_number=match.episode.episode_number,
        confidence=match.confidence,
        reasons=match.reasons,
    )


def is_video(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in VIDEO_EXTENSIONS


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def sanitize_filename_component(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "Untitled"


def quality_score(source: SourceFile) -> int:
    name = normalize(source.name)
    extension = os.path.splitext(name)[1]
    score = {".mkv": 8, ".mp4": 7, ".m2ts": 5, ".ts": 4}.get(extension, 2)
    if "2160p" in name or "4k" in name:
        score += 8
    elif "1080p" in name:
        score += 5
    elif "720p" in name:
        score += 2
    if source.size > 0:
        score += min(8, int(math.log2(max(source.size, 1)) / 4))
    return score


def _token_present(filename: str, token: str) -> bool:
    start = filename.find(token)
    while start >= 0:
        before = filename[start - 1] if start > 0 else ""
        after_pos = start + len(token)
        after = filename[after_pos] if after_pos < len(filename) else ""
        if (not before or not before.isalnum()) and (not after or not after.isdigit()):
            return True
        start = filename.find(token, start + 1)
    return False


def _longest_substring_match(hint: str, filename: str) -> int:
    for length in range(min(len(hint), 8), 4, -1):
        for start in range(0, len(hint) - length + 1):
            if hint[start : start + length] in filename:
                return length
    return 0


def _part_marker(value: str) -> str:
    match = _PART_MARKER.search(unicodedata.normalize("NFKC", value))
    return match.group(1) if match else ""
