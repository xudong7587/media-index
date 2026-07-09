from functools import lru_cache
import json
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class PathRoots(BaseModel):
    cloud: str = "/strm"
    local: str = "/downloads"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Media Index"
    app_env: str = "production"
    auth_secret: str = ""
    media_user: str = "admin"
    media_pass: str = ""

    tmdb_api_key: str = ""
    qas_base_url: str = ""
    qas_token: str = ""
    pansou_url: str = ""
    pansou_token: str = ""

    cloud_save_path: str = "/strm"
    local_save_path: str = "/downloads"
    category_paths_json: str = '{"movie":"/movie","tv":"/tv","variety":"/tv"}'
    db_path: str = "/app/data/media_index.db"
    static_dir: str = "/app/frontend"
    cache_dir: str = "/app/data/cache"
    tmdb_discover_cache_ttl_seconds: int = 21600
    tmdb_details_cache_ttl_seconds: int = 86400
    tmdb_genres_cache_ttl_seconds: int = 604800
    wishlist_cron_enabled: bool = False
    wishlist_cron_schedule: str = "0 */6 * * *"

    cookie_name: str = "media_index_session"
    session_ttl_seconds: int = 604800

    def roots(self) -> PathRoots:
        return PathRoots(cloud=self.cloud_save_path.rstrip("/"), local=self.local_save_path.rstrip("/"))

    def category_paths(self) -> dict[str, str]:
        defaults = {"movie": "/movie", "tv": "/tv", "variety": "/tv"}
        try:
            parsed = json.loads(self.category_paths_json)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if isinstance(key, str) and isinstance(value, str) and value.strip():
                        defaults[key.strip()] = normalize_category_path(value)
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
    s = Settings()
    s.ensure_data_dir()
    return s
