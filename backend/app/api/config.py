import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings, normalize_category_path
from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.clients.moviepilot_115 import MoviePilot115Client, MoviePilot115Error
from app.clients.p115 import P115Client, P115Error, valid_p115_cookie
from app.clients.openlist import OpenListClient, OpenListError
from app.core.security import require_user
from app.db.database import db, init_db
from app.services.paths import normalize_save_root, validate_naming_rule
from app.services.scheduler import start_scheduler, stop_scheduler

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(require_user)])


def current_version() -> str:
    candidates = [Path("/app/VERSION"), Path(__file__).resolve().parents[3] / "VERSION"]
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return "0.5.0-dev"


class ConfigUpdate(BaseModel):
    tmdb_api_key: str = ""
    qas_base_url: str = ""
    qas_token: str = ""
    moviepilot_base_url: str | None = None
    moviepilot_api_token: str = ""
    moviepilot_115_plugin_id: str | None = None
    p115_cookie: str = ""
    p115_root_path: str | None = None
    p115_staging_path: str | None = None
    p115_local_path: str | None = None
    enabled_providers: list[str] | None = None
    default_provider: str | None = None
    pansou_url: str = ""
    proxy_url: str | None = None
    cloud_save_path: str = ""
    qas_save_path: str = ""
    local_save_path: str = ""
    category_paths: dict[str, str] = {}
    qas_category_paths: dict[str, str] = {}
    p115_category_paths: dict[str, str] = {}
    media_folder_naming_rule: str | None = None
    season_folder_naming_rule: str | None = None
    movie_naming_rule: str | None = None
    episode_naming_rule: str | None = None
    season_subdirectory_enabled: bool | None = None
    openlist_enabled: bool | None = None
    openlist_auto_sync: bool | None = None
    openlist_url: str | None = None
    openlist_token: str = ""
    openlist_qas_library_path: str | None = None
    openlist_p115_library_path: str | None = None
    wishlist_scheduler_enabled: bool | None = None
    wishlist_poll_minutes: int | None = None
    wishlist_default_check_hour: int | None = None
    tracking_scheduler_enabled: bool | None = None
    tracking_poll_minutes: int | None = None
    tracking_check_time: str | None = None
    tracking_retry_interval_minutes: int | None = None
    tracking_max_retries: int | None = None
    notification_external_enabled: bool | None = None
    public_base_url: str | None = None
    wecom_callback_url: str | None = None
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
    direct_download_enabled: bool | None = None
    direct_download_provider: str | None = None
    direct_download_save_path: str | None = None


class QasPansouUpdate(BaseModel):
    enabled: bool


class ConfigImport(BaseModel):
    format: str
    settings: dict[str, str]
    task_data: "ConfigTaskBackup | None" = None


class ConfigTaskBackup(BaseModel):
    wishlist: list[dict[str, Any]] = []
    tracking: list[dict[str, Any]] = []


CONFIG_EXPORT_FORMAT = "mediaindex.config/v1"
CONFIG_EXPORT_EXCLUDED = {
    "AUTH_SECRET",
    "CACHE_DIR",
    "COOKIE_NAME",
    "COOKIE_SECURE",
    "DB_PATH",
    "LOGIN_MAX_ATTEMPTS",
    "LOGIN_WINDOW_SECONDS",
    "MEDIA_PASS",
    "MEDIA_USER",
    "SESSION_TTL_SECONDS",
    "STATIC_DIR",
}

WISHLIST_BACKUP_COLUMNS = (
    "tmdb_id", "media_type", "category", "title", "year", "poster_url", "overview",
    "season_number", "save_target", "provider", "check_hour", "tmdb_date", "next_check_at",
    "last_checked_at", "last_error", "retry_count", "notification_sent_at", "status",
    "created_at", "updated_at",
)
TRACKING_TASK_BACKUP_COLUMNS = (
    "tmdb_id", "media_type", "category", "title", "year", "poster_url", "overview",
    "season_number", "save_target", "provider", "save_root", "save_path", "status",
    "last_checked_at", "next_check_at", "last_error", "current_share_url", "decision_state",
    "retry_count", "next_retry_at", "last_search_at", "check_time", "last_saved_episode",
    "auto_start_episode", "last_storage_check_at", "storage_check_message", "created_at", "updated_at",
)
TRACKING_EPISODE_BACKUP_COLUMNS = (
    "season_number", "episode_number", "air_date", "title", "status", "provider", "matched_file",
    "share_url", "save_path", "retry_count", "last_error", "match_tokens_json", "desc_hint",
    "source_file", "rename_to", "confidence", "saved_at", "created_at", "updated_at",
)


class ProviderBrowseRequest(BaseModel):
    provider: str = "qas"
    path: str = ""


@router.get("/status")
def status():
    settings = get_settings()
    p115_auth_mode = str(getattr(settings, "p115_auth_mode", "cookie"))
    p115_open_access_token = str(getattr(settings, "p115_open_access_token", ""))
    p115_open_refresh_token = str(getattr(settings, "p115_open_refresh_token", ""))
    return {
        "has_tmdb_key": bool(settings.tmdb_api_key),
        "has_qas": bool(settings.qas_base_url and settings.qas_token),
        "has_moviepilot_115": bool(settings.moviepilot_base_url and settings.moviepilot_api_token),
        "moviepilot_base_url": saved_endpoint_label(settings.moviepilot_base_url),
        "has_moviepilot_token": bool(settings.moviepilot_api_token),
        "moviepilot_115_plugin_id": settings.moviepilot_115_plugin_id,
        "has_p115_cookie": bool(settings.p115_cookie),
        "p115_auth_mode": p115_auth_mode if p115_auth_mode in {"cookie", "open"} else "cookie",
        "has_p115_open": bool(p115_open_access_token and p115_open_refresh_token),
        "p115_root_path": settings.p115_root_path,
        "p115_staging_path": settings.p115_staging_path,
        "p115_local_path": settings.p115_local_path,
        "enabled_providers": list(settings.enabled_provider_keys()),
        "default_provider": settings.default_provider_key(),
        "has_pansou": bool(settings.pansou_url),
        "qas_base_url": saved_endpoint_label(settings.qas_base_url),
        "pansou_url": saved_endpoint_label(settings.pansou_url),
        "has_proxy": bool(settings.proxy_url),
        "proxy_url": saved_endpoint_label(settings.proxy_url),
        "cloud_root": settings.cloud_save_path,
        "qas_root": settings.provider_save_root("qas"),
        "local_root": settings.local_save_path,
        "category_paths": settings.category_paths(),
        "qas_category_paths": settings.provider_category_paths("qas"),
        "p115_category_paths": settings.provider_category_paths("p115"),
        "media_folder_naming_rule": settings.media_folder_naming_rule,
        "season_folder_naming_rule": settings.season_folder_naming_rule,
        "movie_naming_rule": settings.movie_naming_rule,
        "episode_naming_rule": settings.episode_naming_rule,
        "season_subdirectory_enabled": settings.season_subdirectory_enabled,
        "openlist_enabled": settings.openlist_enabled,
        "openlist_auto_sync": settings.openlist_auto_sync,
        "openlist_url": saved_endpoint_label(settings.openlist_url),
        "has_openlist_token": bool(settings.openlist_token),
        "openlist_qas_library_path": settings.openlist_qas_library_path,
        "openlist_p115_library_path": settings.openlist_p115_library_path,
        "wishlist_default_check_hour": settings.wishlist_default_check_hour,
        "wishlist_scheduler_enabled": settings.wishlist_scheduler_enabled,
        "wishlist_poll_minutes": settings.wishlist_poll_minutes,
        "tracking_scheduler_enabled": getattr(settings, "tracking_scheduler_enabled", True),
        "tracking_poll_minutes": getattr(settings, "tracking_poll_minutes", 5),
        "tracking_check_time": getattr(settings, "tracking_check_time", "10:00"),
        "tracking_retry_interval_minutes": getattr(settings, "tracking_retry_interval_minutes", 120),
        "tracking_max_retries": getattr(settings, "tracking_max_retries", 5),
        "notification_external_enabled": settings.notification_external_enabled,
        "public_base_url": settings.public_base_url,
        "wecom_callback_url": settings.wecom_callback_url,
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
        "direct_download_enabled": bool(getattr(settings, "direct_download_enabled", False)),
        "direct_download_provider": getattr(settings, "direct_download_provider", "qas"),
        "direct_download_save_path": getattr(settings, "direct_download_save_path", ""),
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
        qas_root = normalize_save_root(payload.qas_save_path) if payload.qas_save_path.strip() else ""
        local_root = normalize_save_root(payload.local_save_path) if payload.local_save_path.strip() else ""
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"保存根路径无效：{exc}") from exc
    for label, rule, fields in (
        ("媒体文件夹命名规则", payload.media_folder_naming_rule, {"title", "year"}),
        ("季文件夹命名规则", payload.season_folder_naming_rule, {"season"}),
        ("电影命名规则", payload.movie_naming_rule, {"title", "year"}),
        ("剧集命名规则", payload.episode_naming_rule, {"title", "year", "season", "episode"}),
    ):
        if rule is not None and rule.strip():
            try:
                validate_naming_rule(rule.strip(), fields)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"{label}无效：{exc}") from exc

    mapping = {
        "TMDB_API_KEY": payload.tmdb_api_key,
        "QAS_BASE_URL": payload.qas_base_url,
        "QAS_TOKEN": payload.qas_token,
        "PANSOU_URL": payload.pansou_url,
        "CLOUD_SAVE_PATH": cloud_root,
        "QAS_SAVE_PATH": qas_root,
        "LOCAL_SAVE_PATH": local_root,
        "MEDIA_FOLDER_NAMING_RULE": payload.media_folder_naming_rule,
        "SEASON_FOLDER_NAMING_RULE": payload.season_folder_naming_rule,
        "MOVIE_NAMING_RULE": payload.movie_naming_rule,
        "EPISODE_NAMING_RULE": payload.episode_naming_rule,
        "OPENLIST_QAS_LIBRARY_PATH": payload.openlist_qas_library_path,
        "OPENLIST_P115_LIBRARY_PATH": payload.openlist_p115_library_path,
    }
    for key, value in mapping.items():
        if value is not None and value.strip():
            existing[key] = value.strip()
            os.environ[key] = value.strip()
    if payload.moviepilot_base_url is not None:
        moviepilot_base_url = validate_http_origin(payload.moviepilot_base_url, "MoviePilot API 地址")
        existing["MOVIEPILOT_BASE_URL"] = moviepilot_base_url
        os.environ["MOVIEPILOT_BASE_URL"] = moviepilot_base_url
    if payload.moviepilot_api_token.strip():
        moviepilot_token = payload.moviepilot_api_token.strip()
        existing["MOVIEPILOT_API_TOKEN"] = moviepilot_token
        os.environ["MOVIEPILOT_API_TOKEN"] = moviepilot_token
    if payload.moviepilot_115_plugin_id is not None:
        plugin_id = payload.moviepilot_115_plugin_id.strip() or "P115StrmHelper"
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", plugin_id):
            raise HTTPException(status_code=422, detail="MoviePilot 插件 ID 格式无效")
        existing["MOVIEPILOT_115_PLUGIN_ID"] = plugin_id
        os.environ["MOVIEPILOT_115_PLUGIN_ID"] = plugin_id
    if payload.p115_cookie.strip():
        p115_cookie = payload.p115_cookie.strip()
        if not valid_p115_cookie(p115_cookie):
            raise HTTPException(status_code=422, detail="115 Cookie 缺少 UID、CID 或 SEID")
        existing["P115_COOKIE"] = p115_cookie
        os.environ["P115_COOKIE"] = p115_cookie
        existing["P115_AUTH_MODE"] = "cookie"
        os.environ["P115_AUTH_MODE"] = "cookie"
        existing.pop("P115_OPEN_ACCESS_TOKEN", None)
        existing.pop("P115_OPEN_REFRESH_TOKEN", None)
        os.environ.pop("P115_OPEN_ACCESS_TOKEN", None)
        os.environ.pop("P115_OPEN_REFRESH_TOKEN", None)
    if payload.openlist_url is not None:
        openlist_url = validate_http_origin(payload.openlist_url, "OpenList 地址") if payload.openlist_url.strip() else ""
        if openlist_url:
            existing["OPENLIST_URL"] = openlist_url
            os.environ["OPENLIST_URL"] = openlist_url
        else:
            existing.pop("OPENLIST_URL", None)
            os.environ.pop("OPENLIST_URL", None)
    if payload.openlist_token.strip():
        existing["OPENLIST_TOKEN"] = payload.openlist_token.strip()
        os.environ["OPENLIST_TOKEN"] = payload.openlist_token.strip()
    for key, value in {
        "SEASON_SUBDIRECTORY_ENABLED": payload.season_subdirectory_enabled,
        "OPENLIST_ENABLED": payload.openlist_enabled,
        "OPENLIST_AUTO_SYNC": payload.openlist_auto_sync,
    }.items():
        if value is not None:
            encoded = "true" if value else "false"
            existing[key] = encoded
            os.environ[key] = encoded
    for key, value in {
        "P115_ROOT_PATH": payload.p115_root_path,
        "P115_STAGING_PATH": payload.p115_staging_path,
        "P115_LOCAL_PATH": payload.p115_local_path,
    }.items():
        if value is not None:
            normalized = normalize_save_root(value) if value.strip() else ""
            if not normalized:
                raise HTTPException(status_code=422, detail=f"{key} 不能为空")
            existing[key] = normalized
            os.environ[key] = normalized
    if payload.enabled_providers is not None:
        supported = {"qas", "p115"}
        providers = list(dict.fromkeys(str(value).strip().lower() for value in payload.enabled_providers))
        if not providers or any(value not in supported for value in providers):
            raise HTTPException(status_code=422, detail="至少启用一个受支持的网盘 provider")
        has_open = (
            existing.get("P115_AUTH_MODE") == "open"
            and bool(existing.get("P115_OPEN_ACCESS_TOKEN"))
            and bool(existing.get("P115_OPEN_REFRESH_TOKEN"))
        )
        if "p115" in providers and not valid_p115_cookie(existing.get("P115_COOKIE", "")) and not has_open:
            raise HTTPException(status_code=422, detail="启用原生 115 前请先保存 Cookie 或从 OpenList 导入 115 Open 凭据")
        encoded = ",".join(providers)
        existing["ENABLED_CLOUD_PROVIDERS"] = encoded
        os.environ["ENABLED_CLOUD_PROVIDERS"] = encoded
    if payload.default_provider is not None:
        default_provider = payload.default_provider.strip().lower()
        enabled = set((existing.get("ENABLED_CLOUD_PROVIDERS") or "qas").split(","))
        if default_provider not in enabled:
            raise HTTPException(status_code=422, detail="默认 provider 必须已经启用")
        existing["DEFAULT_CLOUD_PROVIDER"] = default_provider
        os.environ["DEFAULT_CLOUD_PROVIDER"] = default_provider
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
        "TRACKING_POLL_MINUTES": payload.tracking_poll_minutes,
        "TRACKING_RETRY_INTERVAL_MINUTES": payload.tracking_retry_interval_minutes,
        "TRACKING_MAX_RETRIES": payload.tracking_max_retries,
    }
    for key, value in numeric_mapping.items():
        if value is not None:
            minimum, maximum = (1, 1440) if key in {"WISHLIST_POLL_MINUTES", "TRACKING_POLL_MINUTES", "TRACKING_RETRY_INTERVAL_MINUTES"} else (1, 20) if key == "TRACKING_MAX_RETRIES" else (0, 23)
            if not minimum <= value <= maximum:
                raise HTTPException(status_code=422, detail=f"{key} 必须在 {minimum}-{maximum} 之间")
            existing[key] = str(value)
            os.environ[key] = str(value)
    if payload.tracking_check_time is not None:
        try:
            parsed_time = datetime.strptime(payload.tracking_check_time.strip(), "%H:%M")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="TRACKING_CHECK_TIME 必须是 HH:MM") from exc
        normalized_time = parsed_time.strftime("%H:%M")
        existing["TRACKING_CHECK_TIME"] = normalized_time
        os.environ["TRACKING_CHECK_TIME"] = normalized_time
    if payload.wishlist_scheduler_enabled is not None:
        enabled = "true" if payload.wishlist_scheduler_enabled else "false"
        existing["WISHLIST_SCHEDULER_ENABLED"] = enabled
        os.environ["WISHLIST_SCHEDULER_ENABLED"] = enabled
    if payload.tracking_scheduler_enabled is not None:
        enabled = "true" if payload.tracking_scheduler_enabled else "false"
        existing["TRACKING_SCHEDULER_ENABLED"] = enabled
        os.environ["TRACKING_SCHEDULER_ENABLED"] = enabled
    boolean_mapping = {
        "NOTIFICATION_EXTERNAL_ENABLED": payload.notification_external_enabled,
        "TELEGRAM_ENABLED": payload.telegram_enabled,
        "WECOM_ENABLED": payload.wecom_enabled,
        "WECOM_APP_ENABLED": payload.wecom_app_enabled,
        "WECOM_CALLBACK_ENABLED": payload.wecom_callback_enabled,
        "DIRECT_DOWNLOAD_ENABLED": payload.direct_download_enabled,
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
    if payload.direct_download_provider is not None:
        provider = payload.direct_download_provider.strip().lower() or "qas"
        if provider not in {"qas", "p115"}:
            raise HTTPException(status_code=422, detail="下载链接关联网盘只支持夸克或 115")
        existing["DIRECT_DOWNLOAD_PROVIDER"] = provider
        os.environ["DIRECT_DOWNLOAD_PROVIDER"] = provider
    if payload.direct_download_save_path is not None:
        save_path = normalize_save_root(payload.direct_download_save_path) if payload.direct_download_save_path.strip() else ""
        existing["DIRECT_DOWNLOAD_SAVE_PATH"] = save_path
        os.environ["DIRECT_DOWNLOAD_SAVE_PATH"] = save_path
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
    if payload.wecom_callback_url is not None:
        callback_url = payload.wecom_callback_url.strip()
        if callback_url:
            parsed = urlparse(callback_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise HTTPException(status_code=422, detail="企业微信后台回调 URL 必须是完整的 HTTP 或 HTTPS 地址，且不能包含账号、参数或片段")
            callback_url = parsed.geturl()
            existing["WECOM_CALLBACK_URL"] = callback_url
            os.environ["WECOM_CALLBACK_URL"] = callback_url
        else:
            existing.pop("WECOM_CALLBACK_URL", None)
            os.environ.pop("WECOM_CALLBACK_URL", None)
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
    category_payloads = {
        "CATEGORY_PATHS_JSON": payload.category_paths,
        "QAS_CATEGORY_PATHS_JSON": payload.qas_category_paths,
        "P115_CATEGORY_PATHS_JSON": payload.p115_category_paths,
    }
    for env_key, configured_paths in category_payloads.items():
        if not configured_paths:
            continue
        category_paths = {}
        for key, value in configured_paths.items():
            clean_key = key.strip()
            clean_value = value.strip()
            if clean_key:
                if not clean_value:
                    category_paths[clean_key] = ""
                    continue
                normalized = normalize_category_path(clean_value)
                if any(part in {".", ".."} for part in normalized.split("/")):
                    raise HTTPException(status_code=422, detail=f"分类路径 {clean_key} 不能包含 . 或 ..")
                category_paths[clean_key] = normalized
        if category_paths:
            encoded = json.dumps(category_paths, ensure_ascii=False, separators=(",", ":"))
            existing[env_key] = encoded
            os.environ[env_key] = encoded

    ordered = [
        "MEDIA_USER",
        "MEDIA_PASS",
        "AUTH_SECRET",
        "TMDB_API_KEY",
        "QAS_BASE_URL",
        "QAS_TOKEN",
        "MOVIEPILOT_BASE_URL",
        "MOVIEPILOT_API_TOKEN",
        "MOVIEPILOT_115_PLUGIN_ID",
        "MOVIEPILOT_115_REQUEST_TIMEOUT_SECONDS",
        "MOVIEPILOT_115_CONFIRMATION_TIMEOUT_MINUTES",
        "P115_COOKIE",
        "P115_AUTH_MODE",
        "P115_OPEN_ACCESS_TOKEN",
        "P115_OPEN_REFRESH_TOKEN",
        "P115_ROOT_PATH",
        "P115_STAGING_PATH",
        "P115_LOCAL_PATH",
        "P115_REQUEST_TIMEOUT_SECONDS",
        "P115_MAX_SHARE_FILES",
        "ENABLED_CLOUD_PROVIDERS",
        "DEFAULT_CLOUD_PROVIDER",
        "PANSOU_URL",
        "PROXY_URL",
        "CLOUD_SAVE_PATH",
        "QAS_SAVE_PATH",
        "LOCAL_SAVE_PATH",
        "CATEGORY_PATHS_JSON",
        "QAS_CATEGORY_PATHS_JSON",
        "P115_CATEGORY_PATHS_JSON",
        "MEDIA_FOLDER_NAMING_RULE",
        "SEASON_FOLDER_NAMING_RULE",
        "MOVIE_NAMING_RULE",
        "EPISODE_NAMING_RULE",
        "SEASON_SUBDIRECTORY_ENABLED",
        "OPENLIST_ENABLED",
        "OPENLIST_AUTO_SYNC",
        "OPENLIST_URL",
        "OPENLIST_TOKEN",
        "OPENLIST_QAS_LIBRARY_PATH",
        "OPENLIST_P115_LIBRARY_PATH",
        "WISHLIST_SCHEDULER_ENABLED",
        "WISHLIST_POLL_MINUTES",
        "WISHLIST_DEFAULT_CHECK_HOUR",
        "TRACKING_SCHEDULER_ENABLED",
        "TRACKING_POLL_MINUTES",
        "TRACKING_CHECK_TIME",
        "TRACKING_RETRY_INTERVAL_MINUTES",
        "TRACKING_MAX_RETRIES",
        "QAS_CONFIRMATION_TIMEOUT_MINUTES",
        "PUBLIC_BASE_URL",
        "WECOM_CALLBACK_URL",
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
        "DIRECT_DOWNLOAD_ENABLED",
        "DIRECT_DOWNLOAD_PROVIDER",
        "DIRECT_DOWNLOAD_SAVE_PATH",
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


def _config_path() -> Path:
    return Path(os.getenv("MEDIA_CONFIG_PATH", "/app/.env"))


def _read_config_values() -> dict[str, str]:
    env_path = _config_path()
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


@router.get("/export")
def export_config():
    settings = {key: value for key, value in _read_config_values().items() if key not in CONFIG_EXPORT_EXCLUDED}
    return {
        "format": CONFIG_EXPORT_FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings,
        "task_data": _export_task_data(),
    }


@router.post("/import")
def import_config(payload: ConfigImport):
    if payload.format != CONFIG_EXPORT_FORMAT:
        raise HTTPException(status_code=422, detail="不是 MediaIndex 导出的配置文件")
    if not payload.settings:
        raise HTTPException(status_code=422, detail="配置文件中没有可导入的设置")
    invalid = [
        key
        for key, value in payload.settings.items()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not isinstance(value, str) or "\n" in value or "\r" in value
    ]
    if invalid:
        raise HTTPException(status_code=422, detail="配置文件格式无效")
    previous = _read_config_values()
    values = {
        **{key: value for key, value in previous.items() if key in CONFIG_EXPORT_EXCLUDED},
        **{key: value for key, value in payload.settings.items() if key not in CONFIG_EXPORT_EXCLUDED},
    }
    env_path = _config_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(f"{key}={value}" for key, value in sorted(values.items())) + "\n", encoding="utf-8")
    for key in set(previous) | set(values):
        if key in CONFIG_EXPORT_EXCLUDED:
            continue
        if key in values:
            os.environ[key] = values[key]
        else:
            os.environ.pop(key, None)
    get_settings.cache_clear()
    if payload.task_data is not None:
        _restore_task_data(payload.task_data)
    stop_scheduler()
    start_scheduler()
    return {"ok": True, "message": "已覆盖导入全部设置和任务"}


def _export_task_data() -> dict[str, list[dict[str, Any]]]:
    init_db()
    with db() as conn:
        wishlist = [
            {column: row[column] for column in WISHLIST_BACKUP_COLUMNS}
            for row in conn.execute(f"SELECT {','.join(WISHLIST_BACKUP_COLUMNS)} FROM wishlist ORDER BY id").fetchall()
        ]
        tracking: list[dict[str, Any]] = []
        for row in conn.execute(f"SELECT id,{','.join(TRACKING_TASK_BACKUP_COLUMNS)} FROM tracking_tasks ORDER BY id").fetchall():
            task = {column: row[column] for column in TRACKING_TASK_BACKUP_COLUMNS}
            episodes = [
                {column: episode[column] for column in TRACKING_EPISODE_BACKUP_COLUMNS}
                for episode in conn.execute(
                    f"SELECT {','.join(TRACKING_EPISODE_BACKUP_COLUMNS)} FROM tracking_episodes WHERE task_id=? ORDER BY id",
                    (row["id"],),
                ).fetchall()
            ]
            tracking.append({"task": task, "episodes": episodes})
    return {"wishlist": wishlist, "tracking": tracking}


def _restore_task_data(task_data: ConfigTaskBackup) -> None:
    wishlist = [_validate_backup_row(item, WISHLIST_BACKUP_COLUMNS) for item in task_data.wishlist]
    tracking: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for item in task_data.tracking:
        if set(item) - {"task", "episodes"} or not isinstance(item.get("task"), dict):
            raise HTTPException(status_code=422, detail="任务备份格式无效")
        episodes = item.get("episodes", [])
        if not isinstance(episodes, list):
            raise HTTPException(status_code=422, detail="追更集数备份格式无效")
        tracking.append(
            (
                _validate_backup_row(item["task"], TRACKING_TASK_BACKUP_COLUMNS),
                [_validate_backup_row(episode, TRACKING_EPISODE_BACKUP_COLUMNS) for episode in episodes],
            )
        )

    init_db()
    with db() as conn:
        conn.execute("DELETE FROM tracking_episodes")
        conn.execute("DELETE FROM tracking_tasks")
        conn.execute("DELETE FROM wishlist")
        for item in wishlist:
            _insert_backup_row(conn, "wishlist", item)
        for task, episodes in tracking:
            cursor = _insert_backup_row(conn, "tracking_tasks", task)
            for episode in episodes:
                _insert_backup_row(conn, "tracking_episodes", {**episode, "task_id": cursor.lastrowid})


def _validate_backup_row(item: Any, allowed_columns: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) - set(allowed_columns):
        raise HTTPException(status_code=422, detail="任务备份包含不支持的字段")
    if not item:
        raise HTTPException(status_code=422, detail="任务备份中存在空记录")
    if any(not isinstance(value, (str, int, float, bool, type(None))) for value in item.values()):
        raise HTTPException(status_code=422, detail="任务备份字段格式无效")
    return dict(item)


def _insert_backup_row(conn: Any, table: str, item: dict[str, Any]):
    columns = tuple(item)
    return conn.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        tuple(item[column] for column in columns),
    )


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


def saved_endpoint_label(value: str) -> str:
    return "已保存" if str(value or "").strip() else ""


def _normalize_browse_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return "/"
    if not raw.startswith("/"):
        raise HTTPException(status_code=422, detail="目录路径必须以 / 开头")
    parts = [part for part in raw.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=422, detail="目录路径不能包含 . 或 ..")
    return "/" + "/".join(parts) if parts else "/"


def _qas_directories_from_response(response: object) -> list[dict[str, object]]:
    payload = response.get("data", response) if isinstance(response, dict) else {}
    items = payload.get("list") or payload.get("files") or [] if isinstance(payload, dict) else []
    directories: list[dict[str, object]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file_name") or item.get("name") or "").strip()
        if not name:
            continue
        is_dir = bool(item.get("dir") or item.get("is_dir") or item.get("isdir"))
        if is_dir:
            directories.append({"name": name, "is_dir": True})
    return directories


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
        "message": "PanSou 接口连接正常" if response.items else "PanSou 接口可用，本次测试未返回网盘资源",
        "result_count": len(response.items),
    }


@router.post("/test-tmdb")
def test_tmdb():
    settings = get_settings()
    if not settings.tmdb_api_key.strip():
        raise HTTPException(status_code=422, detail="请先保存 TMDB API Key")
    try:
        genres = TmdbClient().genres("movie")
    except Exception as exc:
        return {"ok": False, "message": f"TMDB 连接失败：{type(exc).__name__}"}
    return {
        "ok": True,
        "message": "TMDB API Key 连接正常" if isinstance(genres, list) else "TMDB 已响应，但返回格式异常",
        "genre_count": len(genres) if isinstance(genres, list) else 0,
    }


@router.post("/test-qas")
def test_qas():
    settings = get_settings()
    if not settings.qas_base_url.strip() or not settings.qas_token.strip():
        raise HTTPException(status_code=422, detail="请先保存 QAS 地址和 Token")
    try:
        data = QasClient().data()
    except Exception as exc:
        return {"ok": False, "message": f"QAS 连接失败：{type(exc).__name__}"}
    if not isinstance(data, dict):
        return {"ok": False, "message": "QAS 已响应，但返回格式异常"}
    return {"ok": True, "message": "QAS 地址和 Token 连接正常"}


@router.post("/test-moviepilot-115")
def test_moviepilot_115():
    settings = get_settings()
    if not settings.moviepilot_base_url.strip() or not settings.moviepilot_api_token.strip():
        raise HTTPException(status_code=422, detail="请先保存 MoviePilot API 地址和 Token")
    try:
        probe = MoviePilot115Client(settings).probe(timeout=15)
    except MoviePilot115Error as exc:
        return {"ok": False, "message": str(exc)}
    result = probe.as_dict()
    if not probe.plugin_available:
        return {
            "ok": False,
            "message": "MoviePilot 连接正常，但未发现 115 网盘 STRM 助手接口",
            **result,
        }
    if not probe.plugin_enabled:
        return {
            "ok": False,
            "message": "已找到 115 网盘 STRM 助手，但插件尚未启用",
            **result,
        }
    if not probe.client_ready:
        return {
            "ok": False,
            "message": "插件已连接，但 115 客户端尚未完成授权",
            **result,
        }
    return {
        "ok": True,
        "message": "MoviePilot 与 115 网盘 STRM 助手连接正常",
        **result,
    }


@router.post("/test-p115")
def test_p115():
    settings = get_settings()
    if not settings.p115_cookie.strip() and not (settings.p115_auth_mode == "open" and settings.p115_open_access_token and settings.p115_open_refresh_token):
        raise HTTPException(status_code=422, detail="请先保存 115 Cookie 或导入 115 Open 凭据")
    client = P115Client(settings)
    try:
        root_items = client.list_directory(0)
        client.test_cloud_download_capability()
    except P115Error as exc:
        if _can_fallback_to_openlist(settings):
            try:
                openlist = OpenListClient()
                root_items = openlist.list_directories(openlist.p115_storage_path("/"))
            except OpenListError as fallback_exc:
                return {"ok": False, "message": f"无法通过 OpenList 读取 115 目录：{fallback_exc}"}
            return {
                "ok": True,
                "message": "已通过 OpenList 验证 115 目录；磁力、电驴和 HTTP 下载链接会提交到已选保存路径。",
                "root_item_count": len(root_items),
                "fallback": "openlist",
            }
        return {"ok": False, "message": str(exc)}
    return {
        "ok": True,
        "message": "115 Open 目录读取与离线下载权限正常" if settings.p115_auth_mode == "open" else "115 Cookie、目录读取与离线下载权限正常",
        "root_item_count": len(root_items),
    }


@router.post("/import-p115-from-openlist")
def import_p115_from_openlist():
    try:
        auth = OpenListClient().p115_auth()
    except OpenListError as exc:
        return {"ok": False, "message": str(exc)}
    env_path = _config_path()
    existing = _read_config_values()
    if auth["mode"] == "cookie":
        cookie = auth["cookie"]
        if not valid_p115_cookie(cookie):
            return {"ok": False, "message": "OpenList 中的 115 Cookie 缺少 UID、CID 或 SEID"}
        existing["P115_COOKIE"] = cookie
        existing["P115_AUTH_MODE"] = "cookie"
        existing.pop("P115_OPEN_ACCESS_TOKEN", None)
        existing.pop("P115_OPEN_REFRESH_TOKEN", None)
        message = "已从 OpenList 导入 115 Cookie"
    else:
        existing["P115_AUTH_MODE"] = "open"
        existing["P115_OPEN_ACCESS_TOKEN"] = auth["access_token"]
        existing["P115_OPEN_REFRESH_TOKEN"] = auth["refresh_token"]
        existing.pop("P115_COOKIE", None)
        message = "已从 OpenList 导入 115 Open 开放平台凭据"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(f"{key}={value}" for key, value in sorted(existing.items())) + "\n", encoding="utf-8")
    for key in ("P115_COOKIE", "P115_AUTH_MODE", "P115_OPEN_ACCESS_TOKEN", "P115_OPEN_REFRESH_TOKEN"):
        if key in existing:
            os.environ[key] = existing[key]
        else:
            os.environ.pop(key, None)
    get_settings.cache_clear()
    return {"ok": True, "message": message, "mode": auth["mode"], "mount_path": auth.get("mount_path", "")}


@router.post("/clear-p115-open")
def clear_p115_open():
    """Remove only 115 Open credentials and preserve an existing Cookie."""
    env_path = _config_path()
    existing = _read_config_values()
    existing.pop("P115_OPEN_ACCESS_TOKEN", None)
    existing.pop("P115_OPEN_REFRESH_TOKEN", None)
    has_cookie = valid_p115_cookie(existing.get("P115_COOKIE", ""))
    if has_cookie:
        existing["P115_AUTH_MODE"] = "cookie"
    else:
        existing.pop("P115_AUTH_MODE", None)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(f"{key}={value}" for key, value in sorted(existing.items())) + "\n", encoding="utf-8")
    for key in ("P115_COOKIE", "P115_AUTH_MODE", "P115_OPEN_ACCESS_TOKEN", "P115_OPEN_REFRESH_TOKEN"):
        if key in existing:
            os.environ[key] = existing[key]
        else:
            os.environ.pop(key, None)
    get_settings.cache_clear()
    return {
        "ok": True,
        "message": "已清除 115 Open 授权，当前使用 115 Cookie" if has_cookie else "已清除 115 Open 授权",
        "has_p115_cookie": has_cookie,
        "has_p115_open": False,
    }


@router.post("/browse-provider-path")
def browse_provider_path(payload: ProviderBrowseRequest):
    provider = payload.provider.strip().lower()
    if provider not in {"qas", "p115"}:
        raise HTTPException(status_code=422, detail="只支持夸克或 115 目录选择")
    path = _normalize_browse_path(payload.path)
    if provider == "p115":
        settings = get_settings()
        try:
            client = P115Client(settings)
            cid = client.directory_id(path)
            if cid == "0" and path != "/":
                raise P115Error("目标目录不存在")
            directories = [
                {"name": item.name, "is_dir": True}
                for item in client.list_directory(cid)
                if item.is_dir and item.name
            ]
        except P115Error as exc:
            if not (
                settings.p115_auth_mode == "open"
                and settings.openlist_url.strip()
                and settings.openlist_token.strip()
            ):
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            try:
                openlist = OpenListClient()
                directories = openlist.list_directories(openlist.p115_storage_path(path))
            except OpenListError as fallback_exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"无法通过 OpenList 读取 115 目录：{fallback_exc}",
                ) from fallback_exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"115 目录读取失败：{type(exc).__name__}") from exc
    else:
        try:
            response = QasClient().savepath_detail(path)
            directories = _qas_directories_from_response(response)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"QAS 目录读取失败：{type(exc).__name__}") from exc
    directories.sort(key=lambda item: item["name"])
    return {"ok": True, "provider": provider, "path": path, "directories": directories}


def _can_fallback_to_openlist(settings) -> bool:
    return bool(
        settings.p115_auth_mode == "open"
        and settings.openlist_url.strip()
        and settings.openlist_token.strip()
    )


@router.post("/import-p115-from-moviepilot")
def import_p115_from_moviepilot():
    settings = get_settings()
    if not settings.moviepilot_base_url.strip() or not settings.moviepilot_api_token.strip():
        raise HTTPException(status_code=422, detail="请先保存 MoviePilot API 地址和 Token")
    try:
        cookie = MoviePilot115Client(settings).read_p115_cookie(timeout=15)
    except MoviePilot115Error as exc:
        return {"ok": False, "message": str(exc)}
    result = update_config(ConfigUpdate(p115_cookie=cookie))
    return {
        "ok": bool(result.get("ok")),
        "message": "已从 MoviePilot 安全导入 115 Cookie",
        "has_p115_cookie": True,
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
