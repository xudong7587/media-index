from __future__ import annotations

import json
import concurrent.futures
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request

from app.clients.http import open_url
from app.core.config import get_settings


class OpenListError(RuntimeError):
    pass


def _int_or_zero(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


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
            with open_url(request, timeout=30, use_proxy=False) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise OpenListError(f"OpenList 请求失败：{type(exc).__name__}") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise OpenListError("OpenList 返回格式无效") from exc
        if not isinstance(body, dict) or body.get("code", 200) not in (200, 0):
            raise OpenListError(str(body.get("message") or "OpenList 操作失败") if isinstance(body, dict) else "OpenList 操作失败")
        return body

    def _get(self, path: str, params: dict[str, object] | None = None, *, timeout: int = 30) -> dict:
        suffix = f"?{urlencode(params)}" if params else ""
        request = Request(
            urljoin(f"{self.base_url}/", path.lstrip("/")) + suffix,
            headers={"Authorization": self.token},
            method="GET",
        )
        try:
            with open_url(request, timeout=timeout, use_proxy=False) as response:
                body = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
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

    def p115_storage_path(self, path: str) -> str:
        """Translate an original 115 path into the matching OpenList storage mount path."""
        mount_path = str(self.p115_auth().get("mount_path") or "").strip()
        if not mount_path.startswith("/"):
            raise OpenListError("115 存储未配置有效的 OpenList 挂载路径")
        normalized = "/" + "/".join(part for part in str(path or "").replace("\\", "/").split("/") if part)
        return "/" + "/".join(part for part in f"{mount_path}/{normalized.lstrip('/')}".split("/") if part)

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

    def offline_download_115(self, path: str, url: str) -> dict:
        """Submit a link to the 115 Cloud offline-download tool in the selected OpenList directory."""
        return self._post(
            "/api/fs/other",
            {
                "path": path,
                "method": "offline_download",
                "data": {"tool": "115 Cloud", "urls": url},
            },
        )

    def copy_tasks(self, *, done_limit: int = 50) -> list[dict[str, object]]:
        """Read OpenList's own copy queue with the configured bearer token."""
        tasks: list[dict[str, object]] = []
        endpoints = ((False, "/api/task/copy/undone"), (True, "/api/task/copy/done"))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            bodies = list(executor.map(lambda item: self._get(item[1], timeout=5), endpoints))
        for (completed, _endpoint), body in zip(endpoints, bodies):
            data = body.get("data") if isinstance(body, dict) else []
            rows = data if isinstance(data, list) else []
            if completed and done_limit > 0:
                rows = rows[:done_limit]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                progress = row.get("progress", 100 if completed else 0)
                try:
                    progress_value = max(0.0, min(float(progress), 100.0))
                except (TypeError, ValueError):
                    progress_value = 100.0 if completed else 0.0
                error = str(row.get("error") or "").strip()
                raw_state = str(row.get("state") or row.get("status") or "").strip().lower()
                state = (
                    "failed" if error or raw_state in {"failed", "error"}
                    else "done" if completed or raw_state in {"succeeded", "success", "done", "completed"}
                    else "running"
                )
                tasks.append({
                    "id": str(row.get("id") or ""),
                    "name": str(row.get("name") or "OpenList 复制任务"),
                    "state": state,
                    "status": str(row.get("status") or ""),
                    "progress": progress_value,
                    "total_bytes": _int_or_zero(row.get("total_bytes")),
                    "error": error,
                    "start_time": row.get("start_time"),
                    "end_time": row.get("end_time"),
                })
        return tasks

    def clear_finished_copy_tasks(self) -> None:
        """Remove completed, failed, and canceled copy tasks from OpenList's queue."""
        self._post("/api/task/copy/clear_done", {})

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
