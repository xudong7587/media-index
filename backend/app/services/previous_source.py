from __future__ import annotations

import unicodedata

from app.domain.media import MediaTarget
from app.services.candidate_ranker import compact, extract_seasons


def recover_previous_share_urls(target: MediaTarget, qas, limit: int = 3) -> tuple[str, ...]:
    """Recover legacy QAS links when pre-0.2 tracking rows have no source URL."""
    try:
        tasks = qas.tasklist()
    except Exception:
        return ()

    aliases = [compact(value) for value in target.search_titles if compact(value)]
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        share_url = str(task.get("shareurl") or task.get("share_url") or "").strip()
        if "pan.quark.cn" not in share_url or share_url in seen:
            continue
        evidence_text = " ".join(
            str(task.get(key) or "")
            for key in ("taskname", "savename", "savepath", "pattern", "replace")
        )
        evidence = compact(evidence_text)
        title_score = max((100 - alias_index * 10 for alias_index, alias in enumerate(aliases) if alias in evidence), default=0)
        if title_score <= 0:
            continue
        seasons = extract_seasons(unicodedata.normalize("NFKC", evidence_text).casefold())
        if target.season_number is not None and seasons and target.season_number not in seasons:
            continue
        season_score = 30 if target.season_number is not None and target.season_number in seasons else 0
        seen.add(share_url)
        scored.append((title_score + season_score, index, share_url))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return tuple(item[2] for item in scored[: max(1, limit)])
