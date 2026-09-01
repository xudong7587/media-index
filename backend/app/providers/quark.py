from __future__ import annotations

import time
from hashlib import sha256
from uuid import uuid4

from app.clients.quark import QuarkClient, QuarkError, QuarkShareFile
from app.domain.media import ProviderExecutionResult, SourceFile
from app.providers.base import ProviderCapability, ProviderKey, TransferPlan
from app.services.paths import is_allowed_save_path, is_cloud_download_staging_path, normalize_cloud_root
from app.services.share_inspector import ShareInspection


class QuarkTransferProvider:
    """Native Quark share reception with a cloud-only staging folder.

    This provider never creates a local media copy.  A failed reception is
    deliberately left in the Quark staging folder for the forthcoming recovery
    workflow rather than guessing which remote items are safe to delete.
    """

    key = ProviderKey.QUARK
    cloud_type = "quark"
    share_save_batch_size = 50

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
        logical_path = str(path or "").replace("\\", "/")
        directory = self.client.directory_id(self._provider_path(path))
        if not directory:
            return {
                "success": True,
                "data": {
                    "exists": False,
                    "paths": [{"name": part} for part in logical_path.strip("/").split("/") if part],
                    "list": [],
                },
            }
        items = self.client.list_directory(directory)
        return {
            "success": True,
            "data": {
                "exists": True,
                "paths": [{"name": part} for part in logical_path.strip("/").split("/") if part],
                "list": [{"file_name": item.name, "size": item.size, "dir": item.is_dir} for item in items],
            },
        }

    def savepath_detail(self, path: str) -> dict:
        return self.inspect_save_path(path)

    def execute(self, plan: TransferPlan) -> ProviderExecutionResult:
        staging_plan = (
            plan.destination_scope == "cloud_download"
            and is_cloud_download_staging_path(
                "quark",
                plan.save_path,
                plan.cloud_download_child,
                settings=self.client.settings,
            )
        )
        if not is_allowed_save_path(
            plan.target.category or plan.target.media_type,
            plan.save_path,
            target="cloud",
            provider="quark",
        ) and not staging_plan and not _is_direct_link_cloud_download_child(plan, self.client.settings):
            return ProviderExecutionResult(False, "provider_failed", "夸克目标目录超出允许的保存范围")
        received_started = False
        final_path = self._provider_path(plan.save_path)
        try:
            snapshot = self.client.inspect_share(plan.resolution.share_url)
            selections = _select_snapshot_files(snapshot.files, plan.resolution.rename_pairs)
            fingerprint = sha256(
                (plan.resolution.share_url + "\n" + "\n".join(item.file_id for item, _ in selections)).encode("utf-8")
            ).hexdigest()[:16]
            attempt_id = uuid4().hex[:12]
            staging_path = f"{self.client.settings.quark_staging_path.rstrip('/')}/{fingerprint}/{attempt_id}"
            pairs_by_source = {source.file_id: pair for source, pair in selections}
            matched = {}
            for parent_id, parent_selections in _group_selections_by_parent(selections):
                parent_key = sha256(parent_id.encode("utf-8")).hexdigest()[:12]
                staging_id = self.client.ensure_directory(f"{staging_path}/{parent_key}")
                for batch in _selection_batches(parent_selections, self.share_save_batch_size):
                    before = {
                        item.file_id
                        for item in _list_directory_complete(self.client, staging_id)
                        if not item.is_dir
                    }
                    try:
                        task_id = self.client.save_share_files(
                            snapshot,
                            [item.file_id for item, _ in batch],
                            staging_id,
                        )
                    except QuarkError as exc:
                        raise QuarkError(f"夸克转存提交失败：{exc}") from exc
                    received_started = True
                    matched.update(self._wait_received_files(task_id, staging_id, before, batch))
            if len(matched) != len(selections):
                raise QuarkError("夸克转存已提交，但暂存目录无法唯一识别全部新文件")
            for source_id, item in matched.items():
                self.client.rename_file(item.file_id, pairs_by_source[source_id].replacement)
            final_id = self.client.ensure_directory(final_path)
            move_task = self.client.move_files([item.file_id for item in matched.values()], final_id)
            wait_task = getattr(self.client, "wait_task", None)
            if callable(wait_task):
                wait_task(move_task)
            expected_names = [pair.replacement for _source, pair in selections]
            if not self._wait_reconciled(plan.save_path, expected_names):
                raise QuarkError("夸克转存已执行，但目标目录结果尚未确认")
            verified_outputs = tuple(
                {
                    "file_id": matched[source.file_id].file_id,
                    "parent_id": final_id,
                    "file_name": pair.replacement,
                    "size": int(matched[source.file_id].size or 0),
                    "path": plan.save_path,
                }
                for source, pair in selections
            )
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
            outputs=verified_outputs,
        )

    def reconcile(self, save_path: str, expected_names: list[str]) -> bool:
        directory = self.client.directory_id(self._provider_path(save_path))
        if not directory:
            return False
        actual = {item.name for item in _list_directory_complete(self.client, directory) if not item.is_dir}
        return bool(expected_names) and set(expected_names).issubset(actual)

    def _wait_received_files(self, task_id: str, staging_id: str, before: set[str], selections):
        deadline = time.monotonic() + min(30, max(1, int(self.client.settings.quark_request_timeout_seconds)))
        retry_index = 0
        task_completed = False
        while True:
            if not task_completed:
                try:
                    task = self.client.task(task_id, retry_index=retry_index)
                except QuarkError as exc:
                    raise QuarkError(f"夸克转存任务查询失败：{exc}") from exc
                retry_index += 1
                status = str(task.get("status") or task.get("state") or "").casefold()
                if status in {"3", "4", "failed", "error", "cancelled", "canceled"}:
                    raise QuarkError("夸克转存任务失败")
                task_completed = status in {"2", "success", "succeeded", "done", "completed", "finished"}
            current = [
                item
                for item in _list_directory_complete(self.client, staging_id)
                if not item.is_dir and item.file_id not in before
            ]
            matched = _match_received_files(selections, current)
            if task_completed and len(matched) == len(selections):
                return matched
            if time.monotonic() >= deadline:
                if task_completed:
                    raise QuarkError("夸克转存已完成，但暂存目录文件信息尚未稳定，暂存目录已保留")
                raise QuarkError("夸克转存任务等待超时，暂存目录保留以便后续恢复")
            time.sleep(0.5)

    def _wait_reconciled(self, save_path: str, expected_names: list[str]) -> bool:
        deadline = time.monotonic() + min(30, max(1, int(self.client.settings.quark_request_timeout_seconds)))
        while True:
            if self.reconcile(save_path, expected_names):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)

    def _provider_path(self, logical_path: str) -> str:
        root = self.client.settings.quark_root_path.rstrip("/")
        cloud_root = self.client.settings.cloud_save_path.rstrip("/")
        value = str(logical_path or "").replace("\\", "/")
        download_resolver = getattr(self.client.settings, "provider_cloud_download_path", None)
        configured_download_root = str(download_resolver("quark") or "").strip() if callable(download_resolver) else ""
        download_root = (configured_download_root.rstrip("/") or "/") if configured_download_root else ""
        if download_root and (
            (download_root == "/" and value.startswith("/"))
            or value == download_root
            or value.startswith(f"{download_root}/")
        ):
            return value
        if value == root or value.startswith(f"{root}/"):
            return value
        relative = value[len(cloud_root):] if cloud_root and value.startswith(cloud_root) else value
        return f"{root}/{relative.lstrip('/')}"


def _is_direct_link_cloud_download_child(plan: TransferPlan, settings: object) -> bool:
    """Allow only verified direct-link plans into a configured download-root child."""
    pairs = tuple(plan.resolution.rename_pairs)
    if not pairs or not all("direct_link" in pair.reasons for pair in pairs):
        return False
    resolver = getattr(settings, "provider_cloud_download_path", None)
    if not callable(resolver):
        return False
    try:
        root = normalize_cloud_root(resolver("quark"))
        target = normalize_cloud_root(plan.save_path)
    except (TypeError, ValueError):
        return False
    if root == "/":
        relative = target.lstrip("/")
    else:
        prefix = f"{root}/"
        if not target.startswith(prefix):
            return False
        relative = target[len(prefix):]
    return bool(relative) and "/" not in relative


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


def _group_selections_by_parent(selections):
    grouped = {}
    for selection in selections:
        parent_id = selection[0].parent_id or "0"
        grouped.setdefault(parent_id, []).append(selection)
    return tuple((parent_id, tuple(items)) for parent_id, items in grouped.items())


def _selection_batches(selections, batch_size: int):
    safe_batch_size = max(1, int(batch_size))
    return tuple(tuple(selections[index:index + safe_batch_size]) for index in range(0, len(selections), safe_batch_size))


def _list_directory_complete(client, directory_id: str):
    listing = getattr(client, "list_directory_complete", None)
    return listing(directory_id) if callable(listing) else client.list_directory(directory_id)


def _verification_temporarily_unavailable(message: str) -> bool:
    return any(marker in message for marker in ("Cookie 无效", "Cookie 未配置", "连接失败", "请求过于频繁", "HTTP 5"))
