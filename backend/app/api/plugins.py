from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from app.core.security import require_user
from app.services import plugins

router = APIRouter(prefix="/api/plugins", tags=["plugins"], dependencies=[Depends(require_user)])


class PluginState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.get("")
def catalog():
    return {"plugins": plugins.catalog(), "externalInstallationSupported": False}


@router.put("/{plugin_id}/state")
def set_state(plugin_id: str, payload: PluginState):
    if plugin_id != plugins.PLUGIN_ID:
        raise HTTPException(404, "插件不存在")
    try:
        plugins.set_enabled(payload.enabled)
    except (OSError, ValueError):
        raise HTTPException(503, "插件状态无法保存，请检查持久化目录") from None
    return {"plugins": plugins.catalog(), "externalInstallationSupported": False}
