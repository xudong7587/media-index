import os
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import require_user

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(require_user)])


class ConfigUpdate(BaseModel):
    tmdb_api_key: str = ""
    qas_base_url: str = ""
    qas_token: str = ""
    pansou_url: str = ""
    cloud_save_path: str = ""
    local_save_path: str = ""
    category_paths: dict[str, str] = {}
    wishlist_cron_enabled: bool | None = None
    wishlist_cron_schedule: str = ""


@router.get("/status")
def status():
    settings = get_settings()
    return {
        "has_tmdb_key": bool(settings.tmdb_api_key),
        "has_qas": bool(settings.qas_base_url and settings.qas_token),
        "has_pansou": bool(settings.pansou_url),
        "qas_base_url": settings.qas_base_url,
        "pansou_url": settings.pansou_url,
        "cloud_root": settings.cloud_save_path,
        "local_root": settings.local_save_path,
        "category_paths": settings.category_paths(),
        "wishlist_cron_enabled": settings.wishlist_cron_enabled,
        "wishlist_cron_schedule": settings.wishlist_cron_schedule,
        "version": "0.1.1",
    }


@router.put("")
def update_config(payload: ConfigUpdate):
    env_path = Path("/app/.env")
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value.strip()

    mapping = {
        "TMDB_API_KEY": payload.tmdb_api_key,
        "QAS_BASE_URL": payload.qas_base_url,
        "QAS_TOKEN": payload.qas_token,
        "PANSOU_URL": payload.pansou_url,
        "CLOUD_SAVE_PATH": payload.cloud_save_path,
        "LOCAL_SAVE_PATH": payload.local_save_path,
        "WISHLIST_CRON_SCHEDULE": payload.wishlist_cron_schedule,
    }
    for key, value in mapping.items():
        if value.strip():
            existing[key] = value.strip()
            os.environ[key] = value.strip()
    if payload.wishlist_cron_enabled is not None:
        existing["WISHLIST_CRON_ENABLED"] = "true" if payload.wishlist_cron_enabled else "false"
        os.environ["WISHLIST_CRON_ENABLED"] = existing["WISHLIST_CRON_ENABLED"]
    if payload.category_paths:
        category_paths = {}
        for key, value in payload.category_paths.items():
            clean_key = key.strip()
            clean_value = value.strip()
            if clean_key and clean_value:
                category_paths[clean_key] = "/" + clean_value.strip("/")
        if category_paths:
            encoded = json.dumps(category_paths, ensure_ascii=False, separators=(",", ":"))
            existing["CATEGORY_PATHS_JSON"] = encoded
            os.environ["CATEGORY_PATHS_JSON"] = encoded

    ordered = [
        "MEDIA_USER",
        "MEDIA_PASS",
        "AUTH_SECRET",
        "TMDB_API_KEY",
        "QAS_BASE_URL",
        "QAS_TOKEN",
        "PANSOU_URL",
        "CLOUD_SAVE_PATH",
        "LOCAL_SAVE_PATH",
        "CATEGORY_PATHS_JSON",
        "WISHLIST_CRON_ENABLED",
        "WISHLIST_CRON_SCHEDULE",
        "DB_PATH",
        "STATIC_DIR",
    ]
    lines = []
    for key in ordered:
        if key in existing:
            lines.append(f"{key}={existing[key]}")
    for key in sorted(k for k in existing if k not in ordered):
        lines.append(f"{key}={existing[key]}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    get_settings.cache_clear()
    return {"ok": True, "message": "saved"}
