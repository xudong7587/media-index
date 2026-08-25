from __future__ import annotations

import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Literal

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.clients.pansou import PansouClient
from app.core.config import get_settings
from app.core.security import require_user
from app.services.cross_cloud_transfer import (
    CrossCloudTransferError,
    CrossCloudTransferRequest,
    create_cross_cloud_transfer,
    delete_cross_cloud_transfer,
    get_cross_cloud_transfer,
    list_cross_cloud_transfers,
    request_cancel,
    run_cross_cloud_transfer,
    transfer_events,
)
from app.services.cloud_inventory import CloudInventoryError, scan_p115_inventory, scan_quark_inventory
from app.services.media_assets import list_assets
from app.services.strm_reconciler import StrmReconcileError, list_strm_entries, reconcile_strm
from app.services.strm_jobs import create_strm_job, run_strm_job
from app.services.deletion_workflow import DeletionWorkflowError, confirm_deletion, list_deletion_intents, request_deletion
from app.services.channel_monitor import (
    ChannelMonitorError,
    classify_pansou_channel_sources,
    import_pansou_channels,
    list_channel_messages,
    list_channel_subscriptions,
    upsert_channel_subscription,
)
from app.services.channel_source_poller import sync_public_channels


router = APIRouter(prefix="/api/cloud", tags=["cloud-workspace"], dependencies=[Depends(require_user)])


class CrossCloudTransferCreate(BaseModel):
    source_parent_id: str = Field(min_length=1, max_length=256)
    source_file_id: str = Field(min_length=1, max_length=256)
    target_parent_path: str = Field(min_length=1, max_length=1000)
    target_name: str = Field(default="", max_length=240)


class InventoryScanRequest(BaseModel):
    root_path: str = Field(min_length=1, max_length=1000)
    max_files: int | None = Field(default=None, ge=1, le=50000)


class StrmReconcileRequest(BaseModel):
    output_root: str | None = Field(default=None, max_length=2000)
    playback_base_url: str | None = Field(default=None, max_length=1000)
    provider: Literal["p115", "quark"] | None = None


class StrmJobRequest(BaseModel):
    provider: Literal["p115", "quark"]
    mode: Literal["incremental", "full"]
    root_path: str = Field(min_length=1, max_length=1000)
    output_root: str = Field(min_length=1, max_length=2000)
    include_directories: list[str] = Field(default_factory=list, max_length=500)
    # Omission reuses the saved STRM playback address; an explicit empty value
    # selects the generated Emby-host + 302-port endpoint.
    playback_base_url: str | None = Field(default=None, max_length=1000)


class DeletionIntentCreate(BaseModel):
    asset_id: int = Field(ge=1)


class ChannelSubscriptionUpdate(BaseModel):
    channel_id: str = Field(min_length=1, max_length=100)
    display_name: str = Field(default="", max_length=120)
    enabled: bool = True
    auto_transfer: bool = False
    require_douban_match: bool = False
    douban_titles: list[str] = Field(default_factory=list, max_length=1000)


class PansouChannelImportRequest(BaseModel):
    channel_ids: list[str] = Field(min_length=1, max_length=200)


@router.get("/workspace")
def cloud_workspace_status():
    """Safe defaults used by the dedicated cloud workspace, never credentials."""
    settings = get_settings()
    return {
        "quark_connected": QuarkClient(settings).configured(),
        "p115_connected": P115Client(settings).configured(),
        "default_p115_target_path": settings.p115_root_path,
        "stream_buffer_bytes": 8 * 1024 * 1024,
        "upload_part_bytes": 16 * 1024 * 1024,
    }


@router.get("/quark/directory")
def list_quark_directory(parent_id: str = Query(default="0", min_length=1, max_length=256)):
    client = QuarkClient()
    if not client.configured():
        raise HTTPException(status_code=409, detail="夸克连接未配置")
    try:
        items = client.list_directory(parent_id)
    except QuarkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        {
            "file_id": item.file_id,
            "parent_id": item.parent_id,
            "name": item.name,
            "size": item.size,
            "is_dir": item.is_dir,
            "sha1_available": bool(re.fullmatch(r"[A-Fa-f0-9]{40}", str(item.sha1 or ""))),
        }
        for item in items
    ]


@router.get("/p115/directory")
def list_p115_directory(parent_id: str = Query(default="0", min_length=1, max_length=256)):
    """Read one live native 115 directory; never fall back to inventory/cache."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", str(parent_id or "")):
        raise HTTPException(status_code=400, detail="115 目录 ID 无效")
    client = P115Client()
    if not client.configured():
        raise HTTPException(status_code=409, detail="115 未连接，请先到“账号连接”保存有效 Cookie")
    try:
        items = client.list_directory(parent_id)
    except P115Error as exc:
        message = str(exc)
        status = 409 if any(marker in message for marker in ("重新扫码", "授权已失效", "未配置")) else 502
        raise HTTPException(status_code=status, detail=message) from exc
    return {
        "parent_id": str(parent_id),
        "entries": [
            {
                "file_id": item.file_id,
                "parent_id": item.parent_id,
                "name": item.name,
                "size": item.size,
                "is_dir": item.is_dir,
            }
            for item in items
        ],
    }


@router.get("/cross-transfers")
def list_cross_transfers(limit: int = Query(default=100, ge=1, le=200)):
    return list_cross_cloud_transfers(limit)


@router.get("/cross-transfers/{transfer_id}")
def get_cross_transfer(transfer_id: int):
    record = get_cross_cloud_transfer(transfer_id)
    if not record:
        raise HTTPException(status_code=404, detail="跨盘任务不存在")
    return record


@router.get("/cross-transfers/{transfer_id}/events")
def get_cross_transfer_events(transfer_id: int):
    if not get_cross_cloud_transfer(transfer_id):
        raise HTTPException(status_code=404, detail="跨盘任务不存在")
    return transfer_events(transfer_id)


@router.post("/cross-transfers")
def create_cross_transfer(payload: CrossCloudTransferCreate):
    try:
        return create_cross_cloud_transfer(
            CrossCloudTransferRequest(
                source_parent_id=payload.source_parent_id,
                source_file_id=payload.source_file_id,
                target_parent_path=payload.target_parent_path,
                target_name=payload.target_name,
            )
        )
    except CrossCloudTransferError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cross-transfers/{transfer_id}/run")
def run_cross_transfer(transfer_id: int, background_tasks: BackgroundTasks):
    if not get_cross_cloud_transfer(transfer_id):
        raise HTTPException(status_code=404, detail="跨盘任务不存在")
    # Starting this endpoint is the deliberate confirmation point for the
    # first cloud-side write (115 target directory / upload session).
    background_tasks.add_task(run_cross_cloud_transfer, transfer_id)
    return {"ok": True, "transfer_id": transfer_id, "state": "queued_for_explicit_run"}


@router.post("/cross-transfers/{transfer_id}/cancel")
def cancel_cross_transfer(transfer_id: int):
    try:
        return request_cancel(transfer_id)
    except CrossCloudTransferError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/cross-transfers/{transfer_id}", status_code=204)
def delete_cross_transfer(transfer_id: int):
    try:
        delete_cross_cloud_transfer(transfer_id)
    except CrossCloudTransferError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/assets")
def list_media_assets(limit: int = Query(default=100, ge=1, le=500), status: str = Query(default="")):
    return list_assets(limit, status=status)


@router.post("/inventory/p115")
def scan_p115_assets(payload: InventoryScanRequest):
    try:
        result = scan_p115_inventory(payload.root_path, max_files=payload.max_files)
    except CloudInventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = {
        "provider": result.provider,
        "root_path": result.root_path,
        "directories_scanned": result.directories_scanned,
        "files_indexed": result.files_indexed,
        "truncated": result.truncated,
    }
    response["auto_strm"] = _auto_reconcile("p115", result.root_path)
    return response


@router.post("/inventory/quark")
def scan_quark_assets(payload: InventoryScanRequest):
    try:
        result = scan_quark_inventory(payload.root_path, max_files=payload.max_files)
    except CloudInventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = {
        "provider": result.provider,
        "root_path": result.root_path,
        "directories_scanned": result.directories_scanned,
        "files_indexed": result.files_indexed,
        "truncated": result.truncated,
    }
    response["auto_strm"] = _auto_reconcile("quark", result.root_path)
    return response


def _auto_reconcile(provider: Literal["p115", "quark"], source_root_path: str | None = None):
    settings = get_settings()
    if not bool(getattr(settings, f"{provider}_strm_enabled", False)):
        return None
    try:
        result = reconcile_strm(provider=provider, source_root_path=source_root_path)
        return {
            "ok": True,
            "created": result.created,
            "replaced": result.replaced,
            "unchanged": result.unchanged,
            "scraped": result.scraped,
        }
    except Exception as exc:
        # Inventory indexing has completed successfully. Keep automatic STRM
        # failures visible without turning the successful scan into an error.
        return {
            "ok": False,
            "message": f"STRM 自动校正失败（{exc.__class__.__name__}），请到 STRM 页面重试",
        }


@router.get("/strm")
def list_strm(limit: int = Query(default=200, ge=1, le=500)):
    return list_strm_entries(limit)


@router.post("/strm/reconcile")
def reconcile_strm_entries(payload: StrmReconcileRequest):
    try:
        result = reconcile_strm(output_root=payload.output_root, playback_base_url=payload.playback_base_url, provider=payload.provider)
    except StrmReconcileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "created": result.created,
        "replaced": result.replaced,
        "unchanged": result.unchanged,
        "filtered": result.filtered,
        "conflicts": result.conflicts,
        "removed": result.removed,
        "scraped": result.scraped,
    }


@router.post("/strm/jobs")
def start_strm_job(payload: StrmJobRequest, background_tasks: BackgroundTasks):
    if not payload.include_directories:
        raise HTTPException(status_code=422, detail="请先勾选至少一个 STRM 扫描子目录；不会默认扫描整个网盘")
    playback_base_url = payload.playback_base_url.strip() if payload.playback_base_url is not None else None
    job_id = create_strm_job(
        provider=payload.provider, mode=payload.mode, root_path=payload.root_path.strip(),
        output_root=payload.output_root.strip(), playback_base_url=playback_base_url,
        include_directories=payload.include_directories,
    )
    background_tasks.add_task(
        run_strm_job, job_id, provider=payload.provider, mode=payload.mode, root_path=payload.root_path.strip(),
        output_root=payload.output_root.strip(), playback_base_url=playback_base_url, include_directories=payload.include_directories,
    )
    return {"ok": True, "job_id": job_id, "message": "STRM 任务已创建，可在任务中心和运行日志查看"}


@router.get("/deletion-intents")
def list_deletions(limit: int = Query(default=100, ge=1, le=300)):
    return list_deletion_intents(limit)


@router.post("/deletion-intents")
def create_deletion_intent(payload: DeletionIntentCreate):
    try:
        return request_deletion(payload.asset_id, trigger_source="manual")
    except DeletionWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/deletion-intents/{intent_id}/confirm")
def confirm_deletion_intent(intent_id: int):
    try:
        return confirm_deletion(intent_id)
    except DeletionWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/channels")
def list_channels():
    return list_channel_subscriptions()


@router.get("/channels/pansou")
def list_pansou_channels():
    response = PansouClient().list_telegram_channels(timeout=get_settings().pansou_search_timeout_seconds)
    if response.error == "not_configured":
        raise HTTPException(status_code=409, detail="PanSou 尚未配置")
    if response.error == "channels_not_exposed":
        raise HTTPException(status_code=409, detail="当前 PanSou 的健康接口没有返回已配置频道列表，无法自动导入")
    if response.error:
        raise HTTPException(status_code=502, detail=f"PanSou 频道列表读取失败：{response.error}")
    candidates = classify_pansou_channel_sources(response.sources)
    return {
        "candidates": candidates,
        "message": "已读取 PanSou 当前配置的 Telegram 频道。" if candidates else "PanSou 当前没有配置 Telegram 频道。",
    }


@router.post("/channels/import-pansou")
def import_channels_from_pansou(payload: PansouChannelImportRequest):
    return import_pansou_channels(payload.channel_ids)


@router.put("/channels")
def save_channel(payload: ChannelSubscriptionUpdate):
    try:
        return upsert_channel_subscription(
            payload.channel_id,
            display_name=payload.display_name,
            enabled=payload.enabled,
            auto_transfer=payload.auto_transfer,
            require_douban_match=payload.require_douban_match,
            douban_titles=payload.douban_titles,
        )
    except ChannelMonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/channels/messages")
def list_channel_events(limit: int = Query(default=100, ge=1, le=300)):
    return list_channel_messages(limit)


@router.post("/channels/sync")
def sync_channel_sources(channel_id: str = Query(default="", max_length=100)):
    results = sync_public_channels(channel_id, force=True)
    return {
        "ok": all(item.get("ok") for item in results) if results else False,
        "results": results,
        "message": "；".join(str(item.get("message") or "") for item in results) or "没有可拉取的公开频道来源",
    }
