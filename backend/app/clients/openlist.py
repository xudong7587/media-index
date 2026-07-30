from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from app.core.config import get_settings


class OpenListError(RuntimeError):
    pass


class OpenListClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.openlist_url).strip().rstrip("/")
        self.token = (token or settings.openlist_token).strip()
        if not self.base_url or not self.token:
            raise OpenListError("OpenList 地址和 Token 尚未配置")

    def _post(self, path: str, payload: dict) -> dict:
        request = Request(
            urljoin(f"{self.base_url}/", path.lstrip("/")),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": self.token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise OpenListError(f"OpenList 请求失败：{type(exc).__name__}") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise OpenListError("OpenList 返回格式无效") from exc
        if not isinstance(body, dict) or body.get("code", 200) not in (200, 0):
            raise OpenListError(str(body.get("message") or "OpenList 操作失败") if isinstance(body, dict) else "OpenList 操作失败")
        return body

    def _get(self, path: str, params: dict[str, object] | None = None) -> dict:
        suffix = f"?{urlencode(params)}" if params else ""
        request = Request(
            urljoin(f"{self.base_url}/", path.lstrip("/")) + suffix,
            headers={"Authorization": self.token},
            method="GET",
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise OpenListError(f"OpenList 请求失败：{type(exc).__name__}") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise OpenListError("OpenList 返回格式无效") from exc
        if not isinstance(body, dict) or body.get("code", 200) not in (200, 0):
            raise OpenListError(str(body.get("message") or "OpenList 操作失败") if isinstance(body, dict) else "OpenList 操作失败")
        return body

    def p115_auth(self) -> dict[str, str]:
        """Read one configured 115 storage without exposing its credentials to the browser."""
        body = self._get("/api/admin/storage/list", {"page": 1, "per_page": 100})
        data = body.get("data") if isinstance(body, dict) else {}
        storages = data.get("content") or data.get("list") or [] if isinstance(data, dict) else []
        cookie_storage: dict[str, str] | None = None
        open_storage: dict[str, str] | None = None
        for storage in storages if isinstance(storages, list) else []:
            if not isinstance(storage, dict) or storage.get("disabled"):
                continue
            driver = str(storage.get("driver") or "").strip().casefold().replace("_", " ")
            raw_addition = storage.get("addition")
            try:
                addition = json.loads(raw_addition) if isinstance(raw_addition, str) else raw_addition
            except ValueError:
                continue
            if not isinstance(addition, dict):
                continue
            mount_path = str(storage.get("mount_path") or "").strip()
            cookie = str(addition.get("cookie") or "").strip()
            if driver == "115" and cookie:
                cookie_storage = {"mode": "cookie", "cookie": cookie, "mount_path": mount_path}
            access_token = str(addition.get("access_token") or "").strip()
            refresh_token = str(addition.get("refresh_token") or "").strip()
            if driver in {"115 open", "115open"} and access_token and refresh_token:
                open_storage = {
                    "mode": "open",
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "mount_path": mount_path,
                }
        if cookie_storage:
            return cookie_storage
        if open_storage:
            return open_storage
        raise OpenListError("未找到可用的 115 或 115 Open 存储；请先在 OpenList 中完成挂载")

    def list_directory(self, path: str) -> dict:
        return self._post("/api/fs/list", {"path": path, "page": 1, "per_page": 100, "refresh": True})

    def list_directories(self, path: str) -> list[dict]:
        directories = []
        for item in self._items(self.list_directory(path)):
            if item.get("is_dir") or item.get("type") in {1, "1", "folder", "dir"}:
                directories.append({"name": str(item["name"]).strip(), "is_dir": True})
        return directories

    def copy(self, source_dir: str, target_dir: str, names: list[str], *, overwrite: bool = False) -> dict:
        if not names:
            raise OpenListError("没有可同步的文件")
        return self._post(
            "/api/fs/copy",
            {"src_dir": source_dir, "dst_dir": target_dir, "names": names, "overwrite": overwrite},
        )

    def mkdir(self, path: str) -> dict:
        return self._post("/api/fs/mkdir", {"path": path})

    def list_entries(self, path: str) -> list[dict]:
        entries = []
        for item in self._items(self.list_directory(path)):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            is_dir = bool(item.get("is_dir") or item.get("type") in {1, "1", "folder", "dir"})
            modified = (
                item.get("modified")
                or item.get("updated_at")
                or item.get("mtime")
                or item.get("time")
                or item.get("created")
                or ""
            )
            entries.append({"name": name, "is_dir": is_dir, "size": item.get("size"), "modified": str(modified)})
        return entries

    def test(self, qas_path: str, p115_path: str) -> dict:
        available_mounts = self._available_mounts()
        for label, path in (("夸克", qas_path), ("115", p115_path)):
            try:
                self.list_directory(path)
            except OpenListError as exc:
                detail = str(exc)
                if "storage not found" in detail.lower() and available_mounts:
                    mounts = "、".join(available_mounts)
                    detail = f"{detail}；当前可用挂载点：{mounts}。媒体库目录需填写完整路径，例如 /夸克/strm。"
                raise OpenListError(f"{label}媒体库目录检查失败：{detail}") from exc
        return {"ok": True, "message": "OpenList 连接成功，两个媒体库目录均可读取"}

    def _available_mounts(self) -> list[str]:
        try:
            return [
                str(item.get("name") or "").strip()
                for item in self._items(self.list_directory("/"))
                if str(item.get("name") or "").strip()
            ]
        except OpenListError:
            return []

    @staticmethod
    def _items(body: dict) -> list[dict]:
        data = body.get("data") if isinstance(body, dict) else {}
        if not isinstance(data, dict):
            return []
        items = data.get("content") or data.get("list") or []
        return [item for item in items if isinstance(item, dict) and str(item.get("name") or "").strip()]

    def sync_tree(self, source_root: str, target_root: str, *, max_items: int = 500) -> dict:
        copied = 0
        visited = 0

        def walk(source_dir: str, target_dir: str) -> None:
            nonlocal copied, visited
            if visited >= max_items:
                return
            source_items = self._items(self.list_directory(source_dir))
            target_names = {str(item.get("name") or "") for item in self._items(self.list_directory(target_dir))}
            for item in source_items:
                if visited >= max_items:
                    return
                name = str(item.get("name") or "").strip()
                visited += 1
                is_dir = bool(item.get("is_dir") or item.get("type") in {1, "1", "folder", "dir"})
                source_path = f"{source_dir.rstrip('/')}/{name}"
                target_path = f"{target_dir.rstrip('/')}/{name}"
                if name not in target_names:
                    self.copy(source_dir, target_dir, [name])
                    copied += 1
                    continue
                if is_dir:
                    walk(source_path, target_path)

        walk(source_root, target_root)
        return {"copied": copied, "scanned": visited, "limited": visited >= max_items}
