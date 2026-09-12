from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.clients.openlist import OpenListError
from app.core.security import require_user
from app.services.cross_copy import config_status, save_config

router = APIRouter(prefix="/api/cross-copy", tags=["cloud"], dependencies=[Depends(require_user)])


class CrossCopyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cross_copy_transport: Literal["openlist", "cd2"] | None = None
    openlist_enabled: bool | None = None
    openlist_auto_sync: bool | None = None
    openlist_url: str | None = None
    openlist_token: str | None = None
    openlist_qas_library_path: str | None = None
    openlist_p115_library_path: str | None = None
    cd2_url: str | None = None
    cd2_token: str | None = None
    cd2_qas_library_path: str | None = None
    cd2_p115_library_path: str | None = None


@router.get("/config")
def get_cross_copy_config():
    return config_status()


@router.post("/config")
def update_cross_copy_config(payload: CrossCopyConfig):
    try:
        result = save_config(payload.model_dump(exclude_unset=True))
        from app.services.scheduler import start_scheduler, stop_scheduler
        stop_scheduler()
        start_scheduler()
        return result
    except OpenListError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
