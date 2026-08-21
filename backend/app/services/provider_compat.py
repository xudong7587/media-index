from __future__ import annotations

from dataclasses import replace

from app.clients.pansou import infer_share_provider
from app.domain.media import ResourceCandidate


def provider_accepts_share(provider: str, share_url: str) -> bool:
    """Return whether an execution provider can safely inspect this share.

    A Quark share has two possible executors: the existing QAS adapter and the
    native Quark adapter.  The share URL itself identifies the cloud, not which
    of those executors the user chose, so native Quark must be matched by cloud
    type rather than the legacy QAS provider label.
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
