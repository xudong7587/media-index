import os
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings, normalize_category_path
from app.core.security import require_user
from app.services.paths import normalize_save_root

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(require_user)])


def current_version() -> str:
    candidates = [Path("/app/VERSION"), Path(__file__).resolve().parents[3] / "VERSION"]
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return "0.2.0-dev"


class ConfigUpdate(BaseModel):
    tmdb_api_key: str = ""
    qas_base_url: str = ""
    qas_token: str = ""
    pansou_url: str = ""
    cloud_save_path: str = ""
    local_save_path: str = ""
    category_paths: dict[str, str] = {}


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
        "wishlist_default_check_hour": settings.wishlist_default_check_hour,
        "version": current_version(),
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

    try:
        cloud_root = normalize_save_root(payload.cloud_save_path) if payload.cloud_save_path.strip() else ""
        local_root = normalize_save_root(payload.local_save_path) if payload.local_save_path.strip() else ""
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"保存根路径无效：{exc}") from exc

    mapping = {
        "TMDB_API_KEY": payload.tmdb_api_key,
        "QAS_BASE_URL": payload.qas_base_url,
        "QAS_TOKEN": payload.qas_token,
        "PANSOU_URL": payload.pansou_url,
        "CLOUD_SAVE_PATH": cloud_root,
        "LOCAL_SAVE_PATH": local_root,
    }
    for key, value in mapping.items():
        if value.strip():
            existing[key] = value.strip()
            os.environ[key] = value.strip()
    if payload.category_paths:
        category_paths = {}
        for key, value in payload.category_paths.items():
            clean_key = key.strip()
            clean_value = value.strip()
            if clean_key and clean_value:
                normalized = normalize_category_path(clean_value)
                if any(part in {".", ".."} for part in normalized.split("/")):
                    raise HTTPException(status_code=422, detail=f"分类路径 {clean_key} 不能包含 . 或 ..")
                category_paths[clean_key] = normalized
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
        "WISHLIST_SCHEDULER_ENABLED",
        "WISHLIST_POLL_MINUTES",
        "WISHLIST_DEFAULT_CHECK_HOUR",
        "PUBLIC_BASE_URL",
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
