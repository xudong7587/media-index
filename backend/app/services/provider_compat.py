from __future__ import annotations

from dataclasses import replace

from app.clients.pansou import infer_share_provider
from app.domain.media import ResourceCandidate


def provider_accepts_share(provider: str, share_url: str) -> bool:
    """Return whether an execution provider can safely inspect this share.

    New Quark work always selects the native Quark adapter.  An explicitly
    supplied historical QAS adapter may still inspect Quark shares so existing
    saved tasks and compatibility callers remain readable after upgrading.
    """
    cloud_type, inferred_provider = infer_share_provider(share_url)
    return (
        provider in {"quark", "qas"} and cloud_type == "quark"
    ) or inferred_provider == provider


def provider_accepts_candidate(provider: str, candidate: ResourceCandidate) -> bool:
    if provider in {"quark", "qas"}:
        return candidate.cloud_type == "quark"
    return candidate.provider == provider


def candidate_for_provider(provider: str, candidate: ResourceCandidate) -> ResourceCandidate:
    """Persist the selected executor, never the incidental legacy label."""
    if provider in {"quark", "qas"} and candidate.cloud_type == "quark":
        return replace(candidate, provider=provider)
    return candidate
