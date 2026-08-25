from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.security import require_user
from app.db.database import db
from app.services.notifications import sync_transfer_notifications
from app.services.notification_channels import sync_interaction_shortcuts, test_channel


router = APIRouter(
    prefix="/api/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_user)],
)


class MarkReadRequest(BaseModel):
    id: int | None = None


@router.get("")
def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = False,
):
    sync_transfer_notifications()
    with db() as conn:
        unread_count = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE is_read=0 AND is_cleared=0"
        ).fetchone()[0]
        where = "WHERE is_cleared=0"
        if unread_only:
            where += " AND is_read=0"
        rows = conn.execute(
            f"""
            SELECT id,type,title,message,action_page,poster_key,is_read,created_at
            FROM notifications
            {where}
            ORDER BY created_at DESC,id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        poster_key = str(item.pop("poster_key", "") or "")
        item["poster_url"] = (
            f"/api/notifications/wecom/posters/{poster_key}" if poster_key else ""
        )
        items.append(item)
    return {"items": items, "unread_count": unread_count}


@router.post("/read")
def mark_notifications_read(payload: MarkReadRequest):
    with db() as conn:
        if payload.id is None:
            conn.execute("UPDATE notifications SET is_read=1 WHERE is_cleared=0 AND is_read=0")
        else:
            conn.execute(
                "UPDATE notifications SET is_read=1 WHERE id=? AND is_cleared=0",
                (payload.id,),
            )
    return {"ok": True}


@router.delete("")
def clear_notifications():
    with db() as conn:
        conn.execute("UPDATE notifications SET is_read=1,is_cleared=1 WHERE is_cleared=0")
    return {"ok": True}


@router.post("/test/{provider}")
def test_notification_provider(provider: str):
    if provider not in {"telegram", "wecom", "wecom_app"}:
        raise HTTPException(status_code=404, detail="不支持的通知渠道")
    result = test_channel(provider)
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.message)
    return {"ok": True, "provider": provider, "message": result.message}


@router.post("/interaction-shortcuts/sync")
def sync_shortcut_menus():
    results = sync_interaction_shortcuts()
    if not results:
        raise HTTPException(status_code=422, detail="请先配置 Telegram Bot 或企业微信自建应用")
    return {
        "ok": all(result.ok for result in results),
        "message": "快捷菜单已同步" if all(result.ok for result in results) else "部分渠道同步失败，请查看渠道返回信息",
        "channels": [result.__dict__ for result in results],
    }
