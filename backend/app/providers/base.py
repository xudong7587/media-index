from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.domain.media import LinkResolution, MediaTarget, ProviderExecutionResult
from app.services.share_inspector import ShareInspection


class ProviderKey(StrEnum):
    QAS = "qas"
    MOVIEPILOT_115 = "moviepilot_115"


class ProviderCapability(StrEnum):
    SHARE_INSPECTION = "share_inspection"
    SELECTIVE_TRANSFER = "selective_transfer"
    RENAME_PLAN = "rename_plan"
    SAVE_PATH_INSPECTION = "save_path_inspection"
    EXECUTION_RECONCILE = "execution_reconcile"
    EXTERNAL_ORGANIZE = "external_organize"


@dataclass(frozen=True)
class TransferPlan:
    target: MediaTarget
    resolution: LinkResolution
    save_path: str
    allow_review_confirmed: bool = False


class TransferProvider(Protocol):
    key: ProviderKey
    cloud_type: str

    def configured(self) -> bool: ...

    def capabilities(self) -> set[ProviderCapability]: ...

    def inspect_share(self, share_url: str) -> ShareInspection: ...

    def inspect_save_path(self, path: str) -> dict: ...

    def execute(self, plan: TransferPlan) -> ProviderExecutionResult: ...

    def reconcile(self, save_path: str, expected_names: list[str]) -> bool: ...
