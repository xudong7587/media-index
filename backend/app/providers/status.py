from __future__ import annotations


LEGACY_PROVIDER_STAGE_MAP = {
    "qas_transferring": "provider_submitting",
    "qas_triggered": "provider_triggered",
    "qas_completed": "provider_completed",
    "qas_failed": "provider_failed",
    "qas_confirmation_timeout": "provider_confirmation_timeout",
}


def normalize_provider_stage(stage: str | None) -> str:
    value = str(stage or "")
    return LEGACY_PROVIDER_STAGE_MAP.get(value, value)


def transfer_status_for_stage(stage: str | None) -> str:
    normalized = normalize_provider_stage(stage)
    if normalized in {"provider_completed", "already_saved"}:
        return "done"
    if normalized == "provider_triggered":
        return "triggered"
    if normalized == "needs_review":
        return "needs_review"
    return "failed"


def normalize_provider_record(record: dict) -> dict:
    normalized = dict(record)
    if "stage" in normalized:
        normalized["stage"] = normalize_provider_stage(normalized.get("stage"))
    return normalized
