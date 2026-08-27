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
    p115_cloud_download_path: str = ""
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
    quark_cloud_download_path: str = ""
    quark_staging_path: str = "/.media-index-staging"
    quark_category_paths_json: str = ""
    # Cloud-download organizing is opt-in.  Keeping every default inert makes
    # upgrades safe for installations that already use these folders manually.
    cloud_download_organizer_enabled: bool = False
    # Per-provider switches supersede the legacy aggregate switch.  ``None``
    # deliberately distinguishes an upgraded installation (legacy fallback)
    # from a provider that the user explicitly disabled in the new UI.
    p115_cloud_download_organizer_enabled: bool | None = None
    quark_cloud_download_organizer_enabled: bool | None = None
    cloud_download_organizer_mode: str = "copy"
    # Existing v0.6.18 installations have no trigger field, so event remains
    # the conservative default.  Scheduled scans are restored only when the
    # user explicitly selects them.
    cloud_download_organizer_triggers_json: str = '["event"]'
    cloud_download_organizer_interval_minutes: int = 10
    cloud_download_organizer_stable_minutes: int = 10
    # Empty keeps pre-scope-mode installations fail closed.  Fresh example
    # configuration explicitly selects ``all``; legacy non-empty lists are
    # inferred as ``selected`` below.
    p115_cloud_download_organizer_scope_mode: str = ""
    quark_cloud_download_organizer_scope_mode: str = ""
    p115_cloud_download_organizer_directories_json: str = "[]"
    quark_cloud_download_organizer_directories_json: str = "[]"
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
    p115_strm_life_monitor_enabled: bool = False
    p115_strm_life_monitor_path: str = ""
    p115_strm_life_monitor_interval_seconds: int = 60
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
    mdc_webhook_enabled: bool = False
    mdc_webhook_token: str = ""
    mdc_webhook_provider: str = "p115"
    mdc_webhook_root_path: str = ""
    mdc_webhook_debounce_seconds: int = 30
    emby_library_refresh_enabled: bool = False
    emby_library_id: str = ""
    emby_cover_refresh_enabled: bool = False
    emby_cover_refresh_cron: str = "0 3 * * 1"
    # Kept for installations upgrading from 0.6.9 and earlier.  New writes
    # use the five-field cron expression above.
    emby_cover_refresh_hours: int = 168
    emby_cover_style: str = "collage"
    emby_cover_options_json: str = "{}"
    emby_cover_library_ids_json: str = "[]"
    emby_cover_library_options_json: str = "{}"
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
    resource_excluded_keywords_json: str = '["TC","TS","CAM","抢先","预览版","480p"]'
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
    interaction_shortcuts_json: str = '["strm_full","strm_incremental","strm_directory","tracking","wishlist","status","review"]'
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

    def provider_cloud_download_path(self, provider: str) -> str:
        if provider == "p115":
            configured = self.p115_cloud_download_path
        else:
            configured = self.quark_cloud_download_path
        if configured.strip():
            return configured.rstrip("/") or "/"
        legacy = self.direct_download_save_path.strip().rstrip("/")
        root = self.p115_root_path.rstrip("/") if provider == "p115" else self.quark_root_path.rstrip("/")
        if legacy and (legacy == root or legacy.startswith(f"{root}/")):
            return legacy
        return root or "/"

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

    def provider_cloud_download_organizer_directories(self, provider: str) -> tuple[str, ...]:
        encoded = (
            self.p115_cloud_download_organizer_directories_json
            if provider == "p115"
            else self.quark_cloud_download_organizer_directories_json
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

    def provider_cloud_download_organizer_scope_mode(self, provider: str) -> str:
        if provider not in {"p115", "quark"}:
            return "selected"
        configured = str(
            getattr(self, f"{provider}_cloud_download_organizer_scope_mode", "") or ""
        ).strip().lower()
        if configured in {"all", "selected"}:
            return configured
        # Upgrades from v0.6.15-v0.6.18 had only the directory list.  Preserve
        # that exact authorization rather than silently expanding it.  A
        # disabled provider with no legacy selection is a fresh setup from the
        # UI's perspective, where all direct children is the requested default.
        if self.provider_cloud_download_organizer_directories(provider):
            return "selected"
        explicit_enabled = getattr(self, f"{provider}_cloud_download_organizer_enabled", None)
        was_enabled = (
            bool(explicit_enabled)
            if explicit_enabled is not None
            else bool(self.cloud_download_organizer_enabled)
        )
        return "selected" if was_enabled else "all"

    def provider_cloud_download_organizer_enabled(self, provider: str) -> bool:
        if provider not in {"p115", "quark"}:
            return False
        configured = getattr(self, f"{provider}_cloud_download_organizer_enabled", None)
        if configured is not None:
            if not bool(configured):
                return False
            return (
                self.provider_cloud_download_organizer_scope_mode(provider) == "all"
                or bool(self.provider_cloud_download_organizer_directories(provider))
            )
        # Upgrade compatibility: a previously enabled aggregate switch
        # continues only for providers that already had an authorized direct-
        # child list, or that explicitly opted into the new all-scope mode.
        has_scope = (
            self.provider_cloud_download_organizer_scope_mode(provider) == "all"
            or bool(self.provider_cloud_download_organizer_directories(provider))
        )
        return bool(self.cloud_download_organizer_enabled) and has_scope

    def cloud_download_organizer_triggers(self) -> tuple[str, ...]:
        try:
            values = json.loads(self.cloud_download_organizer_triggers_json)
        except (TypeError, ValueError):
            return ("event",)
        if not isinstance(values, list):
            return ("event",)
        return tuple(
            dict.fromkeys(
                str(value).strip().lower()
                for value in values
                if str(value).strip().lower() in {"event", "scheduled"}
            )
        )

    def cloud_download_organizer_trigger_enabled(self, trigger: str) -> bool:
        return str(trigger or "").strip().lower() in self.cloud_download_organizer_triggers()

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
