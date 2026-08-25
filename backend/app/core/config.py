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
    tmdb_adult_content_enabled: bool = False
    qas_base_url: str = ""
    qas_token: str = ""
    moviepilot_base_url: str = ""
    moviepilot_api_token: str = ""
    moviepilot_115_plugin_id: str = "P115StrmHelper"
    moviepilot_115_request_timeout_seconds: int = 180
    moviepilot_115_confirmation_timeout_minutes: int = 120
    p115_cookie: str = ""
    p115_auth_mode: str = "cookie"
    p115_open_access_token: str = ""
    p115_open_refresh_token: str = ""
    p115_root_path: str = "/strm"
    p115_staging_path: str = "/.media-index-staging"
    p115_local_path: str = "/downloads"
    p115_request_timeout_seconds: int = 30
    p115_max_share_files: int = 5000
    # Native Quark can coexist with the legacy QAS adapter.  Both operate on
    # Quark share links, but only the former performs the cloud-side workflow
    # directly through the user's Quark account.
    quark_cookie: str = ""
    quark_request_timeout_seconds: int = 30
    quark_root_path: str = "/strm"
    quark_staging_path: str = "/.media-index-staging"
    quark_category_paths_json: str = ""
    # STRM generation is disabled until an explicit local/mounted output root
    # is configured.  It is intentionally separate from cloud path settings.
    strm_output_root: str = ""
    p115_strm_source_root: str = "/strm"
    quark_strm_source_root: str = "/strm"
    p115_strm_included_directories_json: str = "[]"
    quark_strm_included_directories_json: str = "[]"
    strm_playback_base_url: str = ""
    strm_library_root_id: str = "default"
    p115_strm_enabled: bool = False
    p115_strm_incremental_cron: str = ""
    p115_strm_scrape_enabled: bool = False
    quark_strm_enabled: bool = False
    quark_strm_incremental_cron: str = ""
    quark_strm_scrape_enabled: bool = False
    strm_video_extensions_json: str = '[".mkv",".mp4",".m4v",".avi",".mov",".ts",".wmv",".webm",".iso"]'
    strm_excluded_name_tokens_json: str = '["trailer","sample","preview","花絮","预告","广告"]'
    strm_min_file_size_mb: int = 0
    emby_base_url: str = ""
    emby_api_key: str = ""
    emby_proxy_port: int = 8097
    emby_deletion_webhook_token: str = ""
    emby_strm_library_root: str = ""
    emby_deletion_auto_confirm: bool = False
    emby_deletion_mode: str = "trash"
    emby_library_refresh_enabled: bool = False
    emby_library_id: str = ""
    emby_cover_refresh_enabled: bool = False
    emby_cover_refresh_hours: int = 168
    emby_cover_style: str = "collage"
    enabled_cloud_providers: str = "quark"
    default_cloud_provider: str = "quark"
    pansou_url: str = ""
    pansou_token: str = ""
    pansou_concurrency: int = 32
    pansou_search_timeout_seconds: int = 45
    # PanSou can return a partial result set while its asynchronous sources are
    # still running. Keep the retry budget deliberately small: this improves
    # recall without turning a normal card interaction into an unbounded wait.
    pansou_result_poll_attempts: int = 4
    pansou_result_poll_seconds: float = 2.5
    proxy_url: str = ""

    cloud_save_path: str = "/strm"
    local_save_path: str = "/下载_未整理"
    category_paths_json: str = '{"movie":"/movie","tv":"/tv","variety":"/tv","concert":"/05演唱会","documentary":"/06纪录片","anime":"/12动漫"}'
    qas_save_path: str = ""
    qas_category_paths_json: str = ""
    p115_category_paths_json: str = ""
    media_folder_naming_rule: str = "{title} ({year})"
    season_folder_naming_rule: str = "Season {season}"
    movie_naming_rule: str = "{title}.{year}"
    episode_naming_rule: str = "{title}.{year}.S{season:02d}E{episode:02d}"
    quality_priority_keywords_json: str = '["4K 原盘","4K DV","4K HDR","4K SDR","4K","1080P HDR","1080P","720P","WEB-DL","WEBRip","SDR"]'
    season_subdirectory_enabled: bool = False
    openlist_enabled: bool = False
    openlist_auto_sync: bool = False
    openlist_auto_sync_direction: str = "bidirectional"
    openlist_url: str = ""
    openlist_token: str = ""
    openlist_qas_library_path: str = "/夸克"
    openlist_p115_library_path: str = "/115"
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
    tracking_check_time: str = "10:00"
    tracking_check_hour: int = 10
    tracking_retry_interval_minutes: int = 120
    tracking_max_retries: int = 5
    qas_confirmation_timeout_minutes: int = 120
    tracking_timezone: str = "Asia/Shanghai"
    public_base_url: str = ""
    wecom_callback_url: str = ""
    notification_external_enabled: bool = False
    notification_event_types: str = "transfer_success,library,review,no_resource,failure,playback"
    notification_enabled_at: str = ""
    telegram_enabled: bool = False
    telegram_channel_source_enabled: bool = False
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
    direct_download_enabled: bool = False
    interaction_cloud_providers: str = "quark,p115"
    direct_download_provider: str = "p115"
    direct_download_save_path: str = ""

    cookie_name: str = "media_index_session"
    session_ttl_seconds: int = 604800
    cookie_secure: bool = False
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    def roots(self) -> PathRoots:
        return PathRoots(cloud=self.cloud_save_path.rstrip("/"), local=self.local_save_path.rstrip("/"))

    def enabled_provider_keys(self) -> tuple[str, ...]:
        # QAS is retained only to read historical jobs and old environment
        # files. New configuration/UI exposes native Quark instead.
        supported = {"qas", "quark", "p115", "moviepilot_115"}
        values = tuple(
            dict.fromkeys(
                value.strip().lower()
                for value in self.enabled_cloud_providers.split(",")
                if value.strip().lower() in supported
            )
        )
        return values or ("quark",)

    def default_provider_key(self) -> str:
        value = self.default_cloud_provider.strip().lower() or "quark"
        enabled = self.enabled_provider_keys()
        return value if value in enabled else enabled[0]

    def interaction_provider_keys(self) -> tuple[str, ...]:
        supported = {"quark", "p115"}
        selected = tuple(
            dict.fromkeys(
                value.strip().lower()
                for value in self.interaction_cloud_providers.split(",")
                if value.strip().lower() in supported
            )
        )
        enabled = set(self.enabled_provider_keys())
        available = tuple(provider for provider in selected if provider in enabled)
        return available or tuple(provider for provider in ("quark", "p115") if provider in enabled) or ("quark",)

    def category_paths(self) -> dict[str, str]:
        return self._merge_category_paths(self._default_category_paths(), self.category_paths_json)

    def provider_save_root(self, provider: str) -> str:
        if provider == "p115":
            return self.p115_root_path.rstrip("/")
        if provider == "quark":
            return self.quark_root_path.rstrip("/")
        return (self.qas_save_path or self.cloud_save_path).rstrip("/")

    def provider_local_root(self, provider: str) -> str:
        if provider == "p115":
            return self.p115_local_path.rstrip("/")
        return self.local_save_path.rstrip("/")

    def provider_strm_source_root(self, provider: str) -> str:
        if provider == "p115":
            return self.p115_strm_source_root.rstrip("/") or "/"
        if provider == "quark":
            return self.quark_strm_source_root.rstrip("/") or "/"
        return "/"

    def provider_strm_included_directories(self, provider: str) -> tuple[str, ...]:
        encoded = (
            self.p115_strm_included_directories_json
            if provider == "p115"
            else self.quark_strm_included_directories_json
            if provider == "quark"
            else "[]"
        )
        try:
            values = json.loads(encoded)
        except (TypeError, ValueError):
            values = []
        if not isinstance(values, list):
            return ()
        return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

    def provider_category_paths(self, provider: str) -> dict[str, str]:
        defaults = self.category_paths()
        encoded = (
            self.p115_category_paths_json
            if provider == "p115"
            else self.quark_category_paths_json
            if provider == "quark"
            else self.qas_category_paths_json
        )
        return self._merge_category_paths(defaults, encoded)

    @staticmethod
    def _default_category_paths() -> dict[str, str]:
        return {
            "movie": "/movie",
            "tv": "/tv",
            "variety": "/tv",
            "concert": "/05演唱会",
            "documentary": "/06纪录片",
            "anime": "/12动漫",
        }

    @staticmethod
    def _merge_category_paths(defaults: dict[str, str], encoded: str) -> dict[str, str]:
        merged = dict(defaults)
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
                        merged[clean_key] = normalize_category_path(value)
                    else:
                        merged.pop(clean_key, None)
        except Exception:
            pass
        return merged

    def ensure_data_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


def normalize_category_path(value: str) -> str:
    path = value.strip()
    if not path:
        return ""
    return "/" + path.strip("/")


@lru_cache
def get_settings() -> Settings:
    config_path = Path(os.getenv("MEDIA_CONFIG_PATH", ".env"))
    s = Settings(_env_file=config_path)
    # PANSOU_URL is provided as a Compose default, but the settings page
    # persists the user override in the runtime env file. Pydantic settings
    # normally give process environment variables precedence over that file,
    # which made a Compose default impossible to replace from the UI.
    if config_path.is_file():
        for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("PANSOU_URL="):
                s.pansou_url = line.split("=", 1)[1].strip()
                break
    s.ensure_data_dir()
    return s
