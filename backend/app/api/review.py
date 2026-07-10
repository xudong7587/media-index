import json

from fastapi import APIRouter, Depends

from app.core.security import require_user
from app.db.database import db

router = APIRouter(prefix="/api/review", tags=["review"], dependencies=[Depends(require_user)])


@router.get("")
def list_review_candidates():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.*,j.tmdb_id,j.media_type,j.season_number,j.message AS job_message,
                   j.created_at AS job_created_at
            FROM candidates c
            JOIN transfer_jobs j ON j.id=c.job_id
            WHERE j.status='needs_review' OR c.rejected=0
            ORDER BY c.score DESC,c.created_at DESC
            LIMIT 200
            """
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["reasons"] = json.loads(item.pop("reasons_json") or "[]")
        except json.JSONDecodeError:
            item["reasons"] = []
        result.append(item)
    return result
