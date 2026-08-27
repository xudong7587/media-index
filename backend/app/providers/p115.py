from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import time

from app.clients.p115 import P115Client, P115Error
from app.domain.media import ProviderExecutionResult, SourceFile
from app.providers.base import ProviderCapability, ProviderKey, TransferPlan
from app.services.share_inspector import ShareInspection
from app.services.paths import is_allowed_save_path


class P115TransferProvider:
    key = ProviderKey.P115
    cloud_type = "115"

    def __init__(self, client: P115Client | None = None) -> None:
        self.client = client or P115Client()

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
                error="115 Cookie 未配置或格式无效，暂时无法验证分享内容",
                verification_unavailable=True,
            )
        try:
            snapshot = self.client.inspect_share(share_url)
        except P115Error as exc:
            message = str(exc)
            return ShareInspection(
                False,
                share_url,
                error=message,
                verification_unavailable=_verification_temporarily_unavailable(message),
            )
        files = tuple(
            SourceFile(
                item.name,
                item.size,
                item.path,
                provider_file_id=item.file_id,
                provider_parent_id=item.parent_id,
            )
            for item in snapshot.files
        )
        return ShareInspection(True, share_url, files)
    def inspect_save_path(self, path: str) -> dict:
        logical_path = str(path or "").replace("\\", "/")
        provider_path = self._provider_path(path)
        cid = self.client.directory_id(provider_path)
        if cid == "0" and provider_path != "/":
            return {
                "success": True,
                "data": {
                    "exists": False,
                    "paths": [{"name": part} for part in logical_path.strip("/").split("/") if part],
                    "list": [],
                },
            }
        items = self.client.list_directory(cid)
        return {
            "success": True,
            "data": {
                "exists": True,
                # The scanner validates the logical MediaIndex destination it
                # requested.  The provider root is an implementation detail
                # and must not leak into this compatibility response.
                "paths": [{"name": part} for part in logical_path.strip("/").split("/") if part],
                "list": [
                    {"file_name": item.name, "size": item.size, "dir": item.is_dir}
                    for item in items
                ]
            },
        }

    def savepath_detail(self, path: str) -> dict:
        return self.inspect_save_path(path)

    def execute(self, plan: TransferPlan) -> ProviderExecutionResult:
        received_started = False
        final_path = self._provider_path(plan.save_path)
        try:
            snapshot = self.client.inspect_share(plan.resolution.share_url)
            selections = _select_snapshot_files(snapshot.files, plan.resolution.rename_pairs)
            selected = [item for item, _pair in selections]

            fingerprint = sha256(
                (plan.resolution.share_url + "\n" + "\n".join(item.file_id for item in selected)).encode("utf-8")
            ).hexdigest()[:16]
            staging_path = f"{self.client.settings.p115_staging_path.rstrip('/')}/{fingerprint}"
            staging_cid = _ensure_directory_with_retry(self.client, staging_path)
            staging_items = [item for item in self.client.list_directory(staging_cid) if not item.is_dir]
            resumed = _match_received_staging_files(selections, staging_items)
            missing = [item for item in selected if item.file_id not in resumed]
            before_ids = {item.file_id for item in staging_items}
            share = snapshot.share
            if missing:
                self.client.receive_share_files(share, [item.file_id for item in missing], staging_cid)
            received_started = bool(resumed or missing)
            deadline = time.monotonic() + min(30, max(1, self.client.settings.p115_request_timeout_seconds))
            received = list(resumed.values())
            if missing:
                while time.monotonic() < deadline:
                    new_items = [item for item in self.client.list_directory(staging_cid) if item.file_id not in before_ids]
                    received = [*resumed.values(), *new_items]
                    if len(received) >= len(selected):
                        break
                    time.sleep(1)
            rename_pairs: list[tuple[str, str]] = []
            received_ids: list[str] = []
            verified_outputs: list[dict] = []
            used_received_ids: set[str] = set()
            for source, rename in selections:
                matches = [
                    item
                    for item in received
                    if not item.is_dir
                    and item.file_id not in used_received_ids
                    and item.name == source.name
                    and (not source.size or item.size == source.size)
                ]
                if len(matches) != 1:
                    matches = [
                        item
                        for item in received
                        if not item.is_dir
                        and item.file_id not in used_received_ids
                        and item.name == source.name
                    ]
                if len(matches) != 1:
                    raise P115Error("115 已接收分享，但无法唯一识别新文件，请在暂存目录检查")
                received_item = matches[0]
                used_received_ids.add(received_item.file_id)
                received_ids.append(received_item.file_id)
                rename_pairs.append((received_item.file_id, rename.replacement))
                verified_outputs.append(
                    {
                        "file_id": received_item.file_id,
                        "file_name": rename.replacement,
                        "size": int(received_item.size or 0),
                        "path": plan.save_path,
                    }
                )

            # Do not leave an empty destination behind when share reception or
            # staging fails.  The final folder is only needed after every
            # selected file has appeared in the isolated staging directory.
            final_cid = _ensure_directory_with_retry(self.client, final_path)
            self.client.rename(rename_pairs)
            if staging_cid != final_cid:
                self.client.move(received_ids, final_cid)
            expected_names = [pair.replacement for pair in plan.resolution.rename_pairs]
            if not self.reconcile(plan.save_path, expected_names):
                raise P115Error("115 转存已执行，但目标目录结果尚未确认")
            for output in verified_outputs:
                output["parent_id"] = final_cid
        except P115Error as exc:
            return ProviderExecutionResult(
                False,
                "provider_partial" if received_started else "provider_failed",
                f"{exc}（目标目录：{final_path}）",
            )
        return ProviderExecutionResult(
            True,
            "provider_completed",
            "115 文件已完成转存、重命名和目标目录确认",
            executed_items=len(plan.resolution.rename_pairs),
            confirmed=True,
            outputs=tuple(verified_outputs),
        )

    def reconcile(self, save_path: str, expected_names: list[str]) -> bool:
        provider_path = self._provider_path(save_path)
        cid = self.client.directory_id(provider_path)
        if cid == "0" and provider_path != "/":
            return False
        actual = {item.name for item in self.client.list_directory(cid) if not item.is_dir}
        return bool(expected_names) and set(expected_names).issubset(actual)

    def _provider_path(self, logical_path: str) -> str:
        p115_root = self.client.settings.p115_root_path.rstrip("/")
        cloud_root = self.client.settings.cloud_save_path.rstrip("/")
        value = str(logical_path or "").replace("\\", "/")
        if value == p115_root or value.startswith(f"{p115_root}/"):
            return value
        relative = value[len(cloud_root):] if cloud_root and value.startswith(cloud_root) else value
        return f"{p115_root}/{relative.lstrip('/')}"


class P115LocalTransferProvider(P115TransferProvider):
    """Download selected 115 share files into a configured NAS-mounted directory."""

    def execute(self, plan: TransferPlan) -> ProviderExecutionResult:
        category = plan.target.category or plan.target.media_type
        if not is_allowed_save_path(category, plan.save_path, target="local", provider="p115"):
            return ProviderExecutionResult(False, "provider_failed", "115 本地目录超出允许的保存范围")
        try:
            snapshot = self.client.inspect_share(plan.resolution.share_url)
            selections = _select_snapshot_files(snapshot.files, plan.resolution.rename_pairs)
            destination = Path(plan.save_path)
            destination.mkdir(parents=True, exist_ok=True)
            outputs: list[dict] = []
            for source, rename in selections:
                target = destination / rename.replacement
                self.client.download_share_file(snapshot.share, source, target)
                if not target.is_file() or target.stat().st_size <= 0:
                    raise P115Error(f"115 本地文件结果未确认：{rename.replacement}")
                outputs.append({"file_name": rename.replacement, "path": str(target)})
        except (OSError, P115Error) as exc:
            return ProviderExecutionResult(False, "provider_failed", str(exc))
        return ProviderExecutionResult(
            True,
            "provider_completed",
            "115 文件已下载到本地目录并完成命名",
            executed_items=len(outputs),
            confirmed=True,
            outputs=tuple(outputs),
        )

    def reconcile(self, save_path: str, expected_names: list[str]) -> bool:
        root = Path(save_path)
        return bool(expected_names) and all((root / name).is_file() for name in expected_names)


def _verification_temporarily_unavailable(message: str) -> bool:
    return any(
        marker in message
        for marker in (
            "Cookie 无效",
            "Cookie 未配置",
            "Cookie 连接",
            "115 连接失败",
            "请求过于频繁",
            "HTTP 5",
            "115 Open 暂不提供分享链接读取",
        )
    )


def _ensure_directory_with_retry(client: P115Client, path: str, attempts: int = 3) -> str:
    last_error: P115Error | None = None
    for attempt in range(max(1, attempts)):
        try:
            return client.ensure_directory(path)
        except P115Error as exc:
            last_error = exc
            if attempt + 1 < max(1, attempts):
                time.sleep(1)
    assert last_error is not None
    raise last_error


def _match_received_staging_files(selections, staging_items) -> dict[str, P115File]:
    """Recover files accepted by 115 before a previous request was interrupted."""
    matched: dict[str, P115File] = {}
    used: set[str] = set()
    for source, _rename in selections:
        candidates = [
            item
            for item in staging_items
            if item.file_id not in used
            and item.name == source.name
            and (not source.size or item.size == source.size)
        ]
        if len(candidates) == 1:
            matched[source.file_id] = candidates[0]
            used.add(candidates[0].file_id)
    return matched


def _select_snapshot_files(files, rename_pairs):
    selected = []
    used: set[str] = set()
    for pair in rename_pairs:
        matches = [
            item
            for item in files
            if item.file_id not in used
            and (
                (pair.source_id and item.file_id == pair.source_id)
                or (pair.source_path and item.path == pair.source_path)
                or (item.name == pair.source_name and (not pair.source_size or item.size == pair.source_size))
            )
        ]
        if len(matches) != 1:
            raise P115Error(f"115 分享内容已变化，无法唯一定位待转存文件：{pair.source_name}")
        used.add(matches[0].file_id)
        selected.append((matches[0], pair))
    return selected
