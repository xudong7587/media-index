from __future__ import annotations

from app.clients.moviepilot_115 import MoviePilot115Client, MoviePilot115Error
from app.domain.media import ProviderExecutionResult
from app.providers.base import ProviderCapability, ProviderKey, TransferPlan
from app.services.share_inspector import ShareInspection


class MoviePilot115TransferProvider:
    key = ProviderKey.MOVIEPILOT_115
    cloud_type = "115"

    def __init__(self, client: MoviePilot115Client | None = None) -> None:
        self.client = client or MoviePilot115Client()

    def configured(self) -> bool:
        return self.client.configured()

    def capabilities(self) -> set[ProviderCapability]:
        return {ProviderCapability.EXTERNAL_ORGANIZE}

    def inspect_share(self, share_url: str) -> ShareInspection:
        return ShareInspection(False, share_url, error="external_provider_does_not_inspect_share")

    def inspect_save_path(self, path: str) -> dict:
        return {}

    def execute(self, plan: TransferPlan) -> ProviderExecutionResult:
        try:
            submission = self.client.submit_share(plan.resolution.share_url)
        except MoviePilot115Error as exc:
            return ProviderExecutionResult(False, "provider_failed", str(exc))
        outputs = ()
        if submission.save_parent_path or submission.save_parent_id:
            outputs = ({
                "save_parent_path": submission.save_parent_path,
                "save_parent_id": submission.save_parent_id,
            },)
        return ProviderExecutionResult(
            True,
            "provider_triggered",
            "已提交给 MoviePilot；后续转存、整理和 STRM 由 MoviePilot 处理",
            executed_items=1,
            outputs=outputs,
        )

    def reconcile(self, save_path: str, expected_names: list[str]) -> bool:
        return False
