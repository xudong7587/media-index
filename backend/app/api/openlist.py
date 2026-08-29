from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.clients.openlist import OpenListClient, OpenListError
from app.core.config import get_settings
from app.core.security import require_user
from app.services.openlist_sync import (
    run_openlist_library_sync,
    run_selected_openlist_sync,
    start_openlist_library_sync,
    start_selected_openlist_sync,
)

router = APIRouter(prefix="/api/openlist", tags=["openlist"], dependencies=[Depends(require_user)])


class OpenListSyncRequest(BaseModel):
    source_dir: str = ""
    target_dir: str = ""
    names: list[str] = Field(min_length=1, max_length=100)


class OpenListBrowseRequest(BaseModel):
    path: str = "/"


class OpenListSelectedSyncRequest(BaseModel):
    source_dir: str
    target_dir: str
    names: list[str] = Field(min_length=1, max_length=100)
    overwrite: bool = False


@router.post("/browse")
def browse_openlist(payload: OpenListBrowseRequest):
    path = payload.path.strip() or "/"
    if not path.startswith("/") or ".." in path.split("/"):
        raise HTTPException(status_code=422, detail="OpenList 目录路径无效")
    try:
        directories = OpenListClient().list_directories(path)
    except OpenListError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "path": path, "directories": directories}


@router.post("/entries")
def list_openlist_entries(payload: OpenListBrowseRequest):
    path = payload.path.strip() or "/"
    try:
        entries = OpenListClient().list_entries(path)
    except OpenListError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "path": path, "entries": entries}


@router.post("/test")
def test_openlist():
    settings = get_settings()
    try:
        return OpenListClient().test(settings.openlist_qas_library_path, settings.openlist_p115_library_path)
    except OpenListError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/tasks")
def openlist_copy_tasks():
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_token.strip():
        return {"available": False, "message": "OpenList 未启用或 Token 未配置", "tasks": []}
    try:
        tasks = OpenListClient().copy_tasks(done_limit=50)
    except OpenListError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    active = sum(1 for task in tasks if task["state"] == "running")
    return {
        "available": True,
        "message": f"已从 OpenList 读取 {active} 个进行中复制任务" if active else "OpenList 当前没有进行中的复制任务",
        "tasks": tasks,
    }


@router.post("/tasks/clear-finished")
def clear_finished_openlist_copy_tasks():
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_token.strip():
        raise HTTPException(status_code=409, detail="OpenList 未启用或 Token 未配置")
    try:
        OpenListClient().clear_finished_copy_tasks()
    except OpenListError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "message": "已从 OpenList 清除完成、失败和已取消的复制任务"}


@router.post("/sync")
def sync_openlist(payload: OpenListSyncRequest):
    settings = get_settings()
    source_dir = payload.source_dir.strip() or settings.openlist_qas_library_path
    target_dir = payload.target_dir.strip() or settings.openlist_p115_library_path
    _validate_manual_copy_paths(source_dir, target_dir, settings)
    try:
        OpenListClient().copy(source_dir, target_dir, [name.strip() for name in payload.names if name.strip()])
    except OpenListError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "message": f"已提交 {len([name for name in payload.names if name.strip()])} 个文件到 OpenList 同步队列"}


@router.post("/sync-selected")
def sync_selected_openlist(payload: OpenListSelectedSyncRequest, background_tasks: BackgroundTasks):
    settings = get_settings()
    _validate_manual_copy_paths(payload.source_dir, payload.target_dir, settings)
    result = start_selected_openlist_sync(
        payload.source_dir,
        payload.target_dir,
        payload.names,
        overwrite=payload.overwrite,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("message", "OpenList 同步失败"))
    if not result.get("duplicate"):
        background_tasks.add_task(
            run_selected_openlist_sync,
            int(result["job_id"]),
            str(result["source_dir"]),
            str(result["target_dir"]),
            list(result["names"]),
            overwrite=bool(result["overwrite"]),
        )
    return result


def _within_openlist_mount(path: str, mount: str) -> bool:
    normalized_path = "/" + "/".join(part for part in str(path or "").replace("\\", "/").split("/") if part)
    normalized_mount = "/" + "/".join(part for part in str(mount or "").replace("\\", "/").split("/") if part)
    return normalized_mount != "/" and (
        normalized_path == normalized_mount or normalized_path.startswith(f"{normalized_mount}/")
    )


def _reject_unsupported_reverse(source_dir: str, target_dir: str, settings) -> None:
    if _within_openlist_mount(source_dir, settings.openlist_p115_library_path) and _within_openlist_mount(
        target_dir,
        settings.openlist_qas_library_path,
    ):
        raise HTTPException(status_code=422, detail="暂不支持从 115 复制到夸克")


def _validate_manual_copy_paths(source_dir: str, target_dir: str, settings) -> None:
    _reject_unsupported_reverse(source_dir, target_dir, settings)
    if not str(settings.openlist_qas_library_path or "").strip() or not str(
        settings.openlist_p115_library_path or ""
    ).strip():
        raise HTTPException(status_code=409, detail="请先配置夸克与 115 的 OpenList 挂载目录")
    if not _within_openlist_mount(source_dir, settings.openlist_qas_library_path) or not _within_openlist_mount(
        target_dir,
        settings.openlist_p115_library_path,
    ):
        raise HTTPException(status_code=422, detail="手动同步仅允许从已配置的夸克挂载目录复制到 115 挂载目录")


@router.post("/sync-library")
def sync_openlist_library(background_tasks: BackgroundTasks):
    result = start_openlist_library_sync()
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "OpenList 同步失败"))
    if not result.get("duplicate"):
        background_tasks.add_task(
            run_openlist_library_sync,
            int(result["job_id"]),
            str(result["source_dir"]),
            str(result["target_dir"]),
        )
    return result
