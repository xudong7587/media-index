"""Native share verification followed by ranked 115 offline-download fallback."""
from dataclasses import replace

from app.clients.pansou import PansouClient
from app.core.config import get_settings
from app.domain.magnet import magnet_key, magnet_title
from app.domain.media import LinkResolution
from app.services.candidate_ranker import rank_resource_candidates
from app.services.quality_priority import quality_priority_score


def resolve_discovery_source(resolver, target, previous_share_urls=(), *, allow_magnets=False,
                             excluded_share_urls=(), **kwargs):
    if not allow_magnets:
        return resolver(target, previous_share_urls, **kwargs)
    excluded = set(excluded_share_urls)
    urls = tuple(url for url in ((previous_share_urls,) if isinstance(previous_share_urls, str) else tuple(previous_share_urls))
                 if url not in excluded)
    items = [{"share_url": url, "title": magnet_title(url), "cloud_type": "115", "provider": "p115"}
             for url in urls if magnet_key(url)]
    upstream = kwargs.pop("pansou", None) or PansouClient()

    class RecordingSearch:
        def search_detailed(self, *args, **options):
            # Rank the full bounded pool before the display/verification limits.
            options["limit"] = 1000
            response = upstream.search_detailed(*args, **options)
            items.extend(item for item in response.items if magnet_key(str(item.get("share_url") or "")))
            return replace(response, items=[item for item in response.items
                           if not magnet_key(str(item.get("share_url") or ""))
                           and item.get("share_url") not in excluded])

    native = resolver(target, tuple(url for url in urls if not magnet_key(url)), pansou=RecordingSearch(), **kwargs)
    ranked = rank_resource_candidates(target, items)
    magnets = {}
    for candidate in ranked:
        if candidate.rejected or "title_exact_or_contained" not in candidate.reasons:
            continue
        # Magnets cannot be inspected before submission: demand explicit year
        # and season evidence instead of borrowing the search query as proof.
        if target.series_year and "year_match" not in candidate.reasons:
            continue
        if target.season_number and "season_exact" not in candidate.reasons:
            continue
        magnets.setdefault(magnet_key(candidate.share_url), replace(candidate, reasons=(*candidate.reasons, "cloud_download_candidate")))
    settings = get_settings()
    ordered = sorted(magnets.values(), key=lambda item: (
        -quality_priority_score(f"{item.title} {item.content}", settings.quality_priority_keywords_json),
        -item.score, item.share_url,
    ))
    reviewed = (*native.reviewed_candidates, *ordered[:50])
    if native.ok or not ordered:
        return replace(native, reviewed_candidates=reviewed)
    return LinkResolution(True, "cloud_download_ready", "115 分享未找到可用文件，已按质量优先级选择磁力云下载",
                          ordered[0].share_url, ordered[0].source or "pansou", reviewed_candidates=reviewed,
                          errors=native.errors)
