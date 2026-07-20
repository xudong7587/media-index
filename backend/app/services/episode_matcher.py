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

_SEASON_EPISODE = re.compile(r"(?i)(?<![a-z0-9])S(\d{1,2})[ ._-]*E(?:P|X)?(\d{1,4})(?!\d)")
_EXPLICIT_EPISODE = re.compile(r"(?i)(?<![a-z0-9])E(?:P|X)?(\d{1,4})(?!\d)")
_CHINESE_EPISODE = re.compile(r"第\s*(\d{1,4})\s*集")
_BARE_NUMBER = re.compile(r"(?<![A-Za-z0-9])(\d{2,4})(?![A-Za-z0-9])")
_LEADING_BARE_NUMBER = re.compile(r"^\s*(\d{1,4})(?=\D|$)")
_PART_MARKER = re.compile(r"(?:第\s*\d+\s*期\s*)?[（(]?([上中下])[）)]?(?![\u4e00-\u9fff])")
_ISSUE_PART_SEQUENCE = re.compile(
    r"第\s*\d+\s*期\s*[（(]?\s*([一二三四五六七八九123456789上中下])\s*[）)]?"
)
_COMBINED_SEASON_EPISODE = re.compile(
    r"(?i)(?<![a-z0-9])S(\d{1,2})[ ._-]*E(?:P)?(\d{1,4})[ ._-]*(?:-|~|至|&|E(?:P)?)(?:E(?:P)?)?(\d{1,4})(?!\d)"
)
_COMBINED_EPISODE = re.compile(
    r"(?i)(?<![a-z0-9])E(?:P)?(\d{1,4})[ ._-]*(?:-|~|至|&)(?:E(?:P)?)?(\d{1,4})(?!\d)"
)


def match_episode_files(
    target: MediaTarget,
    files: list[SourceFile],
) -> tuple[list[EpisodeMatch], list[dict]]:
    token_counts: dict[str, int] = {}
    for episode in target.episodes:
        for token in {normalize(value) for value in episode.match_tokens if value}:
            token_counts[token] = token_counts.get(token, 0) + 1
    combined_matches, reserved_files, reserved_episodes = _match_combined_episode_files(target, files)
    part_matches, part_files, part_episodes = _match_same_date_variety_parts(
        target,
        files,
        reserved_files,
        reserved_episodes,
    )
    reserved_files.update(part_files)
    reserved_episodes.update(part_episodes)
    sequence_numbers = _leading_episode_sequence(files) if target.media_type == "tv" else set()
    edges: list[EpisodeMatch] = []
    for episode in target.episodes:
        if episode.episode_number in reserved_episodes:
            continue
        for source in files:
            if (source.path or source.name) in reserved_files:
                continue
            result = score_episode_file(
                target,
                episode,
                source,
                sequence_evidence=episode.episode_number in sequence_numbers,
                unique_match_tokens={token for token, count in token_counts.items() if count == 1},
            )
            if result is not None:
                edges.append(result)

    edges.sort(key=lambda item: (item.score, quality_score(item.source)), reverse=True)
    assigned_files: set[str] = set()
    matches: list[EpisodeMatch] = [*combined_matches, *part_matches]
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
    matched_episode_numbers = {number for match in matches for number in match.episode_numbers}
    incomplete_shared_tokens: set[str] = set()
    for match in matches:
        for reason in match.reasons:
            if not reason.startswith("shared_episode_token:"):
                continue
            token = reason.partition(":")[2]
            token_episodes = {
                episode.episode_number
                for episode in target.episodes
                if token in {normalize(value) for value in episode.match_tokens if value}
            }
            if not token_episodes.issubset(matched_episode_numbers):
                incomplete_shared_tokens.add(token)
    if incomplete_shared_tokens:
        matches = [
            match
            for match in matches
            if not any(
                reason.partition(":")[2] in incomplete_shared_tokens
                for reason in match.reasons
                if reason.startswith("shared_episode_token:")
            )
        ]
    return matches, ambiguities


def _match_same_date_variety_parts(
    target: MediaTarget,
    files: list[SourceFile],
    reserved_files: set[str],
    reserved_episodes: set[int],
) -> tuple[list[EpisodeMatch], set[str], set[int]]:
    """Map an exact same-day part sequence such as 第3期(一)/(二)."""
    if target.media_type != "variety":
        return [], set(), set()
    by_date: dict[str, list[EpisodeTarget]] = {}
    for episode in target.episodes:
        if episode.episode_number not in reserved_episodes and re.fullmatch(r"\d{4}-\d{2}-\d{2}", episode.air_date or ""):
            by_date.setdefault(episode.air_date, []).append(episode)

    matches: list[EpisodeMatch] = []
    matched_files: set[str] = set()
    matched_episodes: set[int] = set()
    for air_date, episodes in by_date.items():
        if len(episodes) < 2:
            continue
        compact_date = air_date.replace("-", "")
        candidates: dict[int, SourceFile] = {}
        duplicate_part = False
        for source in files:
            key = source.path or source.name
            normalized = unicodedata.normalize("NFKC", source.name)
            if key in reserved_files or key in matched_files or not is_video(source.name):
                continue
            if any(word in normalize(source.name) for word in EXCLUDED_WORDS) or compact_date not in normalized.replace("-", "").replace(".", ""):
                continue
            part_index = _issue_part_index(normalized)
            if part_index is None:
                continue
            if part_index in candidates:
                duplicate_part = True
                break
            candidates[part_index] = source
        ordered_episodes = sorted(episodes, key=lambda item: item.episode_number)
        part_numbers = sorted(candidates)
        consecutive_parts = (
            len(part_numbers) == len(ordered_episodes)
            and part_numbers == list(range(part_numbers[0], part_numbers[0] + len(part_numbers)))
        ) if part_numbers else False
        if duplicate_part or not consecutive_parts:
            continue
        for episode, part_index in zip(ordered_episodes, part_numbers):
            source = candidates[part_index]
            matches.append(
                EpisodeMatch(
                    episode,
                    source,
                    108,
                    "high",
                    ("air_date_part_sequence", f"part_{part_index}"),
                )
            )
            matched_files.add(source.path or source.name)
            matched_episodes.add(episode.episode_number)
    return matches, matched_files, matched_episodes


def _issue_part_index(value: str) -> int | None:
    match = _ISSUE_PART_SEQUENCE.search(value)
    if not match:
        return None
    token = match.group(1)
    values = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9,
        "上": 1, "中": 2, "下": 3,
    }
    return int(token) if token.isdigit() else values.get(token)


def _match_combined_episode_files(
    target: MediaTarget,
    files: list[SourceFile],
) -> tuple[list[EpisodeMatch], set[str], set[int]]:
    targets = {episode.episode_number: episode for episode in target.episodes}
    candidates: dict[tuple[int, ...], list[SourceFile]] = {}
    for source in files:
        if not is_video(source.name) or any(word in normalize(source.name) for word in EXCLUDED_WORDS):
            continue
        combined = _combined_episode_numbers(source.name, target.season_number)
        if not combined or any(number not in targets for number in combined):
            continue
        candidates.setdefault(combined, []).append(source)

    matches: list[EpisodeMatch] = []
    reserved_files: set[str] = set()
    reserved_episodes: set[int] = set()
    for numbers, sources in sorted(candidates.items()):
        if any(number in reserved_episodes for number in numbers):
            continue
        sources.sort(key=quality_score, reverse=True)
        source = sources[0]
        episode = targets[numbers[0]]
        matches.append(
            EpisodeMatch(
                episode,
                source,
                115,
                "high",
                ("combined_episode_range",),
                numbers,
            )
        )
        reserved_files.add(source.path or source.name)
        reserved_episodes.update(numbers)
    return matches, reserved_files, reserved_episodes


def _combined_episode_numbers(filename: str, expected_season: int | None) -> tuple[int, ...]:
    normalized = unicodedata.normalize("NFKC", filename)
    match = _COMBINED_SEASON_EPISODE.search(normalized)
    if match:
        season, start, end = (int(value) for value in match.groups())
        if expected_season is not None and season != expected_season:
            return ()
    else:
        match = _COMBINED_EPISODE.search(normalized)
        if not match:
            return ()
        start, end = (int(value) for value in match.groups())
    if end <= start or end - start > 3:
        return ()
    return tuple(range(start, end + 1))


def score_episode_file(
    target: MediaTarget,
    episode: EpisodeTarget,
    source: SourceFile,
    *,
    sequence_evidence: bool = False,
    unique_match_tokens: set[str] | None = None,
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
            normalized_token = normalize(token)
            shared_token = unique_match_tokens is not None and normalized_token not in unique_match_tokens
            if token.startswith(("S", "E", "EP", "第")):
                if _token_present(name, normalized_token):
                    score = 72 if shared_token else 90
                    confidence = "review" if shared_token else "high"
                    reasons.append(f"shared_episode_token:{normalized_token}" if shared_token else "unique_episode_token")
                    break
            elif token and normalized_token in name:
                score = 70 if shared_token else 86
                confidence = "review" if shared_token else "high"
                reasons.append(f"shared_episode_token:{normalized_token}" if shared_token else "air_date")
                break

    if score == 0 and (episode.episode_number >= 10 or sequence_evidence):
        bare = {int(value) for value in _BARE_NUMBER.findall(name)}
        leading = _leading_bare_number(source.name)
        if sequence_evidence and leading is not None:
            bare.add(leading)
        if episode.episode_number in bare:
            score = 90 if episode.episode_number >= 100 or sequence_evidence else 68
            confidence = "high" if episode.episode_number >= 100 or sequence_evidence else "medium"
            reasons.append(
                "exact_four_digit_episode"
                if episode.episode_number >= 1000
                else "exact_three_digit_episode"
                if episode.episode_number >= 100
                else "numeric_episode_sequence"
                if sequence_evidence
                else "bounded_bare_number"
            )

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
    explicit_number_reasons = {
        "exact_season_episode",
        "explicit_episode",
        "exact_four_digit_episode",
        "exact_three_digit_episode",
        "numeric_episode_sequence",
        "bounded_bare_number",
    }
    if target_part and not source_part and not explicit_number_reasons.intersection(reasons):
        # A generic “第3期” or same-day filename cannot identify “第3期（四）”.
        # Exact SxxExx/Episode evidence may omit the human-readable part marker.
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
    covered = match.episode_numbers
    episode_part = f"E{covered[0]:02d}"
    if len(covered) > 1:
        episode_part += f"-E{covered[-1]:02d}"
    replacement = f"{title}{year_part}.S{match.episode.season_number:02d}{episode_part}{extension}"
    return RenamePair(
        source_name=match.source.name,
        pattern=f"^{re.escape(match.source.name)}$",
        replacement=replacement,
        episode_number=match.episode.episode_number,
        confidence=match.confidence,
        reasons=match.reasons,
        episode_numbers=covered,
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
    normalized = unicodedata.normalize("NFKC", value)
    issue_part = _issue_part_index(normalized)
    if issue_part is not None:
        return f"issue_part_{issue_part}"
    match = _PART_MARKER.search(normalized)
    if not match:
        return ""
    part = match.group(1)
    part_number = {"上": 1, "中": 2, "下": 3}.get(part, part)
    return f"issue_part_{part_number}"


def _leading_bare_number(filename: str) -> int | None:
    stem = os.path.splitext(unicodedata.normalize("NFKC", filename))[0]
    match = _LEADING_BARE_NUMBER.match(stem)
    return int(match.group(1)) if match else None


def _leading_episode_sequence(files: list[SourceFile]) -> set[int]:
    numbers = {
        number
        for source in files
        if is_video(source.name) and (number := _leading_bare_number(source.name)) is not None and number < 1900
    }
    supported: set[int] = set()
    for number in numbers:
        if {number, number + 1, number + 2} <= numbers or {number - 1, number, number + 1} <= numbers or {number - 2, number - 1, number} <= numbers:
            supported.add(number)
    return supported
