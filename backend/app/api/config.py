import os
import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings, normalize_category_path
from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.core.security import require_user
from app.services.paths import normalize_save_root
from app.services.scheduler import start_scheduler, stop_scheduler

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
    proxy_url: str | None = None
    cloud_save_path: str = ""
    local_save_path: str = ""
    category_paths: dict[str, str] = {}
    wishlist_scheduler_enabled: bool | None = None
    wishlist_poll_minutes: int | None = None
    wishlist_default_check_hour: int | None = None


@router.get("/status")
def status():
    settings = get_settings()
    return {
        "has_tmdb_key": bool(settings.tmdb_api_key),
        "has_qas": bool(settings.qas_base_url and settings.qas_token),
        "has_pansou": bool(settings.pansou_url),
        "qas_base_url": settings.qas_base_url,
        "pansou_url": settings.pansou_url,
        "proxy_url": settings.proxy_url,
        "cloud_root": settings.cloud_save_path,
        "local_root": settings.local_save_path,
        "category_paths": settings.category_paths(),
        "wishlist_default_check_hour": settings.wishlist_default_check_hour,
        "wishlist_scheduler_enabled": settings.wishlist_scheduler_enabled,
        "wishlist_poll_minutes": settings.wishlist_poll_minutes,
        "version": current_version(),
    }


@router.put("")
def update_config(payload: ConfigUpdate):
    env_path = Path(os.getenv("MEDIA_CONFIG_PATH", "/app/.env"))
    env_path.parent.mkdir(parents=True, exist_ok=True)
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
    if payload.proxy_url is not None:
        proxy_url = payload.proxy_url.strip()
        if proxy_url:
            parsed = urlparse(proxy_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise HTTPException(status_code=422, detail="代理地址必须是完整的 HTTP 或 HTTPS URL")
            existing["PROXY_URL"] = proxy_url
            os.environ["PROXY_URL"] = proxy_url
        else:
            existing.pop("PROXY_URL", None)
            os.environ.pop("PROXY_URL", None)
    numeric_mapping = {
        "WISHLIST_POLL_MINUTES": payload.wishlist_poll_minutes,
        "WISHLIST_DEFAULT_CHECK_HOUR": payload.wishlist_default_check_hour,
    }
    for key, value in numeric_mapping.items():
        if value is not None:
            minimum, maximum = (1, 1440) if key == "WISHLIST_POLL_MINUTES" else (0, 23)
            if not minimum <= value <= maximum:
                raise HTTPException(status_code=422, detail=f"{key} 必须在 {minimum}-{maximum} 之间")
            existing[key] = str(value)
            os.environ[key] = str(value)
    if payload.wishlist_scheduler_enabled is not None:
        enabled = "true" if payload.wishlist_scheduler_enabled else "false"
        existing["WISHLIST_SCHEDULER_ENABLED"] = enabled
        os.environ["WISHLIST_SCHEDULER_ENABLED"] = enabled
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
        "PROXY_URL",
        "CLOUD_SAVE_PATH",
        "LOCAL_SAVE_PATH",
        "CATEGORY_PATHS_JSON",
        "WISHLIST_SCHEDULER_ENABLED",
        "WISHLIST_POLL_MINUTES",
        "WISHLIST_DEFAULT_CHECK_HOUR",
        "QAS_CONFIRMATION_TIMEOUT_MINUTES",
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
    stop_scheduler()
    start_scheduler()
    return {"ok": True, "message": "saved"}


@router.post("/test-pansou")
def test_pansou():
    settings = get_settings()
    if not settings.pansou_url.strip():
        raise HTTPException(status_code=422, detail="请先保存 PanSou 地址")
    response = PansouClient().search_detailed("测试", limit=1, timeout=15, result_mode="all")
    if response.error:
        return {
            "ok": False,
            "message": f"PanSou 连接失败：{response.error}",
            "error": response.error,
        }
    return {
        "ok": True,
        "message": "PanSou 接口连接正常" if response.items else "PanSou 接口可用，本次测试未返回夸克资源",
        "result_count": len(response.items),
    }


@router.post("/disable-qas-pansou")
def disable_qas_pansou():
    settings = get_settings()
    if not settings.qas_base_url.strip() or not settings.qas_token.strip():
        raise HTTPException(status_code=422, detail="请先保存 QAS 地址和 Token")
    try:
        response = QasClient().disable_pansou_search()
    except Exception as exc:
        return {"ok": False, "message": f"QAS 内置 PanSou 禁用失败：{type(exc).__name__}"}
    if not isinstance(response, dict) or response.get("success") is not True:
        return {"ok": False, "message": "QAS 未确认配置更新成功"}
    return {"ok": True, "message": "已禁用 QAS 内置 PanSou；MediaIndex 的独立 PanSou 不受影响"}
