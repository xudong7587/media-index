from __future__ import annotations

from dataclasses import replace

from app.clients.pansou import infer_share_provider
from app.domain.media import ResourceCandidate


def provider_accepts_share(provider: str, share_url: str) -> bool:
    """Return whether an execution provider can safely inspect this share.

    New Quark work always uses the native Quark adapter. Historical QAS rows
    remain readable, but a newly discovered Quark URL must never select QAS.
    """
    cloud_type, inferred_provider = infer_share_provider(share_url)
    return (provider == "quark" and cloud_type == "quark") or inferred_provider == provider


def provider_accepts_candidate(provider: str, candidate: ResourceCandidate) -> bool:
    if provider == "quark":
        return candidate.cloud_type == "quark"
    return candidate.provider == provider


def candidate_for_provider(provider: str, candidate: ResourceCandidate) -> ResourceCandidate:
    """Persist the selected executor, never the incidental legacy label."""
    if provider == "quark" and candidate.cloud_type == "quark":
        return replace(candidate, provider="quark")
    return candidate
