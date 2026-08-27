from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from app.core.config import Settings, get_settings
from app.providers.cloud_download_organizer import organizer_provider
from app.services.media_assets import AssetInput, register_asset
from app.services.paths import normalize_save_root
from app.services.strm_reconciler import StrmReconcileResult, reconcile_strm


class TargetedStrmError(RuntimeError):
    pass


@dataclass(frozen=True)
class TargetedStrmResult:
    indexed: int
    asset_ids: tuple[int, ...]
    reconcile: StrmReconcileResult


def index_and_reconcile_targeted_strm(
    *,
    provider: str,
    target_path: str,
    target_files: Iterable[Mapping[str, Any]],
    source_transfer_id: int | None = None,
    settings: Settings | None = None,
) -> TargetedStrmResult:
    """Index and reconcile only provider objects proven by the preceding action.

    A caller may provide provider file IDs directly.  When an external webhook
    has only an exact file path, this service lists that one parent directory
    and requires one exact name match; it never traverses a library or sibling
    directory.
    """
    current = settings or get_settings()
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider not in {"p115", "quark"}:
        raise TargetedStrmError("定点 STRM 只支持 115 或夸克")
    if not bool(getattr(current, f"{normalized_provider}_strm_enabled", False)):
        raise TargetedStrmError("对应网盘尚未启用 STRM 生成")

    source_root = normalize_save_root(current.provider_strm_source_root(normalized_provider))
    selected = tuple(current.provider_strm_included_directories(normalized_provider))
    output_root = str(current.strm_output_root or "").strip()
    if not output_root or not selected:
        raise TargetedStrmError("STRM 输出目录或已勾选的媒体子目录未配置")

    default_path = normalize_save_root(target_path)
    candidates = [_candidate_file(default_path, item) for item in target_files]
    if not candidates:
        raise TargetedStrmError("前序动作没有提供可核验的目标文件")
    for candidate in candidates:
        _relative_file_path(source_root, selected, candidate["file_path"])

    unresolved = [item for item in candidates if not item["file_id"]]
    if unresolved:
        adapter = organizer_provider(current, normalized_provider)
        if not adapter.configured():
            raise TargetedStrmError("网盘连接未配置，无法核验 Webhook 目标文件")
        by_parent: dict[str, list[dict[str, Any]]] = {}
        for item in unresolved:
            by_parent.setdefault(item["parent_path"], []).append(item)
        for parent_path, pending in by_parent.items():
            parent_id = adapter.directory_id(parent_path)
            if not parent_id:
                raise TargetedStrmError(f"目标文件目录不存在：{parent_path}")
            entries = tuple(adapter.list_directory(parent_id))
            for item in pending:
                matches = [entry for entry in entries if not entry.is_dir and entry.name == item["name"]]
                if len(matches) != 1:
                    raise TargetedStrmError(f"目标文件未唯一确认：{item['name']}")
                match = matches[0]
                item.update(
                    file_id=str(match.file_id),
                    parent_id=str(match.parent_id or parent_id),
                    size=int(match.size or 0),
                )

    asset_ids: list[int] = []
    for item in candidates:
        relative_path = _relative_file_path(source_root, selected, item["file_path"])
        asset = register_asset(
            AssetInput(
                provider=normalized_provider,
                file_id=item["file_id"],
                parent_id=item["parent_id"],
                name=item["name"],
                relative_path=relative_path,
                inventory_root_path=source_root,
                size=item["size"],
                source_transfer_id=source_transfer_id,
                status="ready",
            )
        )
        asset_ids.append(int(asset["id"]))

    reconciled = reconcile_strm(
        output_root=output_root,
        provider=normalized_provider,
        source_root_path=source_root,
        include_directories=selected,
        asset_ids=asset_ids,
    )
    return TargetedStrmResult(len(asset_ids), tuple(asset_ids), reconciled)


def map_external_media_path(
    value: str,
    *,
    provider: str,
    settings: Settings | None = None,
) -> str:
    """Map an MDC-NG/container path into the saved provider media root."""
    current = settings or get_settings()
    remote_root = normalize_save_root(current.provider_strm_source_root(provider))
    external_root_raw = str(getattr(current, "mdc_webhook_root_path", "") or "").strip()
    supplied = normalize_save_root(value)
    if external_root_raw:
        external_root = normalize_save_root(external_root_raw)
        if supplied == external_root:
            mapped = remote_root
        elif supplied.startswith(f"{external_root.rstrip('/')}/"):
            mapped = f"{remote_root.rstrip('/')}/{supplied[len(external_root.rstrip('/')) + 1:]}"
        elif supplied == remote_root or supplied.startswith(f"{remote_root.rstrip('/')}/"):
            mapped = supplied
        else:
            raise TargetedStrmError("Webhook 文件路径不属于已保存的 MDC-NG 媒体根目录")
    else:
        mapped = supplied
    # Reuse the same direct-child authorization as STRM generation.
    _relative_file_path(
        remote_root,
        current.provider_strm_included_directories(provider),
        mapped,
    )
    return mapped


def _candidate_file(default_path: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    name = str(raw.get("file_name") or raw.get("name") or "").strip()
    supplied_path = str(raw.get("path") or "").strip()
    if not name and supplied_path:
        name = PurePosixPath(supplied_path.replace("\\", "/")).name
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise TargetedStrmError("目标文件名无效")
    base = normalize_save_root(supplied_path) if supplied_path else default_path
    file_path = base if PurePosixPath(base).name == name else normalize_save_root(f"{base.rstrip('/')}/{name}")
    return {
        "file_id": str(raw.get("file_id") or "").strip(),
        "parent_id": str(raw.get("parent_id") or "").strip(),
        "name": name,
        "file_path": file_path,
        "parent_path": normalize_save_root(str(PurePosixPath(file_path).parent)),
        "size": max(0, int(raw.get("size") or 0)),
    }


def _relative_file_path(source_root: str, selected: Iterable[str], file_path: str) -> str:
    candidate = normalize_save_root(file_path)
    prefix = "/" if source_root == "/" else f"{source_root.rstrip('/')}/"
    if candidate == source_root or not candidate.startswith(prefix):
        raise TargetedStrmError("目标文件不属于已保存的媒体根目录")
    relative = candidate[len(prefix):]
    if "/" not in relative:
        raise TargetedStrmError("目标文件必须位于已勾选的媒体一级子目录内")
    allowed = {
        normalize_save_root(path)[len(prefix):]
        for path in selected
        if normalize_save_root(path).startswith(prefix)
        and "/" not in normalize_save_root(path)[len(prefix):]
    }
    if relative.split("/", 1)[0] not in allowed:
        raise TargetedStrmError("目标文件不属于已勾选的媒体一级子目录")
    return relative
