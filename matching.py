"""
Matching Engine — zero-LLM filename-to-episode matching for smart tracking.

Three-stage pipeline:
  A) Digital episode number matching (E180, 180, .180.)
  B) Chinese token matching (第1期上, 第1期中)
  C) Fuzzy description matching (desc_hint substring)

Also: year cross-validation to prevent wrong-movie transfer.
"""

import re

# Valid boundary characters after a Chinese token
_CHINESE_BOUNDARY = {'.', '-', '_', ' ', '[', ']', '(', ')', '（', '）', '【', '】', '/', '\\'}

# Exclusion patterns: files that are definitely NOT main episodes
_EXCLUDE_PATTERNS = [
    r'纯享', r'加更', r'花絮', r'TOP\d', r'精彩', r'预告', r'先导',
    r'番外', r'幕后', r'彩排', r'cut', r'片段', r'集锦', r'合集',
    r'ost', r'原声', r'配乐', r'flac', r'无损', r'mp3',
    r'游戏', r'补丁', r'mod', r'修改器',
]


def extract_year(filename: str) -> int | None:
    """Extract a 4-digit year (1900-2099) from filename."""
    m = re.search(r'(19|20)\d{2}', filename)
    return int(m.group()) if m else None


def is_valid_boundary_after(filename: str, pos: int) -> bool:
    """Check if position pos in filename is a valid boundary (end or in boundary set)."""
    if pos >= len(filename):
        return True
    ch = filename[pos]
    # End of filename (or before extension)
    if ch == '.':
        return True
    if ch in _CHINESE_BOUNDARY:
        return True
    # Chinese characters are OK as boundary only for certain patterns
    # But generally, a Chinese char right after a token means it's part of a longer word
    if '\u4e00' <= ch <= '\u9fff':
        return False
    if ch.isdigit():
        return False
    return True


def is_excluded(filename: str) -> bool:
    """Check if filename matches any exclusion pattern (pure-cut, bonus, OST, etc.)."""
    lower = filename.lower()
    for pat in _EXCLUDE_PATTERNS:
        if re.search(pat, lower):
            return True
    return False


def match_stage_a(filenames: list[str], episode_num: int) -> list[str]:
    """
    Stage A: Digital episode number matching.
    
    E18 matches: E18, .18., 18 (with non-digit boundaries on both sides).
    E18 does NOT match: E180, 1800P, 20241018 (date).
    
    Returns list of matching filenames.
    """
    candidates = set()
    patterns = [
        f'E{episode_num:02d}',      # E01
        f'E{episode_num}',           # E1
        f'EP{episode_num:02d}',     # EP01
        f'EP{episode_num}',          # EP1
    ]

    for fn in filenames:
        if is_excluded(fn):
            continue
        upper = fn.upper()
        matched = False

        for pat in patterns:
            idx = 0
            while True:
                idx = upper.find(pat, idx)
                if idx < 0:
                    break
                # Boundary check: next char after pattern must not be a digit
                after_pos = idx + len(pat)
                if after_pos >= len(upper) or not upper[after_pos].isdigit():
                    matched = True
                    break
                idx += 1
            if matched:
                break

        # Also try bare number: " 180 " or ".180." or "_180_"
        if not matched:
            snum = str(episode_num)
            # Build a regex that ensures non-digit boundaries
            bare_pat = re.compile(
                rf'(?<!\d){re.escape(snum)}(?!\d)'
            )
            if bare_pat.search(upper):
                matched = True

        if matched:
            candidates.add(fn)

    return sorted(candidates)


def match_stage_b(filenames: list[str], chinese_tokens: list[str]) -> list[str]:
    """
    Stage B: Chinese token matching.
    
    Token "第1期上" must be followed by a boundary character or end of filename.
    Token "第1期上" followed by "中" or "纯" is NOT a match.
    
    Returns list of matching filenames.
    """
    if not chinese_tokens:
        return []

    candidates = set()
    for fn in filenames:
        if is_excluded(fn):
            continue
        for token in chinese_tokens:
            idx = fn.find(token)
            if idx < 0:
                continue
            if is_valid_boundary_after(fn, idx + len(token)):
                candidates.add(fn)
                break  # one match per file is enough

    return sorted(candidates)


def match_stage_c(filenames: list[str], desc_hint: str) -> list[str]:
    """
    Stage C: Fuzzy description matching.

    desc_hint (first ~8 chars from TMDB episode description) is matched
    against filenames. Uses sliding window: any 4+ consecutive chars from
    desc_hint appearing in filename counts as a match.
    
    Results must be marked [fuzzy] by the caller.
    """
    if not desc_hint:
        return []

    candidates = set()
    for fn in filenames:
        if is_excluded(fn):
            continue
        # Sliding window: try all substrings of desc_hint with len >= 4
        matched = False
        for win_len in range(len(desc_hint), 3, -1):
            for start in range(0, len(desc_hint) - win_len + 1):
                chunk = desc_hint[start:start + win_len]
                if chunk in fn:
                    candidates.add(fn)
                    matched = True
                    break
            if matched:
                break

    return sorted(candidates)


def match_episode(
    filenames: list[str],
    episode_num: int,
    chinese_tokens: list[str] | None = None,
    desc_hint: str | None = None,
) -> dict:
    """
    Full 3-stage matching for a single episode.
    
    Returns: {
        "episode": int,
        "files": list[str],      # matching filenames
        "stage": "a"|"b"|"c",    # which stage matched
        "fuzzy": bool,           # Stage C match (needs human confirmation)
    }
    """
    chinese_tokens = chinese_tokens or []

    # Stage A
    results = match_stage_a(filenames, episode_num)
    if results:
        return {"episode": episode_num, "files": results, "stage": "a", "fuzzy": False}

    # Stage B
    results = match_stage_b(filenames, chinese_tokens)
    if results:
        return {"episode": episode_num, "files": results, "stage": "b", "fuzzy": False}

    # Stage C
    if desc_hint:
        results = match_stage_c(filenames, desc_hint)
        if results:
            return {"episode": episode_num, "files": results, "stage": "c", "fuzzy": True}

    return {"episode": episode_num, "files": [], "stage": None, "fuzzy": False}


def match_all_episodes(
    filenames: list[str],
    episodes: list[dict],
) -> list[dict]:
    """
    Match all episodes against available filenames.
    
    episodes: list of {"num": int, "tokens": [str], "desc": str|None}
    
    Returns list of match results, one per episode.
    Files matched by earlier episodes are removed from the pool.
    """
    available = list(filenames)
    results = []

    for ep in episodes:
        result = match_episode(
            available,
            ep["num"],
            ep.get("tokens", []),
            ep.get("desc"),
        )
        results.append(result)

        # Remove matched files from pool to prevent double-matching
        for f in result["files"]:
            if f in available:
                available.remove(f)

    return results


def year_validate(filenames: list[str], expected_year: int | str) -> tuple[bool, int | None]:
    """
    Cross-validate: do the filenames contain the expected year?
    
    Returns (match: bool, found_year: int|None).
    If expected_year is empty/None, returns (True, None) — skip validation.
    """
    if not expected_year:
        return (True, None)

    expected = int(expected_year)
    years_found = set()
    for fn in filenames:
        y = extract_year(fn)
        if y is not None:
            years_found.add(y)

    if not years_found:
        return (True, None)  # No year in filenames, can't validate

    return (expected in years_found, min(years_found) if years_found else None)


# ── Self-tests ──────────────────────────────────────────────────────────────

def _test():
    """Run self-tests. Returns (passed, total)."""
    passed = total = 0

    def check(name, got, expected):
        nonlocal passed, total
        total += 1
        if got == expected:
            passed += 1
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name}: got {got!r}, expected {expected!r}")

    print("── Stage A: Digital matching ──")

    # Exact match
    check("E01 exact",
          match_stage_a(["凡人修仙传.E01.4K.mkv"], 1),
          ["凡人修仙传.E01.4K.mkv"])

    # E18 should NOT match E180
    check("E18 != E180",
          match_stage_a(["凡人修仙传.E180.4K.mkv"], 18),
          [])

    # E180 should match E180
    check("E180 == E180",
          match_stage_a(["凡人修仙传.E180.4K.mkv"], 180),
          ["凡人修仙传.E180.4K.mkv"])

    # E18 should NOT match 1800P
    check("E18 != 1800P",
          match_stage_a(["movie.1800P.mkv"], 18),
          [])

    # Bare number with boundaries
    check("bare 180 with dots",
          match_stage_a(["凡人修仙传.180.4K.HDR.mkv"], 180),
          ["凡人修仙传.180.4K.HDR.mkv"])

    # EP format
    check("EP181 format",
          match_stage_a(["FR.EP181.4K.AVC-GM.mp4"], 181),
          ["FR.EP181.4K.AVC-GM.mp4"])

    # Exclusion: pure-cut should not match
    check("exclude 纯享",
          match_stage_a(["第2期上纯享版.mp4"], 2),
          [])

    print("\n── Stage B: Chinese token matching ──")

    check("第1期上 exact",
          match_stage_b(["第1期上.mp4"], ["第1期上"]),
          ["第1期上.mp4"])

    check("第1期上 with 4K",
          match_stage_b(["第1期上 [4K].mp4"], ["第1期上"]),
          ["第1期上 [4K].mp4"])

    # 第1期上 followed by 中 should NOT match
    check("第1期上 != 第1期上中",
          match_stage_b(["第1期上中纯享版.mp4"], ["第1期上"]),
          [])

    check("第1期下 exact",
          match_stage_b(["第1期下.mp4", "第1期下纯享.mp4"], ["第1期下"]),
          ["第1期下.mp4"])  # 纯享 excluded by is_excluded, 第1期下 matched

    # Boundary: 第1期下 followed by . or [
    check("第1期下 with bracket",
          match_stage_b(["第1期下【终版】.mp4"], ["第1期下"]),
          ["第1期下【终版】.mp4"])

    print("\n── Stage C: Fuzzy matching ──")

    check("desc_hint substring",
          match_stage_c(["20240908薛之谦陈立农双版本.mp4"], "薛之谦陈立农唱尽"),
          ["20240908薛之谦陈立农双版本.mp4"])

    check("desc_hint no match",
          match_stage_c(["something_else.mp4"], "薛之谦陈立农"),
          [])

    print("\n── Year validation ──")

    check("year match",
          year_validate(["后室.2026.1080P.mp4"], 2026),
          (True, 2026))

    check("year mismatch",
          year_validate(["后室2023.1080P.mp4"], 2026),
          (False, 2023))

    check("no year in filename",
          year_validate(["后室.1080P.mp4"], 2026),
          (True, None))

    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed == total:
        print("ALL TESTS PASSED ✓")
    else:
        print(f"FAILED: {total - passed} tests")

    return passed, total


if __name__ == "__main__":
    _test()
