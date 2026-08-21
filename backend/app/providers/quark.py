from __future__ import annotations

import time
from hashlib import sha256

from app.clients.quark import QuarkClient, QuarkError, QuarkShareFile
from app.domain.media import ProviderExecutionResult, SourceFile
from app.providers.base import ProviderCapability, ProviderKey, TransferPlan
from app.services.paths import is_allowed_save_path
from app.services.share_inspector import ShareInspection


class QuarkTransferProvider:
    """Native Quark share reception with a cloud-only staging folder.

    This provider never creates a local media copy.  A failed reception is
    deliberately left in the Quark staging folder for the forthcoming recovery
    workflow rather than guessing which remote items are safe to delete.
    """

    key = ProviderKey.QUARK
    cloud_type = "quark"

    def __init__(self, client: QuarkClient | None = None) -> None:
        self.client = client or QuarkClient()

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
        if not self.client.configured():
            return ShareInspection(
                False,
                share_url,
                error="夸克 Cookie 未配置或格式无效，暂时无法验证分享内容",
                verification_unavailable=True,
            )
        try:
            snapshot = self.client.inspect_share(share_url)
        except QuarkError as exc:
            message = str(exc)
            return ShareInspection(
                False,
                share_url,
                error=message,
                verification_unavailable=_verification_temporarily_unavailable(message),
            )
        return ShareInspection(
            True,
            share_url,
            tuple(
                SourceFile(
                    item.name,
                    item.size,
                    f"/{item.parent_id}/{item.name}",
                    provider_file_id=item.file_id,
                    provider_parent_id=item.parent_id,
                )
                for item in snapshot.files
                if not item.is_dir
            ),
        )

    def inspect_save_path(self, path: str) -> dict:
        directory = self.client.directory_id(self._provider_path(path))
        items = self.client.list_directory(directory) if directory else ()
        return {
            "success": True,
            "data": {
                "list": [{"file_name": item.name, "size": item.size, "dir": item.is_dir} for item in items],
            },
        }

    def savepath_detail(self, path: str) -> dict:
        return self.inspect_save_path(path)

    def execute(self, plan: TransferPlan) -> ProviderExecutionResult:
        if not is_allowed_save_path(plan.target.category or plan.target.media_type, plan.save_path, target="cloud", provider="quark"):
            return ProviderExecutionResult(False, "provider_failed", "夸克目标目录超出允许的保存范围")
        received_started = False
        final_path = self._provider_path(plan.save_path)
        try:
            snapshot = self.client.inspect_share(plan.resolution.share_url)
            selections = _select_snapshot_files(snapshot.files, plan.resolution.rename_pairs)
            fingerprint = sha256(
                (plan.resolution.share_url + "\n" + "\n".join(item.file_id for item, _ in selections)).encode("utf-8")
            ).hexdigest()[:16]
            staging_path = f"{self.client.settings.quark_staging_path.rstrip('/')}/{fingerprint}"
            staging_id = self.client.ensure_directory(staging_path)
            before = {item.file_id for item in self.client.list_directory(staging_id) if not item.is_dir}
            task_id = self.client.save_share_files(snapshot, [item.file_id for item, _ in selections], staging_id)
            received_started = True
            received = self._wait_received_files(task_id, staging_id, before, len(selections))
            pairs_by_source = {source.file_id: pair for source, pair in selections}
            matched = _match_received_files(selections, received)
            if len(matched) != len(selections):
                raise QuarkError("夸克转存已提交，但暂存目录无法唯一识别全部新文件")
            for source_id, item in matched.items():
                self.client.rename_file(item.file_id, pairs_by_source[source_id].replacement)
            final_id = self.client.ensure_directory(final_path)
            self.client.move_files([item.file_id for item in matched.values()], final_id)
            expected_names = [pair.replacement for _source, pair in selections]
            if not self.reconcile(plan.save_path, expected_names):
                raise QuarkError("夸克转存已执行，但目标目录结果尚未确认")
        except QuarkError as exc:
            return ProviderExecutionResult(
                False,
                "provider_partial" if received_started else "provider_failed",
                f"{exc}（目标目录：{final_path}）",
            )
        return ProviderExecutionResult(
            True,
            "provider_completed",
            "夸克文件已完成转存、重命名和目标目录确认",
            executed_items=len(selections),
            confirmed=True,
            outputs=tuple({"file_name": pair.replacement} for _source, pair in selections),
        )

    def reconcile(self, save_path: str, expected_names: list[str]) -> bool:
        directory = self.client.directory_id(self._provider_path(save_path))
        if not directory:
            return False
        actual = {item.name for item in self.client.list_directory(directory) if not item.is_dir}
        return bool(expected_names) and set(expected_names).issubset(actual)

    def _wait_received_files(self, task_id: str, staging_id: str, before: set[str], expected_count: int):
        deadline = time.monotonic() + min(30, max(1, int(self.client.settings.quark_request_timeout_seconds)))
        while True:
            task = self.client.task(task_id)
            status = str(task.get("status") or task.get("state") or "").lower()
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise QuarkError("夸克转存任务失败")
            current = [item for item in self.client.list_directory(staging_id) if not item.is_dir and item.file_id not in before]
            if len(current) >= expected_count:
                return current
            if time.monotonic() >= deadline:
                raise QuarkError("夸克转存任务等待超时，暂存目录保留以便后续恢复")
            time.sleep(1)

    def _provider_path(self, logical_path: str) -> str:
        root = self.client.settings.quark_root_path.rstrip("/")
        cloud_root = self.client.settings.cloud_save_path.rstrip("/")
        value = str(logical_path or "").replace("\\", "/")
        if value == root or value.startswith(f"{root}/"):
            return value
        relative = value[len(cloud_root):] if cloud_root and value.startswith(cloud_root) else value
        return f"{root}/{relative.lstrip('/')}"


def _select_snapshot_files(files: tuple[QuarkShareFile, ...], rename_pairs):
    selected = []
    used: set[str] = set()
    for pair in rename_pairs:
        matches = [
            item
            for item in files
            if not item.is_dir
            and item.file_id not in used
            and (
                (pair.source_id and item.file_id == pair.source_id)
                or (item.name == pair.source_name and (not pair.source_size or item.size == pair.source_size))
            )
        ]
        if len(matches) != 1:
            raise QuarkError(f"夸克分享内容已变化，无法唯一定位待转存文件：{pair.source_name}")
        used.add(matches[0].file_id)
        selected.append((matches[0], pair))
    return selected


def _match_received_files(selections, received):
    matched = {}
    used: set[str] = set()
    for source, _pair in selections:
        candidates = [
            item for item in received
            if item.file_id not in used and item.name == source.name and (not source.size or item.size == source.size)
        ]
        if len(candidates) == 1:
            matched[source.file_id] = candidates[0]
            used.add(candidates[0].file_id)
    return matched


def _verification_temporarily_unavailable(message: str) -> bool:
    return any(marker in message for marker in ("Cookie 无效", "Cookie 未配置", "连接失败", "请求过于频繁", "HTTP 5"))
