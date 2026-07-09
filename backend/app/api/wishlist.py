from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import require_user
from app.db.database import db

router = APIRouter(prefix="/api/wishlist", tags=["wishlist"], dependencies=[Depends(require_user)])


class WishlistCreate(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: str = ""
    poster_url: str = ""
    overview: str = ""


@router.get("")
def list_wishlist():
    with db() as conn:
        rows = conn.execute("SELECT * FROM wishlist ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


@router.post("")
def create_wishlist(payload: WishlistCreate):
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO wishlist(tmdb_id, media_type, title, year, poster_url, overview, status)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(tmdb_id, media_type) DO UPDATE SET
              title=excluded.title,
              year=excluded.year,
              poster_url=excluded.poster_url,
              overview=excluded.overview,
              status='pending'
            """,
            (
                payload.tmdb_id,
                payload.media_type,
                payload.title,
                payload.year,
                payload.poster_url,
                payload.overview,
                "pending",
            ),
        )
        return {"ok": True, "id": cur.lastrowid}


@router.delete("/{item_id}")
def delete_wishlist(item_id: int):
    with db() as conn:
        conn.execute("DELETE FROM wishlist WHERE id=?", (item_id,))
    return {"ok": True}
