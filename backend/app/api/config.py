import os
import json
from datetime import datetime, timezone
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
    return "0.4.16-dev"


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
    notification_external_enabled: bool | None = None
    public_base_url: str | None = None
    telegram_enabled: bool | None = None
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_host: str | None = None
    wecom_enabled: bool | None = None
    wecom_key: str = ""
    wecom_origin: str | None = None
    wecom_app_enabled: bool | None = None
    wecom_corp_id: str = ""
    wecom_app_secret: str = ""
    wecom_app_agent_id: int | None = None
    wecom_app_to_user: str | None = None
    wecom_app_to_party: str | None = None
    wecom_app_to_tag: str | None = None
    wecom_callback_enabled: bool | None = None
    wecom_callback_token: str = ""
    wecom_callback_aes_key: str = ""
    wecom_callback_allowed_users: str | None = None


class QasPansouUpdate(BaseModel):
    enabled: bool


@router.get("/status")
def status():
    settings = get_settings()
    return {
        "has_tmdb_key": bool(settings.tmdb_api_key),
        "has_qas": bool(settings.qas_base_url and settings.qas_token),
        "has_pansou": bool(settings.pansou_url),
        "qas_base_url": settings.qas_base_url,
        "pansou_url": settings.pansou_url,
        "has_proxy": bool(settings.proxy_url),
        "proxy_url": redact_url_credentials(settings.proxy_url),
        "cloud_root": settings.cloud_save_path,
        "local_root": settings.local_save_path,
        "category_paths": settings.category_paths(),
        "wishlist_default_check_hour": settings.wishlist_default_check_hour,
        "wishlist_scheduler_enabled": settings.wishlist_scheduler_enabled,
        "wishlist_poll_minutes": settings.wishlist_poll_minutes,
        "notification_external_enabled": settings.notification_external_enabled,
        "public_base_url": settings.public_base_url,
        "telegram_enabled": settings.telegram_enabled,
        "has_telegram_token": bool(settings.telegram_bot_token),
        "telegram_chat_id": settings.telegram_chat_id,
        "telegram_api_host": settings.telegram_api_host,
        "wecom_enabled": settings.wecom_enabled,
        "has_wecom_key": bool(settings.wecom_key),
        "wecom_origin": settings.wecom_origin,
        "wecom_app_enabled": settings.wecom_app_enabled,
        "wecom_corp_id": settings.wecom_corp_id,
        "has_wecom_app_secret": bool(settings.wecom_app_secret),
        "wecom_app_agent_id": settings.wecom_app_agent_id,
        "wecom_app_to_user": settings.wecom_app_to_user,
        "wecom_app_to_party": settings.wecom_app_to_party,
        "wecom_app_to_tag": settings.wecom_app_to_tag,
        "wecom_callback_enabled": settings.wecom_callback_enabled,
        "has_wecom_callback_token": bool(settings.wecom_callback_token),
        "has_wecom_callback_aes_key": bool(settings.wecom_callback_aes_key),
        "wecom_callback_allowed_users": settings.wecom_callback_allowed_users,
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
    notifications_were_enabled = existing.get("NOTIFICATION_EXTERNAL_ENABLED", "false").lower() == "true"

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
            try:
                parsed_port = parsed.port
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="代理地址端口无效") from exc
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or (parsed_port is None and parsed.netloc.endswith(":")):
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
    boolean_mapping = {
        "NOTIFICATION_EXTERNAL_ENABLED": payload.notification_external_enabled,
        "TELEGRAM_ENABLED": payload.telegram_enabled,
        "WECOM_ENABLED": payload.wecom_enabled,
        "WECOM_APP_ENABLED": payload.wecom_app_enabled,
        "WECOM_CALLBACK_ENABLED": payload.wecom_callback_enabled,
    }
    for key, value in boolean_mapping.items():
        if value is not None:
            encoded = "true" if value else "false"
            existing[key] = encoded
            os.environ[key] = encoded
    if payload.notification_external_enabled and not notifications_were_enabled:
        enabled_at = datetime.now(timezone.utc).isoformat()
        existing["NOTIFICATION_ENABLED_AT"] = enabled_at
        os.environ["NOTIFICATION_ENABLED_AT"] = enabled_at
    secret_mapping = {
        "TELEGRAM_BOT_TOKEN": payload.telegram_bot_token,
        "WECOM_KEY": payload.wecom_key,
        "WECOM_APP_SECRET": payload.wecom_app_secret,
        "WECOM_CALLBACK_TOKEN": payload.wecom_callback_token,
        "WECOM_CALLBACK_AES_KEY": payload.wecom_callback_aes_key,
    }
    for key, value in secret_mapping.items():
        if value.strip():
            if key == "WECOM_CALLBACK_AES_KEY" and len(value.strip()) != 43:
                raise HTTPException(status_code=422, detail="企业微信 EncodingAESKey 必须是 43 个字符")
            existing[key] = value.strip()
            os.environ[key] = value.strip()
    if payload.telegram_chat_id.strip():
        existing["TELEGRAM_CHAT_ID"] = payload.telegram_chat_id.strip()
        os.environ["TELEGRAM_CHAT_ID"] = payload.telegram_chat_id.strip()
    if payload.wecom_corp_id.strip():
        existing["WECOM_CORP_ID"] = payload.wecom_corp_id.strip()
        os.environ["WECOM_CORP_ID"] = payload.wecom_corp_id.strip()
    if payload.wecom_app_agent_id is not None:
        if payload.wecom_app_agent_id <= 0:
            raise HTTPException(status_code=422, detail="企业微信 AgentId 必须是正整数")
        existing["WECOM_APP_AGENT_ID"] = str(payload.wecom_app_agent_id)
        os.environ["WECOM_APP_AGENT_ID"] = str(payload.wecom_app_agent_id)
    recipient_mapping = {
        "WECOM_APP_TO_USER": payload.wecom_app_to_user,
        "WECOM_APP_TO_PARTY": payload.wecom_app_to_party,
        "WECOM_APP_TO_TAG": payload.wecom_app_to_tag,
        "WECOM_CALLBACK_ALLOWED_USERS": payload.wecom_callback_allowed_users,
    }
    for key, value in recipient_mapping.items():
        if value is not None:
            existing[key] = value.strip()
            os.environ[key] = value.strip()
    endpoint_mapping = {
        "PUBLIC_BASE_URL": payload.public_base_url,
        "TELEGRAM_API_HOST": payload.telegram_api_host,
        "WECOM_ORIGIN": payload.wecom_origin,
    }
    for key, value in endpoint_mapping.items():
        if value is not None:
            normalized = validate_http_origin(value, key)
            existing[key] = normalized
            os.environ[key] = normalized
    if existing.get("WECOM_CALLBACK_ENABLED", "false").lower() == "true":
        required_callback = {
            "企业 ID": existing.get("WECOM_CORP_ID", ""),
            "应用 Secret": existing.get("WECOM_APP_SECRET", ""),
            "AgentId": existing.get("WECOM_APP_AGENT_ID", ""),
            "回调 Token": existing.get("WECOM_CALLBACK_TOKEN", ""),
            "EncodingAESKey": existing.get("WECOM_CALLBACK_AES_KEY", ""),
        }
        missing = [label for label, value in required_callback.items() if not str(value).strip() or str(value).strip() == "0"]
        if missing:
            raise HTTPException(status_code=422, detail=f"启用企业微信交互回调前请填写：{'、'.join(missing)}")
        if len(existing["WECOM_CALLBACK_AES_KEY"]) != 43:
            raise HTTPException(status_code=422, detail="企业微信 EncodingAESKey 必须是 43 个字符")
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
        "NOTIFICATION_EXTERNAL_ENABLED",
        "NOTIFICATION_ENABLED_AT",
        "TELEGRAM_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_API_HOST",
        "WECOM_ENABLED",
        "WECOM_KEY",
        "WECOM_ORIGIN",
        "WECOM_APP_ENABLED",
        "WECOM_CORP_ID",
        "WECOM_APP_SECRET",
        "WECOM_APP_AGENT_ID",
        "WECOM_APP_TO_USER",
        "WECOM_APP_TO_PARTY",
        "WECOM_APP_TO_TAG",
        "WECOM_CALLBACK_ENABLED",
        "WECOM_CALLBACK_TOKEN",
        "WECOM_CALLBACK_AES_KEY",
        "WECOM_CALLBACK_ALLOWED_USERS",
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


def validate_http_origin(value: str, field_name: str) -> str:
    raw = value.strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail=f"{field_name} 必须是完整的 HTTP/HTTPS 地址")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail=f"{field_name} 只能填写 API 根地址")
    return raw


def redact_url_credentials(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.username is None and parsed.password is None:
        return raw
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        parsed_port = parsed.port
    except ValueError:
        return f"{parsed.scheme or 'http'}://***"
    port = f":{parsed_port}" if parsed_port else ""
    username = parsed.username or ""
    credentials = f"{username}:***@" if username else "***@"
    return parsed._replace(netloc=f"{credentials}{hostname}{port}").geturl()


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


@router.get("/qas-pansou")
def qas_pansou_status():
    settings = get_settings()
    if not settings.qas_base_url.strip() or not settings.qas_token.strip():
        raise HTTPException(status_code=422, detail="请先保存 QAS 地址和 Token")
    try:
        enabled = QasClient().pansou_search_enabled()
    except Exception as exc:
        return {"ok": False, "message": f"QAS 自带搜索状态读取失败：{type(exc).__name__}"}
    return {"ok": True, "enabled": enabled}


@router.put("/qas-pansou")
def update_qas_pansou(payload: QasPansouUpdate):
    settings = get_settings()
    if not settings.qas_base_url.strip() or not settings.qas_token.strip():
        raise HTTPException(status_code=422, detail="请先保存 QAS 地址和 Token")
    try:
        response = QasClient().set_pansou_search(payload.enabled)
    except Exception as exc:
        return {"ok": False, "message": f"QAS 自带搜索设置失败：{type(exc).__name__}"}
    if not isinstance(response, dict) or response.get("success") is not True:
        return {"ok": False, "message": "QAS 未确认配置更新成功"}
    state = "启用" if payload.enabled else "禁用"
    return {"ok": True, "enabled": payload.enabled, "message": f"已{state} QAS 自带搜索"}
