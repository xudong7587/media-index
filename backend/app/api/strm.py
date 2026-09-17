from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from app.core.config import get_settings
from app.core.security import require_user
from app.services.strm_jobs import create_strm_job, run_directory_rescan
from app.services.targeted_strm import TargetedStrmError, validate_targeted_strm_path

router = APIRouter(prefix="/api/strm", tags=["strm"], dependencies=[Depends(require_user)])


class DirectoryRescanRequest(BaseModel):
    provider: Literal["p115", "quark"]
    directory_path: str = Field(min_length=1, max_length=1000)


@router.post("/directory-rescan")
def start_directory_rescan(payload: DirectoryRescanRequest, background_tasks: BackgroundTasks):
    settings = get_settings()
    root = settings.provider_strm_source_root(payload.provider)
    selected = settings.provider_strm_included_directories(payload.provider)
    output = settings.strm_output_root.strip()
    if not root or not selected or not output:
        raise HTTPException(status_code=422, detail="请先配置 STRM 来源、扫描子目录和输出目录")
    try:
        path = validate_targeted_strm_path(root, selected, payload.directory_path)
    except (ValueError, TargetedStrmError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job_id = create_strm_job(provider=payload.provider, mode="full", root_path=path, output_root=output)
    background_tasks.add_task(run_directory_rescan, job_id, provider=payload.provider, directory_path=path)
    return {"ok": True, "job_id": job_id, "message": "指定目录重新扫描已排队"}
