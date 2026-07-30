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


@router.post("/sync")
def sync_openlist(payload: OpenListSyncRequest):
    settings = get_settings()
    source_dir = payload.source_dir.strip() or settings.openlist_qas_library_path
    target_dir = payload.target_dir.strip() or settings.openlist_p115_library_path
    try:
        OpenListClient().copy(source_dir, target_dir, [name.strip() for name in payload.names if name.strip()])
    except OpenListError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "message": f"已提交 {len([name for name in payload.names if name.strip()])} 个文件到 OpenList 同步队列"}


@router.post("/sync-selected")
def sync_selected_openlist(payload: OpenListSelectedSyncRequest, background_tasks: BackgroundTasks):
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
