from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.security import require_user
from app.services.diagnostics import export_diagnostic_bundle, record_diagnostic_event


router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


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
