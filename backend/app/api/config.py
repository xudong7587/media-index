import os
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings, normalize_category_path
from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.clients.http import open_url
from app.clients.moviepilot_115 import MoviePilot115Client, MoviePilot115Error
from app.clients.p115 import P115Client, P115Error, valid_p115_cookie
from app.clients.quark import QuarkClient, QuarkError, normalize_quark_cookie, valid_quark_cookie
from app.clients.openlist import OpenListClient, OpenListError
from app.core.security import require_user
from app.core.env_file import atomic_write_env, env_file_lock
from app.db.database import db, init_db
from app.services.paths import normalize_save_root, validate_naming_rule
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.quality_priority import configured_quality_keywords
from app.services.quark_login import QuarkLoginService
from app.services.p115_login import P115OpenLoginService

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(require_user)])

_REVEALABLE_SECRET_FIELDS = {
    "tmdb_api_key",
    "qas_token",
    "moviepilot_api_token",
    "p115_cookie",
    "p115_open_access_token",
    "p115_open_refresh_token",
    "quark_cookie",
    "emby_api_key",
    "emby_deletion_webhook_token",
    "openlist_token",
    "telegram_bot_token",
    "wecom_key",
    "wecom_app_secret",
    "wecom_callback_token",
    "wecom_callback_aes_key",
}


def current_version() -> str:
    candidates = [Path("/app/VERSION"), Path(__file__).resolve().parents[3] / "VERSION"]
    for path in candidates:
        if path.is_file():
            version = path.read_text(encoding="utf-8").strip()
            local_path = path.with_name("VERSION.local")
            if local_path.is_file():
                local_build = local_path.read_text(encoding="utf-8").strip()
                if local_build:
                    return f"{version}+local.{local_build}"
            return version
    return "0.5.0-dev"


class ConfigUpdate(BaseModel):
    tmdb_api_key: str = ""
    qas_base_url: str = ""
    qas_token: str = ""
    moviepilot_base_url: str | None = None
    moviepilot_api_token: str = ""
    moviepilot_115_plugin_id: str | None = None
    p115_cookie: str = ""
    p115_auth_mode: Literal["cookie", "open"] | None = None
    p115_open_access_token: str = ""
    p115_open_refresh_token: str = ""
    quark_cookie: str = ""
    quark_root_path: str | None = None
    quark_staging_path: str | None = None
    p115_root_path: str | None = None
    p115_staging_path: str | None = None
    p115_local_path: str | None = None
    p115_strm_source_root: str | None = None
    quark_strm_source_root: str | None = None
    enabled_providers: list[str] | None = None
    default_provider: str | None = None
    pansou_url: str = ""
    proxy_url: str | None = None
    cloud_save_path: str = ""
    qas_save_path: str = ""
    local_save_path: str = ""
    category_paths: dict[str, str] = Field(default_factory=dict)
    qas_category_paths: dict[str, str] = Field(default_factory=dict)
    p115_category_paths: dict[str, str] = Field(default_factory=dict)
    quark_category_paths: dict[str, str] = Field(default_factory=dict)
    strm_output_root: str | None = None
    strm_playback_base_url: str | None = None
    strm_library_root_id: str | None = None
    p115_strm_enabled: bool | None = None
    p115_strm_incremental_cron: str | None = None
    p115_strm_scrape_enabled: bool | None = None
    quark_strm_enabled: bool | None = None
    quark_strm_incremental_cron: str | None = None
    quark_strm_scrape_enabled: bool | None = None
    strm_video_extensions: list[str] | None = None
    strm_excluded_name_tokens: list[str] | None = None
    strm_min_file_size_mb: int | None = None
    emby_base_url: str | None = None
    emby_api_key: str = ""
    emby_proxy_port: int | None = None
    emby_deletion_webhook_token: str = ""
    emby_strm_library_root: str | None = None
    emby_deletion_auto_confirm: bool | None = None
    emby_deletion_mode: str | None = None
    emby_library_refresh_enabled: bool | None = None
    emby_library_id: str | None = None
    emby_cover_refresh_enabled: bool | None = None
    emby_cover_refresh_hours: int | None = None
    emby_cover_style: Literal["collage", "showcase", "mosaic", "minimal"] | None = None
    media_folder_naming_rule: str | None = None
    season_folder_naming_rule: str | None = None
    movie_naming_rule: str | None = None
    episode_naming_rule: str | None = None
    quality_priority_keywords: list[str] | None = None
    season_subdirectory_enabled: bool | None = None
    openlist_enabled: bool | None = None
    openlist_auto_sync: bool | None = None
    openlist_auto_sync_direction: Literal["bidirectional", "qas_to_p115", "p115_to_qas"] | None = None
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
    telegram_channel_source_enabled: bool | None = None
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
    interaction_providers: list[str] | None = None
    direct_download_provider: str | None = None
    direct_download_save_path: str | None = None


class QasPansouUpdate(BaseModel):
    enabled: bool


class QuarkQrPollRequest(BaseModel):
    session_id: str = Field(min_length=20, max_length=128)


class P115QrPollRequest(BaseModel):
    session_id: str = Field(min_length=20, max_length=128)


class QuarkShareInspectionRequest(BaseModel):
    share_url: str = Field(min_length=20, max_length=2048)


_quark_login = QuarkLoginService()
_p115_login = P115OpenLoginService()


class ConfigImport(BaseModel):
    format: str
    settings: dict[str, str] = Field(max_length=250)
    task_data: "ConfigTaskBackup | None" = None


class ConfigTaskBackup(BaseModel):
    wishlist: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    tracking: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)


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
CONFIG_IMPORT_ALLOWED = {name.upper() for name in Settings.model_fields} | CONFIG_EXPORT_EXCLUDED | {
    "NOTIFICATION_ENABLED_AT",
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


class LocalBrowseRequest(BaseModel):
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
        "moviepilot_base_url": redact_url_credentials(settings.moviepilot_base_url),
        "has_moviepilot_token": bool(settings.moviepilot_api_token),
        "moviepilot_115_plugin_id": settings.moviepilot_115_plugin_id,
        "has_p115_cookie": bool(settings.p115_cookie),
        "has_quark_cookie": valid_quark_cookie(str(getattr(settings, "quark_cookie", ""))),
        "quark_root_path": getattr(settings, "quark_root_path", ""),
        "quark_staging_path": getattr(settings, "quark_staging_path", ""),
        "p115_auth_mode": p115_auth_mode if p115_auth_mode in {"cookie", "open"} else "cookie",
        "has_p115_open": bool(p115_open_access_token and p115_open_refresh_token),
        "p115_root_path": settings.p115_root_path,
        "p115_staging_path": settings.p115_staging_path,
        "p115_local_path": settings.p115_local_path,
        "p115_strm_source_root": getattr(settings, "p115_strm_source_root", "/strm"),
        "quark_strm_source_root": getattr(settings, "quark_strm_source_root", "/strm"),
        "enabled_providers": list(settings.enabled_provider_keys()),
        "default_provider": settings.default_provider_key(),
        "has_pansou": bool(settings.pansou_url),
        "qas_base_url": redact_url_credentials(settings.qas_base_url),
        "pansou_url": redact_url_credentials(settings.pansou_url),
        "has_proxy": bool(settings.proxy_url),
        "proxy_url": redact_url_credentials(settings.proxy_url),
        "cloud_root": settings.cloud_save_path,
        "qas_root": settings.provider_save_root("qas"),
        "local_root": settings.local_save_path,
        "category_paths": settings.category_paths(),
        "qas_category_paths": settings.provider_category_paths("qas"),
        "p115_category_paths": settings.provider_category_paths("p115"),
        "quark_category_paths": settings.provider_category_paths("quark"),
        "strm_output_root": getattr(settings, "strm_output_root", ""),
        "strm_playback_base_url": getattr(settings, "strm_playback_base_url", ""),
        "strm_library_root_id": getattr(settings, "strm_library_root_id", "default"),
        "p115_strm_enabled": bool(getattr(settings, "p115_strm_enabled", False)),
        "p115_strm_incremental_cron": getattr(settings, "p115_strm_incremental_cron", ""),
        "p115_strm_scrape_enabled": bool(getattr(settings, "p115_strm_scrape_enabled", False)),
        "quark_strm_enabled": bool(getattr(settings, "quark_strm_enabled", False)),
        "quark_strm_incremental_cron": getattr(settings, "quark_strm_incremental_cron", ""),
        "quark_strm_scrape_enabled": bool(getattr(settings, "quark_strm_scrape_enabled", False)),
        "strm_video_extensions": _json_string_list(getattr(settings, "strm_video_extensions_json", ""), [".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".wmv", ".webm", ".iso"]),
        "strm_excluded_name_tokens": _json_string_list(getattr(settings, "strm_excluded_name_tokens_json", ""), ["trailer", "sample", "preview", "花絮", "预告", "广告"]),
        "strm_min_file_size_mb": max(0, int(getattr(settings, "strm_min_file_size_mb", 0) or 0)),
        "emby_base_url": redact_url_credentials(getattr(settings, "emby_base_url", "")),
        "has_emby_api_key": bool(getattr(settings, "emby_api_key", "")),
        "emby_proxy_port": int(getattr(settings, "emby_proxy_port", 8097)),
        "has_emby_deletion_webhook_token": bool(getattr(settings, "emby_deletion_webhook_token", "")),
        "emby_strm_library_root": getattr(settings, "emby_strm_library_root", ""),
        "emby_deletion_auto_confirm": bool(getattr(settings, "emby_deletion_auto_confirm", False)),
        "emby_deletion_mode": getattr(settings, "emby_deletion_mode", "trash"),
        "emby_library_refresh_enabled": bool(getattr(settings, "emby_library_refresh_enabled", False)),
        "emby_library_id": getattr(settings, "emby_library_id", ""),
        "emby_cover_refresh_enabled": bool(getattr(settings, "emby_cover_refresh_enabled", False)),
        "emby_cover_refresh_hours": max(1, int(getattr(settings, "emby_cover_refresh_hours", 168) or 168)),
        "emby_cover_style": getattr(settings, "emby_cover_style", "collage"),
        "media_folder_naming_rule": settings.media_folder_naming_rule,
        "season_folder_naming_rule": settings.season_folder_naming_rule,
        "movie_naming_rule": settings.movie_naming_rule,
        "episode_naming_rule": settings.episode_naming_rule,
        "quality_priority_keywords": list(configured_quality_keywords(getattr(settings, "quality_priority_keywords_json", ""))),
        "season_subdirectory_enabled": settings.season_subdirectory_enabled,
        "openlist_enabled": settings.openlist_enabled,
        "openlist_auto_sync": settings.openlist_auto_sync,
        "openlist_auto_sync_direction": getattr(settings, "openlist_auto_sync_direction", "bidirectional"),
        "openlist_url": redact_url_credentials(settings.openlist_url),
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
        "telegram_channel_source_enabled": bool(getattr(settings, "telegram_channel_source_enabled", False)),
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
        "interaction_providers": list(
            getattr(settings, "interaction_provider_keys", lambda: settings.enabled_provider_keys())()
        ),
        "direct_download_provider": "p115",
        "direct_download_save_path": getattr(settings, "direct_download_save_path", ""),
        "version": current_version(),
    }


@router.get("/secret/{name}")
def reveal_secret(name: str):
    if name not in _REVEALABLE_SECRET_FIELDS:
        raise HTTPException(status_code=404, detail="配置项不存在或不允许显示")
    value = str(getattr(get_settings(), name, "") or "")
    if not value:
        raise HTTPException(status_code=404, detail="该密钥尚未配置")
    return {"name": name, "value": value}


@router.put("")
def update_config(payload: ConfigUpdate):
    with env_file_lock():
        snapshot = {key: os.environ.get(key) for key in CONFIG_IMPORT_ALLOWED}
        try:
            return _update_config(payload)
        except Exception:
            for key, value in snapshot.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()
            raise


def _update_config(payload: ConfigUpdate):
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
        "QAS_TOKEN": payload.qas_token,
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
    for key, value, label in (
        ("QAS_BASE_URL", payload.qas_base_url, "QAS 地址"),
        ("PANSOU_URL", payload.pansou_url, "PanSou 地址"),
    ):
        if value.strip():
            normalized = validate_http_origin(value, label)
            existing[key] = normalized
            os.environ[key] = normalized
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
    if payload.p115_open_access_token.strip() or payload.p115_open_refresh_token.strip():
        access_token = payload.p115_open_access_token.strip()
        refresh_token = payload.p115_open_refresh_token.strip()
        if not access_token or not refresh_token or len(access_token) > 4096 or len(refresh_token) > 4096:
            raise HTTPException(status_code=422, detail="115 文件接口需要完整的 Access Token 和 Refresh Token")
        existing["P115_OPEN_ACCESS_TOKEN"] = access_token
        existing["P115_OPEN_REFRESH_TOKEN"] = refresh_token
        os.environ["P115_OPEN_ACCESS_TOKEN"] = access_token
        os.environ["P115_OPEN_REFRESH_TOKEN"] = refresh_token
        existing["P115_AUTH_MODE"] = "open"
        os.environ["P115_AUTH_MODE"] = "open"
    if payload.p115_auth_mode is not None:
        if payload.p115_auth_mode == "open" and not (existing.get("P115_OPEN_ACCESS_TOKEN") and existing.get("P115_OPEN_REFRESH_TOKEN")):
            raise HTTPException(status_code=422, detail="请先完成 115 文件接口授权")
        if payload.p115_auth_mode == "cookie" and not valid_p115_cookie(existing.get("P115_COOKIE", "")):
            raise HTTPException(status_code=422, detail="请先保存有效的 115 Cookie")
        existing["P115_AUTH_MODE"] = payload.p115_auth_mode
        os.environ["P115_AUTH_MODE"] = payload.p115_auth_mode
    if payload.quark_cookie.strip():
        quark_cookie = normalize_quark_cookie(payload.quark_cookie)
        if not valid_quark_cookie(quark_cookie):
            raise HTTPException(status_code=422, detail="夸克 Cookie 格式无效")
        existing["QUARK_COOKIE"] = quark_cookie
        os.environ["QUARK_COOKIE"] = quark_cookie
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
    if payload.openlist_auto_sync_direction is not None:
        existing["OPENLIST_AUTO_SYNC_DIRECTION"] = payload.openlist_auto_sync_direction
        os.environ["OPENLIST_AUTO_SYNC_DIRECTION"] = payload.openlist_auto_sync_direction
    for key, value in {
        "P115_ROOT_PATH": payload.p115_root_path,
        "P115_STAGING_PATH": payload.p115_staging_path,
        "P115_LOCAL_PATH": payload.p115_local_path,
        "QUARK_ROOT_PATH": payload.quark_root_path,
        "QUARK_STAGING_PATH": payload.quark_staging_path,
        "P115_STRM_SOURCE_ROOT": payload.p115_strm_source_root,
        "QUARK_STRM_SOURCE_ROOT": payload.quark_strm_source_root,
    }.items():
        if value is not None:
            normalized = normalize_save_root(value) if value.strip() else ""
            if not normalized:
                raise HTTPException(status_code=422, detail=f"{key} 不能为空")
            existing[key] = normalized
            os.environ[key] = normalized
    if payload.enabled_providers is not None:
        supported = {"quark", "p115"}
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
        if "quark" in providers and not valid_quark_cookie(existing.get("QUARK_COOKIE", "")):
            raise HTTPException(status_code=422, detail="启用原生夸克前请先保存 Cookie 或完成扫码授权")
        encoded = ",".join(providers)
        existing["ENABLED_CLOUD_PROVIDERS"] = encoded
        os.environ["ENABLED_CLOUD_PROVIDERS"] = encoded
    if payload.default_provider is not None:
        default_provider = payload.default_provider.strip().lower()
        enabled = set((existing.get("ENABLED_CLOUD_PROVIDERS") or "quark").split(","))
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
    if payload.strm_output_root is not None:
        output_root = payload.strm_output_root.strip()
        if len(output_root) > 2000 or "\x00" in output_root or "\r" in output_root or "\n" in output_root:
            raise HTTPException(status_code=422, detail="STRM 输出目录无效")
        existing["STRM_OUTPUT_ROOT"] = output_root
        os.environ["STRM_OUTPUT_ROOT"] = output_root
    if payload.emby_strm_library_root is not None:
        raw_library_root = payload.emby_strm_library_root
        if len(raw_library_root) > 2000 or any(char in raw_library_root for char in "\x00\r\n"):
            raise HTTPException(status_code=422, detail="Emby STRM 媒体库根目录无效")
        library_root = raw_library_root.strip().replace("\\", "/").rstrip("/")
        if library_root:
            existing["EMBY_STRM_LIBRARY_ROOT"] = library_root
            os.environ["EMBY_STRM_LIBRARY_ROOT"] = library_root
        else:
            existing.pop("EMBY_STRM_LIBRARY_ROOT", None)
            os.environ.pop("EMBY_STRM_LIBRARY_ROOT", None)
    if payload.strm_playback_base_url is not None:
        playback_raw = payload.strm_playback_base_url.strip()
        if playback_raw:
            playback_base = validate_http_origin(playback_raw, "STRM_PLAYBACK_BASE_URL")
            existing["STRM_PLAYBACK_BASE_URL"] = playback_base
            os.environ["STRM_PLAYBACK_BASE_URL"] = playback_base
        else:
            existing.pop("STRM_PLAYBACK_BASE_URL", None)
            os.environ.pop("STRM_PLAYBACK_BASE_URL", None)
    if payload.strm_library_root_id is not None:
        root_id = payload.strm_library_root_id.strip() or "default"
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", root_id):
            raise HTTPException(status_code=422, detail="STRM 媒体库标识仅支持字母、数字、下划线和连字符")
        existing["STRM_LIBRARY_ROOT_ID"] = root_id
        os.environ["STRM_LIBRARY_ROOT_ID"] = root_id
    for provider, expression in (("P115", payload.p115_strm_incremental_cron), ("QUARK", payload.quark_strm_incremental_cron)):
        if expression is None:
            continue
        cron = expression.strip()
        if cron:
            try:
                from apscheduler.triggers.cron import CronTrigger
                CronTrigger.from_crontab(cron)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"{provider} STRM 定时增量扫描必须是 5 段 Cron 表达式") from exc
        key = f"{provider}_STRM_INCREMENTAL_CRON"
        if cron:
            existing[key] = cron
            os.environ[key] = cron
        else:
            existing.pop(key, None)
            os.environ.pop(key, None)
    if payload.emby_base_url is not None:
        emby_base_url = validate_http_origin(payload.emby_base_url, "Emby 地址") if payload.emby_base_url.strip() else ""
        if emby_base_url:
            existing["EMBY_BASE_URL"] = emby_base_url
            os.environ["EMBY_BASE_URL"] = emby_base_url
        else:
            existing.pop("EMBY_BASE_URL", None)
            os.environ.pop("EMBY_BASE_URL", None)
    if payload.emby_api_key.strip():
        existing["EMBY_API_KEY"] = payload.emby_api_key.strip()
        os.environ["EMBY_API_KEY"] = payload.emby_api_key.strip()
    if payload.emby_proxy_port is not None:
        if os.getenv("EMBY_PROXY_PORT_LOCKED", "").strip().lower() in {"1", "true", "yes", "on"}:
            raise HTTPException(status_code=409, detail="302 内网端口由 Compose 锁定，请修改 MEDIA_PLAYBACK_PORT 后重新部署")
        if not 1024 <= payload.emby_proxy_port <= 65535:
            raise HTTPException(status_code=422, detail="Emby 反代端口必须在 1024-65535 之间")
        existing["EMBY_PROXY_PORT"] = str(payload.emby_proxy_port)
        os.environ["EMBY_PROXY_PORT"] = str(payload.emby_proxy_port)
    if payload.emby_library_id is not None:
        library_id = payload.emby_library_id.strip()
        if library_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", library_id):
            raise HTTPException(status_code=422, detail="Emby 媒体库 ID 格式无效")
        existing["EMBY_LIBRARY_ID"] = library_id
        os.environ["EMBY_LIBRARY_ID"] = library_id
    if payload.emby_deletion_mode is not None:
        if payload.emby_deletion_mode != "trash":
            raise HTTPException(status_code=422, detail="当前仅支持将 115 源文件移入回收站")
        existing["EMBY_DELETION_MODE"] = "trash"
        os.environ["EMBY_DELETION_MODE"] = "trash"
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
        "P115_STRM_ENABLED": payload.p115_strm_enabled,
        "P115_STRM_SCRAPE_ENABLED": payload.p115_strm_scrape_enabled,
        "QUARK_STRM_ENABLED": payload.quark_strm_enabled,
        "QUARK_STRM_SCRAPE_ENABLED": payload.quark_strm_scrape_enabled,
        "EMBY_LIBRARY_REFRESH_ENABLED": payload.emby_library_refresh_enabled,
        "EMBY_COVER_REFRESH_ENABLED": payload.emby_cover_refresh_enabled,
        "EMBY_DELETION_AUTO_CONFIRM": payload.emby_deletion_auto_confirm,
        "NOTIFICATION_EXTERNAL_ENABLED": payload.notification_external_enabled,
        "TELEGRAM_ENABLED": payload.telegram_enabled,
        "TELEGRAM_CHANNEL_SOURCE_ENABLED": payload.telegram_channel_source_enabled,
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
    if payload.emby_cover_refresh_hours is not None:
        hours = max(1, min(8760, int(payload.emby_cover_refresh_hours)))
        existing["EMBY_COVER_REFRESH_HOURS"] = str(hours)
        os.environ["EMBY_COVER_REFRESH_HOURS"] = str(hours)
    if payload.emby_cover_style is not None:
        existing["EMBY_COVER_STYLE"] = payload.emby_cover_style
        os.environ["EMBY_COVER_STYLE"] = payload.emby_cover_style
    if any(
        value is not None
        for value in (
            payload.strm_output_root,
            payload.strm_playback_base_url,
            payload.p115_strm_enabled,
            payload.quark_strm_enabled,
            payload.emby_base_url,
            payload.emby_proxy_port,
        )
    ):
        output_root = existing.get("STRM_OUTPUT_ROOT", os.getenv("STRM_OUTPUT_ROOT", "")).strip()
        playback_base = existing.get("STRM_PLAYBACK_BASE_URL", os.getenv("STRM_PLAYBACK_BASE_URL", "")).strip()
        emby_base = existing.get("EMBY_BASE_URL", os.getenv("EMBY_BASE_URL", "")).strip()
        for label, key in (("115", "P115_STRM_ENABLED"), ("夸克", "QUARK_STRM_ENABLED")):
            enabled = existing.get(key, os.getenv(key, "false")).lower() == "true"
            if enabled and (not output_root or (not playback_base and not emby_base)):
                raise HTTPException(status_code=422, detail=f"启用 {label} STRM 前必须填写输出目录和 Emby 内网地址")
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
        "EMBY_DELETION_WEBHOOK_TOKEN": payload.emby_deletion_webhook_token,
    }
    for key, value in secret_mapping.items():
        if value.strip():
            if key == "TELEGRAM_BOT_TOKEN" and not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{20,}", value.strip()):
                raise HTTPException(status_code=422, detail="Bot Token 格式无效；应为 BotFather 提供的“数字:密钥”，不要填写 Bot 编号")
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
        provider = payload.direct_download_provider.strip().lower() or "p115"
        if provider != "p115":
            raise HTTPException(status_code=422, detail="磁力、电驴和普通下载链接目前只支持 115 离线下载")
        existing["DIRECT_DOWNLOAD_PROVIDER"] = provider
        os.environ["DIRECT_DOWNLOAD_PROVIDER"] = provider
    if payload.interaction_providers is not None:
        providers = tuple(
            dict.fromkeys(
                str(value).strip().lower()
                for value in payload.interaction_providers
                if str(value).strip().lower() in {"qas", "p115"}
            )
        )
        if not providers:
            raise HTTPException(status_code=422, detail="至少选择一个交互网盘")
        encoded = ",".join(providers)
        existing["INTERACTION_CLOUD_PROVIDERS"] = encoded
        os.environ["INTERACTION_CLOUD_PROVIDERS"] = encoded
    if payload.direct_download_save_path is not None:
        save_path = normalize_save_root(payload.direct_download_save_path) if payload.direct_download_save_path.strip() else ""
        existing["DIRECT_DOWNLOAD_SAVE_PATH"] = save_path
        os.environ["DIRECT_DOWNLOAD_SAVE_PATH"] = save_path
    endpoint_mapping = {
        "PUBLIC_BASE_URL": payload.public_base_url,
        "TELEGRAM_API_HOST": payload.telegram_api_host,
        "WECOM_ORIGIN": payload.wecom_origin,
    }
    if payload.strm_video_extensions is not None:
        values = _safe_strm_extensions(payload.strm_video_extensions)
        existing["STRM_VIDEO_EXTENSIONS_JSON"] = json.dumps(values, ensure_ascii=False)
        os.environ["STRM_VIDEO_EXTENSIONS_JSON"] = existing["STRM_VIDEO_EXTENSIONS_JSON"]
    if payload.strm_excluded_name_tokens is not None:
        values = _safe_strm_tokens(payload.strm_excluded_name_tokens)
        existing["STRM_EXCLUDED_NAME_TOKENS_JSON"] = json.dumps(values, ensure_ascii=False)
        os.environ["STRM_EXCLUDED_NAME_TOKENS_JSON"] = existing["STRM_EXCLUDED_NAME_TOKENS_JSON"]
    if payload.strm_min_file_size_mb is not None:
        if not 0 <= payload.strm_min_file_size_mb <= 100_000:
            raise HTTPException(status_code=422, detail="STRM 最小文件大小必须在 0-100000 MiB")
        existing["STRM_MIN_FILE_SIZE_MB"] = str(payload.strm_min_file_size_mb)
        os.environ["STRM_MIN_FILE_SIZE_MB"] = str(payload.strm_min_file_size_mb)
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
        "QUARK_CATEGORY_PATHS_JSON": payload.quark_category_paths,
    }
    for env_key, configured_paths in category_payloads.items():
        if not configured_paths:
            continue
        category_paths: dict[str, str] = {}
        try:
            saved_paths = json.loads(existing.get(env_key, "{}"))
            if isinstance(saved_paths, dict):
                category_paths = {
                    str(key): str(value)
                    for key, value in saved_paths.items()
                    if isinstance(key, str) and isinstance(value, str) and key.strip()
                }
        except (TypeError, ValueError):
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

    if payload.quality_priority_keywords is not None:
        keywords = list(configured_quality_keywords(payload.quality_priority_keywords))
        if not keywords:
            raise HTTPException(status_code=422, detail="至少保留一个质量优先级关键词")
        encoded = json.dumps(keywords, ensure_ascii=False, separators=(",", ":"))
        existing["QUALITY_PRIORITY_KEYWORDS_JSON"] = encoded
        os.environ["QUALITY_PRIORITY_KEYWORDS_JSON"] = encoded

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
        "P115_STRM_SOURCE_ROOT",
        "P115_STRM_INCREMENTAL_CRON",
        "P115_REQUEST_TIMEOUT_SECONDS",
        "P115_MAX_SHARE_FILES",
        "QUARK_COOKIE",
        "QUARK_REQUEST_TIMEOUT_SECONDS",
        "QUARK_ROOT_PATH",
        "QUARK_STAGING_PATH",
        "QUARK_STRM_SOURCE_ROOT",
        "QUARK_STRM_INCREMENTAL_CRON",
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
        "QUARK_CATEGORY_PATHS_JSON",
        "MEDIA_FOLDER_NAMING_RULE",
        "SEASON_FOLDER_NAMING_RULE",
        "MOVIE_NAMING_RULE",
        "EPISODE_NAMING_RULE",
        "QUALITY_PRIORITY_KEYWORDS_JSON",
        "SEASON_SUBDIRECTORY_ENABLED",
        "STRM_OUTPUT_ROOT",
        "STRM_PLAYBACK_BASE_URL",
        "STRM_LIBRARY_ROOT_ID",
        "P115_STRM_ENABLED",
        "P115_STRM_SCRAPE_ENABLED",
        "QUARK_STRM_ENABLED",
        "QUARK_STRM_SCRAPE_ENABLED",
        "EMBY_LIBRARY_REFRESH_ENABLED",
        "EMBY_DELETION_AUTO_CONFIRM",
        "EMBY_DELETION_MODE",
        "EMBY_STRM_LIBRARY_ROOT",
        "EMBY_LIBRARY_ID",
        "STRM_VIDEO_EXTENSIONS_JSON",
        "STRM_EXCLUDED_NAME_TOKENS_JSON",
        "STRM_MIN_FILE_SIZE_MB",
        "OPENLIST_ENABLED",
        "OPENLIST_AUTO_SYNC",
        "OPENLIST_AUTO_SYNC_DIRECTION",
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
        "TELEGRAM_CHANNEL_SOURCE_ENABLED",
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
        "INTERACTION_CLOUD_PROVIDERS",
        "DIRECT_DOWNLOAD_PROVIDER",
        "DIRECT_DOWNLOAD_SAVE_PATH",
        "DB_PATH",
        "STATIC_DIR",
    ]
    atomic_write_env(env_path, existing, ordered)
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
    settings = _exportable_config_values()
    return {
        "format": CONFIG_EXPORT_FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings,
        "task_data": _export_task_data(),
    }


@router.post("/import")
def import_config(payload: ConfigImport):
    with env_file_lock():
        return _import_config(payload)


def _import_config(payload: ConfigImport):
    if payload.format != CONFIG_EXPORT_FORMAT:
        raise HTTPException(status_code=422, detail="不是 MediaIndex 导出的配置文件")
    if not payload.settings and payload.task_data is None:
        raise HTTPException(status_code=422, detail="配置文件中没有可导入的设置")
    invalid = [
        key
        for key, value in payload.settings.items()
        if key not in CONFIG_IMPORT_ALLOWED
        or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
        or not isinstance(value, str)
        or "\n" in value
        or "\r" in value
    ]
    if invalid:
        raise HTTPException(status_code=422, detail="配置文件格式无效")
    previous = _read_config_values()
    values = {
        **{key: value for key, value in previous.items() if key in CONFIG_EXPORT_EXCLUDED},
        **{key: value for key, value in payload.settings.items() if key not in CONFIG_EXPORT_EXCLUDED},
    }
    if payload.task_data is not None:
        _prepare_task_data(payload.task_data)
    env_path = _config_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_env(env_path, values)
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
    return {"ok": True, "message": "已覆盖导入可迁移设置和任务；当前部署登录、会话密钥与路径保持不变"}


def _exportable_config_values() -> dict[str, str]:
    """Export persisted settings plus safe Compose-provided settings."""
    values = _read_config_values()
    for field_name in Settings.model_fields:
        key = field_name.upper()
        if key in CONFIG_EXPORT_EXCLUDED or key in values:
            continue
        value = os.getenv(key)
        if value is not None and value.strip():
            values[key] = value.strip()
    return {key: value for key, value in values.items() if key not in CONFIG_EXPORT_EXCLUDED}


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
    wishlist, tracking = _prepare_task_data(task_data)

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


def _prepare_task_data(task_data: ConfigTaskBackup):
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

    return wishlist, tracking


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


def _json_string_list(raw: str, fallback: list[str]) -> list[str]:
    try:
        values = json.loads(raw) if str(raw or "").strip() else fallback
    except (TypeError, ValueError):
        values = fallback
    if not isinstance(values, list):
        return list(fallback)
    return [str(value).strip() for value in values if str(value).strip()] or list(fallback)


def _safe_strm_extensions(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        suffix = str(value).strip().casefold()
        if suffix and not suffix.startswith("."):
            suffix = f".{suffix}"
        if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
            raise HTTPException(status_code=422, detail="STRM 视频扩展名格式无效")
        if suffix not in normalized:
            normalized.append(suffix)
    if not normalized or len(normalized) > 40:
        raise HTTPException(status_code=422, detail="STRM 视频扩展名数量必须在 1-40 个之间")
    return normalized


def _safe_strm_tokens(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        token = str(value).strip().casefold()
        if not token or len(token) > 80 or any(char in token for char in "\r\n\x00"):
            raise HTTPException(status_code=422, detail="STRM 排除关键词格式无效")
        if token not in normalized:
            normalized.append(token)
    if len(normalized) > 100:
        raise HTTPException(status_code=422, detail="STRM 排除关键词最多 100 个")
    return normalized


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


@router.post("/test-telegram-bot")
def test_telegram_bot():
    settings = get_settings()
    token = str(settings.telegram_bot_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="请先保存 Bot Token")
    if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{20,}", token):
        raise HTTPException(status_code=400, detail="已保存的 Bot Token 格式无效，请重新填写 BotFather 提供的完整 Token")
    host = validate_http_origin(str(settings.telegram_api_host or "https://api.telegram.org"), "TELEGRAM_API_HOST")
    request = urllib.request.Request(f"{host}/bot{token}/getMe", headers={"Accept": "application/json"}, method="GET")
    try:
        with open_url(request, timeout=15) as response:
            payload = json.loads(response.read(256_000).decode("utf-8"))
        result = payload.get("result") if isinstance(payload, dict) else None
        if not payload.get("ok") or not isinstance(result, dict):
            raise RuntimeError("Telegram 未确认该 Bot")
        username = str(result.get("username") or "").strip()
        return {"ok": True, "message": f"Bot 连接正常{f'：@{username}' if username else ''}"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bot 连接失败：{type(exc).__name__}") from exc


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
        # This endpoint verifies the selected native 115 mode. OpenList is an
        # optional compatibility bridge, but reporting its mount as a native
        # 115 success would hide an expired Open token from the user and from
        # tracking diagnostics.
        return {
            "ok": False,
            "message": str(exc),
            "native_ok": False,
            "relogin_required": "重新扫码" in str(exc) or "授权已失效" in str(exc),
        }
    return {
        "ok": True,
        "message": "115 Cookie、目录读取与离线下载权限正常" if valid_p115_cookie(settings.p115_cookie) else "115 Open 目录读取与离线下载权限正常",
        "root_item_count": len(root_items),
    }


@router.post("/test-quark")
def test_quark():
    """Verify only authenticated read operations; it never changes Quark data."""
    settings = get_settings()
    if not valid_quark_cookie(str(getattr(settings, "quark_cookie", ""))):
        raise HTTPException(status_code=422, detail="请先保存有效的夸克 Cookie")
    try:
        client = QuarkClient(settings)
        root_items = client.list_root()
        try:
            account = client.account()
        except QuarkError:
            account = None
    except QuarkError as exc:
        return {"ok": False, "message": str(exc)}
    return {
        "ok": True,
        "message": "夸克 Cookie 与根目录读取正常（未修改网盘文件）",
        "account": {"user_id": account.user_id, "nickname": account.nickname} if account else None,
        "root_item_count": len(root_items),
    }


@router.post("/quark/qr/start")
def start_quark_qr_login():
    """Create a short-lived QR session without changing a cloud file."""
    try:
        session = _quark_login.start()
    except QuarkError as exc:
        return {"ok": False, "message": str(exc)}
    return {
        "ok": True,
        "session_id": session.session_id,
        "qr_url": session.qr_url,
        "expires_in_seconds": max(0, int(session.expires_at - time.monotonic())),
    }


@router.post("/quark/qr/poll")
def poll_quark_qr_login(payload: QuarkQrPollRequest):
    """Persist a scanned Cookie locally, while never returning it to the browser."""
    try:
        result = _quark_login.poll(payload.session_id)
    except QuarkError as exc:
        return {"ok": False, "status": "failed", "message": str(exc)}
    if result.status == "success":
        update_config(ConfigUpdate(quark_cookie=result.cookie))
        return {"ok": True, "status": "success", "message": "夸克扫码授权已保存；尚未修改任何网盘文件"}
    if result.status == "waiting":
        return {"ok": True, "status": "waiting", "message": "等待扫码确认"}
    if result.status == "expired":
        return {"ok": False, "status": "expired", "message": "扫码会话已过期，请重新开始"}
    return {"ok": False, "status": "failed", "message": "夸克扫码授权未完成"}


@router.post("/p115/open/qr/start")
def start_p115_open_qr_login():
    """Create an official 115 Open device-code session without touching files."""
    try:
        session = _p115_login.start()
    except P115Error as exc:
        return {"ok": False, "message": str(exc)}
    return {
        "ok": True,
        "session_id": session.session_id,
        "qr_url": session.qr_url,
        "expires_in_seconds": max(0, int(session.expires_at - time.monotonic())),
    }


@router.post("/p115/open/qr/poll")
def poll_p115_open_qr_login(payload: P115QrPollRequest):
    """Persist Open tokens server-side and never return them to the browser."""
    try:
        result = _p115_login.poll(payload.session_id)
    except P115Error as exc:
        return {"ok": False, "status": "failed", "message": str(exc)}
    if result.status == "success":
        update_config(ConfigUpdate(
            p115_open_access_token=result.access_token,
            p115_open_refresh_token=result.refresh_token,
            p115_auth_mode="open",
        ))
        return {"ok": True, "status": "success", "message": "115 文件接口授权已保存；尚未修改任何网盘文件"}
    messages = {
        "waiting": "等待使用 115 App 扫码",
        "scanned": "已扫码，请在 115 App 中确认授权",
        "expired": "二维码已过期，请重新开始",
        "failed": "115 授权未完成",
    }
    return {"ok": result.status in {"waiting", "scanned"}, "status": result.status, "message": messages.get(result.status, "115 授权未完成")}


@router.post("/quark/share/inspect")
def inspect_quark_share(payload: QuarkShareInspectionRequest):
    """Read and classify a Quark share without saving, renaming, or deleting it."""
    settings = get_settings()
    if not valid_quark_cookie(str(getattr(settings, "quark_cookie", ""))):
        raise HTTPException(status_code=422, detail="请先连接夸克账号")
    try:
        snapshot = QuarkClient(settings).inspect_share(payload.share_url)
    except QuarkError as exc:
        return {"ok": False, "message": str(exc)}
    video_extensions = {".mkv", ".mp4", ".avi", ".mov", ".m2ts", ".ts", ".wmv", ".flv", ".webm"}
    video_files = [item for item in snapshot.files if not item.is_dir and Path(item.name).suffix.lower() in video_extensions]
    return {
        "ok": True,
        "message": "夸克分享读取正常，尚未向网盘写入任何文件",
        "title": snapshot.title,
        "file_count": len(snapshot.files),
        "directory_count": sum(1 for item in snapshot.files if item.is_dir),
        "video_count": len(video_files),
        "files": [
            {"name": item.name, "size": item.size, "is_dir": item.is_dir, "is_video": item in video_files}
            for item in snapshot.files[:200]
        ],
        "truncated": len(snapshot.files) > 200,
    }


@router.post("/import-p115-from-openlist")
def import_p115_from_openlist():
    with env_file_lock():
        return _import_p115_from_openlist()


def _import_p115_from_openlist():
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
    atomic_write_env(env_path, existing)
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
    with env_file_lock():
        return _clear_p115_open()


def _clear_p115_open():
    env_path = _config_path()
    existing = _read_config_values()
    existing.pop("P115_OPEN_ACCESS_TOKEN", None)
    existing.pop("P115_OPEN_REFRESH_TOKEN", None)
    has_cookie = valid_p115_cookie(existing.get("P115_COOKIE", ""))
    if has_cookie:
        existing["P115_AUTH_MODE"] = "cookie"
    else:
        existing.pop("P115_AUTH_MODE", None)
    atomic_write_env(env_path, existing)
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
    if provider not in {"qas", "quark", "p115"}:
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
    elif provider == "quark":
        try:
            client = QuarkClient(get_settings())
            fid = client.directory_id(path)
            if not fid:
                raise QuarkError("目标目录不存在")
            directories = [
                {"name": item.name, "is_dir": True}
                for item in client.list_directory(fid)
                if item.is_dir and item.name
            ]
        except QuarkError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"夸克目录读取失败：{type(exc).__name__}") from exc
    else:
        try:
            response = QasClient().savepath_detail(path)
            directories = _qas_directories_from_response(response)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"QAS 目录读取失败：{type(exc).__name__}") from exc
    directories.sort(key=lambda item: item["name"])
    return {"ok": True, "provider": provider, "path": path, "directories": directories}


@router.post("/browse-local-path")
def browse_local_path(payload: LocalBrowseRequest):
    settings = get_settings()
    configured_root = Path(os.getenv("STRM_BROWSE_ROOT", "/strm")).expanduser()
    if not configured_root.is_dir():
        current = Path(settings.strm_output_root).expanduser() if settings.strm_output_root else configured_root
        configured_root = current if current.is_dir() else current.parent
    try:
        allowed_root = configured_root.resolve(strict=True)
        requested = Path(payload.path).expanduser() if payload.path.strip() else allowed_root
        selected = requested.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail="STRM 输出目录不存在或不可访问") from exc
    if not selected.is_dir() or (selected != allowed_root and allowed_root not in selected.parents):
        raise HTTPException(status_code=422, detail="只能选择 STRM 挂载目录及其子目录")
    directories: list[dict[str, str | bool]] = []
    try:
        for child in selected.iterdir():
            try:
                resolved = child.resolve(strict=True)
                if child.is_dir() and not child.is_symlink() and (resolved == allowed_root or allowed_root in resolved.parents):
                    directories.append({"name": child.name, "is_dir": True})
            except OSError:
                continue
    except OSError as exc:
        raise HTTPException(status_code=502, detail="STRM 输出目录读取失败") from exc
    directories.sort(key=lambda item: str(item["name"]).casefold())
    return {"ok": True, "root": str(allowed_root), "path": str(selected), "directories": directories}


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
