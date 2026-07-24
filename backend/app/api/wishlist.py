from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import require_user
from app.db.database import db
from app.services.wishlist_schedule import compute_wishlist_next_check, resolve_wishlist_target
from app.services.wishlist_engine import run_wishlist_item
from app.providers.registry import resolve_provider_key

router = APIRouter(prefix="/api/wishlist", tags=["wishlist"], dependencies=[Depends(require_user)])


class WishlistCreate(BaseModel):
    tmdb_id: int
    media_type: str
    category: str = ""
    title: str
    year: str = ""
    poster_url: str = ""
    overview: str = ""
    season_number: int | None = None
    save_target: str = "cloud"
    check_hour: int | None = Field(default=None, ge=0, le=23)
    provider: str | None = None


class WishlistScheduleUpdate(BaseModel):
    check_hour: int = Field(ge=0, le=23)


class WishlistProviderUpdate(BaseModel):
    provider: str
    enabled: bool = True


@router.get("")
def list_wishlist():
    with db() as conn:
        rows = conn.execute("SELECT * FROM wishlist ORDER BY created_at DESC").fetchall()
        grouped: dict[tuple[int, str], dict] = {}
        for raw in rows:
            row = dict(raw)
            key = (row["tmdb_id"], row["media_type"])
            state = {
                "id": row["id"],
                "provider": row["provider"],
                "status": row["status"],
                "next_check_at": row["next_check_at"],
                "last_checked_at": row["last_checked_at"],
                "last_error": row["last_error"],
            }
            if key not in grouped:
                row["provider_states"] = [state]
                grouped[key] = row
            else:
                grouped[key]["provider_states"].append(state)
        return list(grouped.values())


@router.post("")
def create_wishlist(payload: WishlistCreate):
    try:
        provider = resolve_provider_key(payload.save_target, payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
                tmdb_id,media_type,category,title,year,poster_url,overview,season_number,save_target,provider,
                check_hour,tmdb_date,next_check_at,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'pending')
            ON CONFLICT(tmdb_id, media_type, provider) DO UPDATE SET
              title=excluded.title,
              year=excluded.year,
              poster_url=excluded.poster_url,
              overview=excluded.overview,
              category=excluded.category,
              season_number=excluded.season_number,
              save_target=excluded.save_target,
              provider=excluded.provider,
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
                payload.category or payload.media_type,
                target.title,
                target.series_year,
                target.poster_url or payload.poster_url,
                target.overview or payload.overview,
                target.season_number,
                payload.save_target,
                provider,
                check_hour,
                tmdb_date,
                next_check_at,
            ),
        )
        row = conn.execute(
            "SELECT id FROM wishlist WHERE tmdb_id=? AND media_type=? AND provider=?",
            (payload.tmdb_id, payload.media_type, provider),
        ).fetchone()
        return {"ok": True, "id": int(row["id"]), "next_check_at": next_check_at, "provider": provider}


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


@router.patch("/{item_id}/provider")
def update_wishlist_provider(item_id: int, payload: WishlistProviderUpdate):
    try:
        provider = resolve_provider_key("cloud", payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with db() as conn:
        item_row = conn.execute("SELECT * FROM wishlist WHERE id=?", (item_id,)).fetchone()
        if not item_row:
            raise HTTPException(status_code=404, detail="wishlist item not found")
        item = dict(item_row)
        sibling = conn.execute(
            "SELECT id FROM wishlist WHERE tmdb_id=? AND media_type=? AND provider=?",
            (item["tmdb_id"], item["media_type"], provider),
        ).fetchone()
        siblings = conn.execute(
            "SELECT COUNT(*) FROM wishlist WHERE tmdb_id=? AND media_type=?",
            (item["tmdb_id"], item["media_type"]),
        ).fetchone()[0]
    if not payload.enabled:
        if not sibling:
            return {"ok": True, "provider": provider, "enabled": False}
        if siblings <= 1:
            raise HTTPException(status_code=422, detail="至少保留一个愿望单网盘")
        with db() as conn:
            conn.execute("DELETE FROM wishlist WHERE id=?", (sibling["id"],))
        return {"ok": True, "provider": provider, "enabled": False}
    if sibling:
        return {"ok": True, "provider": provider, "enabled": True, "id": int(sibling["id"])}
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO wishlist(
                tmdb_id,media_type,category,title,year,poster_url,overview,season_number,save_target,provider,
                check_hour,tmdb_date,next_check_at,status
            ) VALUES(?,?,?,?,?,?,?,?,'cloud',?,?,?,CURRENT_TIMESTAMP,'pending')
            """,
            (
                item["tmdb_id"], item["media_type"], item.get("category") or "", item["title"],
                item.get("year") or "", item.get("poster_url") or "", item.get("overview") or "",
                item.get("season_number"), provider, item.get("check_hour") or 9, item.get("tmdb_date") or "",
            ),
        )
        new_id = int(cur.lastrowid)
    return {"ok": True, "provider": provider, "enabled": True, "id": new_id}


@router.delete("/{item_id}")
def delete_wishlist(item_id: int):
    with db() as conn:
        conn.execute("DELETE FROM wishlist WHERE id=?", (item_id,))
    return {"ok": True}
