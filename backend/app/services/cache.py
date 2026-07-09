import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class FileCache:
    def __init__(self, namespace: str) -> None:
        settings = get_settings()
        self.root = Path(settings.cache_dir) / namespace
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str, ttl_seconds: int) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            if time.time() - path.stat().st_mtime > ttl_seconds:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        path = self._path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
