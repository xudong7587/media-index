from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import require_user
from app.db.database import db
from app.services.wishlist_schedule import compute_wishlist_next_check, resolve_wishlist_target
from app.services.wishlist_engine import run_wishlist_item

router = APIRouter(prefix="/api/wishlist", tags=["wishlist"], dependencies=[Depends(require_user)])


class WishlistCreate(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: str = ""
    poster_url: str = ""
    overview: str = ""
    season_number: int | None = None
    save_target: str = "cloud"
    check_hour: int | None = Field(default=None, ge=0, le=23)


class WishlistScheduleUpdate(BaseModel):
    check_hour: int = Field(ge=0, le=23)


@router.get("")
def list_wishlist():
    with db() as conn:
        rows = conn.execute("SELECT * FROM wishlist ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


@router.post("")
def create_wishlist(payload: WishlistCreate):
    try:
        target = resolve_wishlist_target(payload.tmdb_id, payload.media_type, payload.season_number)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB target resolution failed: {exc}") from exc
    check_hour = payload.check_hour if payload.check_hour is not None else get_settings().wishlist_default_check_hour
    next_check_at, tmdb_date = compute_wishlist_next_check(target, check_hour)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO wishlist(
                tmdb_id,media_type,title,year,poster_url,overview,season_number,save_target,
                check_hour,tmdb_date,next_check_at,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending')
            ON CONFLICT(tmdb_id, media_type) DO UPDATE SET
              title=excluded.title,
              year=excluded.year,
              poster_url=excluded.poster_url,
              overview=excluded.overview,
              season_number=excluded.season_number,
              save_target=excluded.save_target,
              check_hour=excluded.check_hour,
              tmdb_date=excluded.tmdb_date,
              next_check_at=excluded.next_check_at,
              last_error='',
              retry_count=0,
              notification_sent_at=NULL,
              status='pending'
            """,
            (
                payload.tmdb_id,
                payload.media_type,
                target.title,
                target.series_year,
                target.poster_url or payload.poster_url,
                target.overview or payload.overview,
                target.season_number,
                payload.save_target,
                check_hour,
                tmdb_date,
                next_check_at,
            ),
        )
        row = conn.execute(
            "SELECT id FROM wishlist WHERE tmdb_id=? AND media_type=?",
            (payload.tmdb_id, payload.media_type),
        ).fetchone()
        return {"ok": True, "id": int(row["id"]), "next_check_at": next_check_at}


@router.patch("/{item_id}/schedule")
def update_wishlist_schedule(item_id: int, payload: WishlistScheduleUpdate):
    with db() as conn:
        row = conn.execute("SELECT * FROM wishlist WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="wishlist item not found")
    item = dict(row)
    try:
        target = resolve_wishlist_target(item["tmdb_id"], item["media_type"], item.get("season_number"))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB target resolution failed: {exc}") from exc
    next_check_at, tmdb_date = compute_wishlist_next_check(target, payload.check_hour)
    with db() as conn:
        conn.execute(
            """
            UPDATE wishlist SET check_hour=?,tmdb_date=?,next_check_at=?,status='pending',
                                last_error='',notification_sent_at=NULL
            WHERE id=?
            """,
            (payload.check_hour, tmdb_date, next_check_at, item_id),
        )
    return {"ok": True, "next_check_at": next_check_at, "tmdb_date": tmdb_date}


@router.post("/{item_id}/run")
def run_wishlist_now(item_id: int):
    return run_wishlist_item(item_id, refresh=True)


@router.delete("/{item_id}")
def delete_wishlist(item_id: int):
    with db() as conn:
        conn.execute("DELETE FROM wishlist WHERE id=?", (item_id,))
    return {"ok": True}
