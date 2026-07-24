from functools import lru_cache
import json
import os
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class PathRoots(BaseModel):
    cloud: str = "/strm"
    local: str = "/下载_未整理"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "Media Index"
    app_env: str = "production"
    auth_secret: str = ""
    media_user: str = "admin"
    media_pass: str = ""

    tmdb_api_key: str = ""
    qas_base_url: str = ""
    qas_token: str = ""
    moviepilot_base_url: str = ""
    moviepilot_api_token: str = ""
    moviepilot_115_plugin_id: str = "P115StrmHelper"
    moviepilot_115_request_timeout_seconds: int = 180
    moviepilot_115_confirmation_timeout_minutes: int = 120
    p115_cookie: str = ""
    p115_root_path: str = "/strm"
    p115_staging_path: str = "/.media-index-staging"
    p115_local_path: str = "/downloads"
    p115_request_timeout_seconds: int = 30
    p115_max_share_files: int = 5000
    enabled_cloud_providers: str = "qas"
    default_cloud_provider: str = "qas"
    pansou_url: str = ""
    pansou_token: str = ""
    pansou_concurrency: int = 32
    pansou_search_timeout_seconds: int = 45
    proxy_url: str = ""

    cloud_save_path: str = "/strm"
    local_save_path: str = "/下载_未整理"
    category_paths_json: str = '{"movie":"/movie","tv":"/tv","variety":"/tv","concert":"/05演唱会","documentary":"/06纪录片","anime":"/12动漫"}'
    qas_save_path: str = ""
    qas_category_paths_json: str = ""
    p115_category_paths_json: str = ""
    db_path: str = "/app/data/media_index.db"
    static_dir: str = "/app/frontend"
    cache_dir: str = "/app/data/cache"
    tmdb_discover_cache_ttl_seconds: int = 21600
    tmdb_details_cache_ttl_seconds: int = 86400
    tmdb_tracking_cache_ttl_seconds: int = 3600
    tmdb_genres_cache_ttl_seconds: int = 604800
    resource_probe_cache_ttl_seconds: int = 3600
    wishlist_scheduler_enabled: bool = True
    wishlist_poll_minutes: int = 5
    wishlist_default_check_hour: int = 9
    tracking_scheduler_enabled: bool = True
    tracking_poll_minutes: int = 5
    tracking_check_hour: int = 10
    tracking_max_retries: int = 5
    qas_confirmation_timeout_minutes: int = 120
    tracking_timezone: str = "Asia/Shanghai"
    public_base_url: str = ""
    notification_external_enabled: bool = False
    notification_enabled_at: str = ""
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_host: str = "https://api.telegram.org"
    wecom_enabled: bool = False
    wecom_key: str = ""
    wecom_origin: str = "https://qyapi.weixin.qq.com"
    wecom_app_enabled: bool = False
    wecom_corp_id: str = ""
    wecom_app_secret: str = ""
    wecom_app_agent_id: int = 0
    wecom_app_to_user: str = "@all"
    wecom_app_to_party: str = ""
    wecom_app_to_tag: str = ""
    wecom_callback_enabled: bool = False
    wecom_callback_token: str = ""
    wecom_callback_aes_key: str = ""
    wecom_callback_allowed_users: str = ""

    cookie_name: str = "media_index_session"
    session_ttl_seconds: int = 604800
    cookie_secure: bool = False
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    def roots(self) -> PathRoots:
        return PathRoots(cloud=self.cloud_save_path.rstrip("/"), local=self.local_save_path.rstrip("/"))

    def enabled_provider_keys(self) -> tuple[str, ...]:
        supported = {"qas", "p115", "moviepilot_115"}
        values = tuple(
            dict.fromkeys(
                value.strip().lower()
                for value in self.enabled_cloud_providers.split(",")
                if value.strip().lower() in supported
            )
        )
        return values or ("qas",)

    def default_provider_key(self) -> str:
        value = self.default_cloud_provider.strip().lower() or "qas"
        enabled = self.enabled_provider_keys()
        return value if value in enabled else enabled[0]

    def category_paths(self) -> dict[str, str]:
        return self.provider_category_paths("qas")

    def provider_save_root(self, provider: str) -> str:
        if provider == "p115":
            return self.p115_root_path.rstrip("/")
        return (self.qas_save_path or self.cloud_save_path).rstrip("/")

    def provider_local_root(self, provider: str) -> str:
        if provider == "p115":
            return self.p115_local_path.rstrip("/")
        return self.local_save_path.rstrip("/")

    def provider_category_paths(self, provider: str) -> dict[str, str]:
        defaults = {
            "movie": "/movie",
            "tv": "/tv",
            "variety": "/tv",
            "concert": "/05演唱会",
            "documentary": "/06纪录片",
            "anime": "/12动漫",
        }
        encoded = (
            self.p115_category_paths_json
            if provider == "p115"
            else self.qas_category_paths_json or self.category_paths_json
        )
        try:
            parsed = json.loads(encoded)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if not isinstance(key, str) or not isinstance(value, str):
                        continue
                    clean_key = key.strip()
                    if not clean_key:
                        continue
                    if value.strip():
                        defaults[clean_key] = normalize_category_path(value)
                    else:
                        defaults.pop(clean_key, None)
        except Exception:
            pass
        return defaults

    def ensure_data_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


def normalize_category_path(value: str) -> str:
    path = value.strip()
    if not path:
        return ""
    return "/" + path.strip("/")


@lru_cache
def get_settings() -> Settings:
    s = Settings(_env_file=os.getenv("MEDIA_CONFIG_PATH", ".env"))
    s.ensure_data_dir()
    return s
