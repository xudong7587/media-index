from __future__ import annotations

from app.clients.qas import QasClient
from app.domain.media import ProviderExecutionResult
from app.providers.base import ProviderCapability, ProviderKey, TransferPlan
from app.providers.status import normalize_provider_stage
from app.services.qas_executor import execute_qas_plan, qas_saved_files_confirmed
from app.services.share_inspector import ShareInspection, inspect_share


class QasTransferProvider:
    key = ProviderKey.QAS
    cloud_type = "quark"

    def __init__(self, client: QasClient | None = None) -> None:
        self.client = client or QasClient()

    def configured(self) -> bool:
        return self.client.configured()

    def capabilities(self) -> set[ProviderCapability]:
        return {
            ProviderCapability.SHARE_INSPECTION,
            ProviderCapability.SELECTIVE_TRANSFER,
            ProviderCapability.RENAME_PLAN,
            ProviderCapability.SAVE_PATH_INSPECTION,
            ProviderCapability.EXECUTION_RECONCILE,
        }

    def inspect_share(self, share_url: str) -> ShareInspection:
        return inspect_share(self.client, share_url)

    # These two delegates keep the existing inspectors usable while their
    # dependency is supplied through the provider facade.
    def share_detail(self, share_url: str) -> dict:
        return self.client.share_detail(share_url)

    def inspect_save_path(self, path: str) -> dict:
        return self.client.savepath_detail(path)

    def savepath_detail(self, path: str) -> dict:
        return self.inspect_save_path(path)

    def execute(self, plan: TransferPlan) -> ProviderExecutionResult:
        result = execute_qas_plan(
            plan.target,
            plan.resolution,
            plan.save_path,
            qas=self.client,
            allow_review_confirmed=plan.allow_review_confirmed,
        )
        return ProviderExecutionResult(
            ok=result.ok,
            stage=normalize_provider_stage(result.stage),
            message=result.message,
            external_job_id="",
            executed_items=result.executed_pairs,
            confirmed=result.confirmed,
            outputs=result.outputs,
        )

    def reconcile(self, save_path: str, expected_names: list[str]) -> bool:
        return qas_saved_files_confirmed(self.client, save_path, expected_names)
