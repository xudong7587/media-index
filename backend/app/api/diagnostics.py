from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi import Response as FastAPIResponse
from fastapi.responses import Response

from app.core.security import require_user
from app.services.diagnostic_support import (
    create_support_token,
    require_support_token,
    revoke_support_tokens,
    support_status,
)
from app.services.diagnostics import (
    diagnostic_task_timeline,
    export_diagnostic_bundle,
    recent_diagnostic_events,
    record_diagnostic_event,
)


router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


class SupportTokenCreate(BaseModel):
    ttl_minutes: int = Field(default=30, ge=5, le=120)


@router.get("/export", dependencies=[Depends(require_user)])
def export_diagnostics():
    record_diagnostic_event("diagnostics", "bundle_exported", message="后台诊断包已导出")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=export_diagnostic_bundle(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="mediaindex-diagnostics-{stamp}.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/support/status", dependencies=[Depends(require_user)])
def get_support_status(response: FastAPIResponse):
    response.headers["Cache-Control"] = "no-store"
    return support_status()


@router.post("/support/tokens", dependencies=[Depends(require_user)])
def issue_support_token(payload: SupportTokenCreate, response: FastAPIResponse):
    response.headers["Cache-Control"] = "no-store"
    return create_support_token(payload.ttl_minutes)


@router.delete("/support/tokens", dependencies=[Depends(require_user)])
def revoke_all_support_tokens(response: FastAPIResponse):
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "revoked": revoke_support_tokens()}


@router.get("/support/events", dependencies=[Depends(require_support_token)])
def read_support_events(
    response: FastAPIResponse,
    after_id: int = Query(default=0, ge=0),
    job_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=200, ge=1, le=500),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return {"events": recent_diagnostic_events(after_id=after_id, job_id=job_id, limit=limit)}


@router.get("/support/tasks/{job_id}/timeline", dependencies=[Depends(require_support_token)])
def read_support_task_timeline(job_id: int, response: FastAPIResponse):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    result = diagnostic_task_timeline(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result
