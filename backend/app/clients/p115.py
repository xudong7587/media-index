from __future__ import annotations

import json
import os
import random
import re
import shutil
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.env_file import atomic_write_env, env_file_lock


_P115_SDK_ENV_LOCK = threading.RLock()


class P115Error(RuntimeError):
    """A redacted, user-safe 115 API error."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class P115ShareRef:
    share_code: str
    receive_code: str = ""


@dataclass(frozen=True)
class P115File:
    file_id: str
    parent_id: str
    name: str
    path: str
    size: int = 0
    is_dir: bool = False
    pick_code: str = ""


@dataclass(frozen=True)
class P115ShareSnapshot:
    share: P115ShareRef
    files: tuple[P115File, ...]


@dataclass(frozen=True)
class P115CloudDownloadResult:
    payload: dict[str, Any]
    target_cid: str
    status: str = "submitted"
    message: str = ""
    task_id: str = ""
    info_hash: str = ""
    task: dict[str, Any] | None = None


class P115Client:
    API_ORIGIN = "https://webapi.115.com"
    _SHARE_HOSTS = {"115.com", "www.115.com", "115cdn.com", "www.115cdn.com"}

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        handlers: list[Any] = [_NoRedirectHandler()]
        if self.settings.proxy_url.strip():
            handlers.append(
                urllib.request.ProxyHandler(
                    {"http": self.settings.proxy_url.strip(), "https": self.settings.proxy_url.strip()}
                )
            )
        self._opener = urllib.request.build_opener(*handlers)

    def configured(self) -> bool:
        return self._cookie_configured() or self._open_configured()

    def _cookie_configured(self) -> bool:
        return valid_p115_cookie(self.settings.p115_cookie)

    def _open_configured(self) -> bool:
        return (
            self.settings.p115_auth_mode == "open"
            and bool(self.settings.p115_open_access_token.strip())
            and bool(self.settings.p115_open_refresh_token.strip())
        )

    def _open_client(self) -> Any:
        if not self._open_configured():
            raise P115Error("请先配置有效的 115 Open access token 和 refresh token")
        try:
            with _p115_sdk_cache_env(self.settings):
                from p115client import P115OpenClient
                return P115OpenClient(
                    self.settings.p115_open_access_token,
                    self.settings.p115_open_refresh_token,
                    console_qrcode=False,
                )
        except ImportError as exc:
            raise P115Error("115 Open 组件未安装") from exc

    def _with_open_client(self, action: Any, *, retry_transient: bool = False) -> Any:
        client = None
        try:
            client = self._open_client()
            for attempt in range(2 if retry_transient else 1):
                try:
                    return action(client)
                except Exception as exc:
                    if attempt == 0 and _is_retryable_open_transport_error(exc):
                        continue
                    raise P115Error(f"115 Open 请求失败：{_p115_sdk_error_message(exc)}") from exc
        except P115Error:
            raise
        except Exception as exc:
            raise P115Error(f"115 Open 请求失败：{_p115_sdk_error_message(exc)}") from exc
        finally:
            if client is not None:
                _persist_open_tokens(self.settings, client)

    def parse_share_url(self, share_url: str) -> P115ShareRef:
        raw = str(share_url or "").strip()
        try:
            parsed = urllib.parse.urlsplit(raw)
        except ValueError as exc:
            raise P115Error("115 分享链接格式无效") from exc
        hostname = (parsed.hostname or "").lower()
        allowed_host = hostname in self._SHARE_HOSTS or hostname.endswith((".115.com", ".115cdn.com"))
        if parsed.scheme != "https" or not allowed_host:
            raise P115Error("只能读取有效的 115 HTTPS 分享链接")
        match = re.search(r"/s/([A-Za-z0-9_-]+)", parsed.path)
        if not match:
            raise P115Error("115 分享链接缺少分享码")
        query = urllib.parse.parse_qs(parsed.query)
        receive_code = next(
            (str(query[key][0]).strip() for key in ("password", "receive_code", "code") if query.get(key)),
            "",
        )
        return P115ShareRef(match.group(1), receive_code)

    def inspect_share(self, share_url: str) -> P115ShareSnapshot:
        # Public-share inspection is a Cookie API. A stale Open selection must
        # not disable it when a valid Cookie is also configured.
        if self._open_configured() and not self._cookie_configured():
            raise P115Error("115 Open 暂不提供分享链接读取，请改用 Cookie 连接后再处理 115 分享")
        share = self.parse_share_url(share_url)
        queue: list[tuple[str, str]] = [("0", "")]
        files: list[P115File] = []
        visited: set[str] = set()
        while queue:
            cid, parent_path = queue.pop(0)
            if cid in visited:
                continue
            visited.add(cid)
            offset = 0
            while True:
                payload = self._request_json(
                    "/share/snap",
                    params={
                        "share_code": share.share_code,
                        "receive_code": share.receive_code,
                        "cid": cid,
                        "limit": 1000,
                        "offset": offset,
                        "asc": 1,
                        "o": "file_name",
                    },
                )
                data = _response_data(payload, "115 分享读取失败")
                items = data.get("list") if isinstance(data.get("list"), list) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    normalized = _normalize_file(item, parent_path)
                    if not normalized.file_id or not normalized.name:
                        continue
                    if normalized.is_dir:
                        queue.append((normalized.file_id, normalized.path))
                    else:
                        files.append(normalized)
                        if len(files) > self.settings.p115_max_share_files:
                            raise P115Error("115 分享文件过多，请缩小分享范围后重试")
                count = _as_int(data.get("count"), len(items))
                offset += len(items)
                if not items or offset >= count:
                    break
        return P115ShareSnapshot(share, tuple(files))

    def receive_share_files(
        self,
        share: P115ShareRef,
        file_ids: list[str],
        target_cid: str,
    ) -> dict[str, Any]:
        if self._open_configured() and not self._cookie_configured():
            raise P115Error("115 Open 暂不提供分享链接转存，请改用 Cookie 连接后再处理 115 分享")
        if not file_ids:
            raise P115Error("没有可转存的 115 文件")
        return _response_data(
            self._request_json(
                "/share/receive",
                method="POST",
                data={
                    "share_code": share.share_code,
                    "receive_code": share.receive_code,
                    "file_id": ",".join(dict.fromkeys(file_ids)),
                    "cid": str(target_cid),
                },
            ),
            "115 转存失败",
        )

    def add_cloud_download(self, url: str, target_path: str, *, wait_seconds: float = 12.0) -> P115CloudDownloadResult:
        """Submit a 115 cloud-download task, including magnet/ed2k/http links."""
        if not self.configured():
            raise P115Error("115 连接未配置")
        if self._open_configured():
            target_cid = self.ensure_directory(target_path)
            payload = self._with_open_client(
                lambda client: client.clouddownload_task_add_urls({"urls": str(url).strip(), "wp_path_id": str(target_cid)})
            )
            _response_data(payload, "115 Open 离线下载任务提交失败", root_fallback=True)
            return P115CloudDownloadResult(payload=payload, target_cid=str(target_cid), message="115 Open 离线下载任务已提交")
        target_cid = self.ensure_directory(target_path)
        try:
            with _p115_sdk_cache_env(self.settings):
                from p115client import P115Client as CloudDownloadClient
                sdk = CloudDownloadClient(cookies=self.settings.p115_cookie, console_qrcode=False)
        except ImportError as exc:
            raise P115Error("115 离线下载组件未安装") from exc
        payload_data = {"url": str(url).strip(), "wp_path_id": str(target_cid)}
        last_error: Exception | None = None
        for api_type in ("ssp", "web"):
            try:
                payload = sdk.clouddownload_task_add_url(
                    payload_data,
                    type=api_type,
                    timeout=self.settings.p115_request_timeout_seconds,
                )
                _response_data(payload, "115 离线下载任务提交失败", root_fallback=True)
                return _resolve_cloud_download_result(
                    sdk,
                    str(url).strip(),
                    str(target_cid),
                    payload,
                    timeout=self.settings.p115_request_timeout_seconds,
                    wait_seconds=wait_seconds,
                )
            except Exception as exc:
                last_error = exc
                if api_type == "ssp" and _should_retry_p115_cloud_download(exc):
                    continue
                break
        detail = _p115_sdk_error_message(last_error) if last_error else ""
        raise P115Error(f"115 离线下载任务提交失败：{detail}" if detail else "115 离线下载任务提交失败") from last_error

    def test_cloud_download_capability(self) -> dict[str, Any]:
        """Check whether the current cookie can access 115 cloud-download APIs."""
        if not self.configured():
            raise P115Error("115 连接未配置")
        if self._open_configured():
            payload = self._with_open_client(lambda client: client.clouddownload_quota_info())
            _response_data(payload, "115 Open 离线下载权限检测失败", root_fallback=True)
            return payload
        try:
            with _p115_sdk_cache_env(self.settings):
                from p115client import P115Client as CloudDownloadClient
                sdk = CloudDownloadClient(cookies=self.settings.p115_cookie, console_qrcode=False)
        except ImportError as exc:
            raise P115Error("115 离线下载组件未安装") from exc
        return _probe_cloud_download_capability(sdk, self.settings.p115_request_timeout_seconds)

    def list_directory(self, cid: str | int = 0) -> tuple[P115File, ...]:
        if self._open_configured():
            offset = 0
            result: list[P115File] = []
            while True:
                payload = self._with_open_client(
                    lambda client: client.fs_files({"cid": str(cid), "limit": 1000, "offset": offset, "show_dir": 1}),
                    retry_transient=True,
                )
                data = payload.get("data") if isinstance(payload, dict) else []
                items = data if isinstance(data, list) else []
                result.extend(_normalize_file(item, "") for item in items if isinstance(item, dict))
                count = _as_int(payload.get("count") if isinstance(payload, dict) else 0, len(items))
                offset += len(items)
                if not items or offset >= count:
                    break
            return tuple(result)
        offset = 0
        result: list[P115File] = []
        while True:
            payload = self._request_json(
                "/files",
                params={"cid": str(cid), "limit": 1000, "offset": offset, "show_dir": 1, "cur": 1},
            )
            data = _response_data(payload, "115 目录读取失败", root_fallback=True)
            items = data.get("data") if isinstance(data.get("data"), list) else data.get("list")
            items = items if isinstance(items, list) else []
            for item in items:
                if isinstance(item, dict):
                    result.append(_normalize_file(item, ""))
            count = _as_int(data.get("count"), len(items))
            offset += len(items)
            if not items or offset >= count:
                break
        return tuple(result)

    def directory_id(self, path: str) -> str:
        if self._open_configured():
            normalized = "/" + "/".join(part for part in str(path).replace("\\", "/").split("/") if part)
            if normalized == "/":
                return "0"
            payload = self._with_open_client(lambda client: client.fs_info({"path": normalized}), retry_transient=True)
            data = payload.get("data") if isinstance(payload, dict) else {}
            value = data.get("file_id") or data.get("fid") or data.get("id") if isinstance(data, dict) else ""
            return str(value or "0")
        payload = self._request_json("/files/getid", params={"path": path})
        data = _response_data(payload, "115 路径查询失败", root_fallback=True)
        value = data.get("id") or data.get("cid") or payload.get("id")
        return str(value or "0")

    def create_directory(self, name: str, parent_id: str | int = 0) -> str:
        if self._open_configured():
            payload = self._with_open_client(lambda client: client.fs_mkdir({"pid": str(parent_id), "file_name": _safe_name(name)}))
            data = payload.get("data") if isinstance(payload, dict) else {}
            value = data.get("file_id") or data.get("fid") or data.get("id") if isinstance(data, dict) else ""
            if not value:
                raise P115Error("115 Open 创建目录成功但未返回目录 ID")
            return str(value)
        payload = self._request_json(
            "/files/add",
            method="POST",
            data={"cname": _safe_name(name), "pid": str(parent_id)},
        )
        data = _response_data(payload, "115 创建目录失败", root_fallback=True)
        value = data.get("cid") or data.get("id") or payload.get("cid")
        if not value:
            raise P115Error("115 创建目录成功但未返回目录 ID")
        return str(value)

    def ensure_directory(self, path: str) -> str:
        normalized = "/" + "/".join(part for part in str(path).replace("\\", "/").split("/") if part)
        existing = self.directory_id(normalized)
        if existing != "0" or normalized == "/":
            return existing
        current_id = "0"
        current_path = ""
        for part in normalized.strip("/").split("/"):
            current_path += f"/{part}"
            found = self.directory_id(current_path)
            current_id = found if found != "0" else self.create_directory(part, current_id)
        return current_id

    def rename(self, pairs: list[tuple[str, str]]) -> None:
        if not pairs:
            return
        if self._open_configured():
            for index, (file_id, name) in enumerate(pairs):
                if index:
                    # 115 Open only exposes one-file rename calls.  Keep a
                    # small jitter between calls so a batch does not look
                    # like a burst of automated edits to the service.
                    time.sleep(random.uniform(1.0, 10.0))
                self._with_open_client(lambda client, file_id=file_id, name=name: client.fs_rename((str(file_id), _safe_name(name))))
            return
        data = {f"files_new_name[{file_id}]": _safe_name(name) for file_id, name in pairs}
        _response_data(self._request_json("/files/batch_rename", method="POST", data=data), "115 重命名失败")

    def move(self, file_ids: list[str], target_cid: str) -> None:
        if not file_ids:
            return
        if self._open_configured():
            self._with_open_client(lambda client: client.fs_move({"file_ids": ",".join(dict.fromkeys(file_ids)), "to_cid": str(target_cid)}))
            return
        data = {"fid[]": list(dict.fromkeys(file_ids)), "pid": str(target_cid)}
        _response_data(self._request_json("/files/move", method="POST", data=data), "115 移动失败")

    def download_share_file(
        self,
        share: P115ShareRef,
        source: P115File,
        destination: str | Path,
    ) -> int:
        """Download one inspected share file to an atomically replaced local path."""
        if self._open_configured():
            raise P115Error("115 Open 暂不提供分享文件下载，请改用 Cookie 连接")
        if source.is_dir or not source.file_id:
            raise P115Error("115 本地下载只支持已确认的文件")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.media-index.part")
        user_agent = "Mozilla/5.0 MediaIndex/P115"
        try:
            with _p115_sdk_cache_env(self.settings):
                from p115client import P115Client as DownloadClient
                sdk = DownloadClient(cookies=self.settings.p115_cookie, console_qrcode=False)
            download_url = sdk.share_download_url(
                {
                    "file_id": source.file_id,
                    "share_code": share.share_code,
                    "receive_code": share.receive_code,
                },
                app="android",
                timeout=self.settings.p115_request_timeout_seconds,
            )
            parsed_download = urllib.parse.urlsplit(str(download_url))
            if parsed_download.scheme != "https" or not parsed_download.hostname:
                raise P115Error("115 返回了不安全的本地下载地址")
            handlers: list[Any] = []
            if self.settings.proxy_url.strip():
                handlers.append(
                    urllib.request.ProxyHandler(
                        {"http": self.settings.proxy_url.strip(), "https": self.settings.proxy_url.strip()}
                    )
                )
            opener = urllib.request.build_opener(*handlers)
            request = urllib.request.Request(
                str(download_url),
                headers={"User-Agent": user_agent},
            )
            with opener.open(request, timeout=self.settings.p115_request_timeout_seconds) as response:
                with partial.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
            downloaded = partial.stat().st_size
            if downloaded <= 0 or (source.size > 0 and downloaded != source.size):
                raise P115Error(
                    f"115 本地下载文件大小不一致：{source.name}"
                    if downloaded > 0
                    else f"115 本地下载得到空文件：{source.name}"
                )
            os.replace(partial, target)
            return downloaded
        except P115Error:
            raise
        except Exception as exc:
            raise P115Error(f"115 本地下载失败：{type(exc).__name__}") from exc
        finally:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        if authenticated and not self.configured():
            raise P115Error("请先配置有效的 115 Cookie")
        url = f"{self.API_ORIGIN}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 MediaIndex/P115"}
        if authenticated:
            headers["Cookie"] = self.settings.p115_cookie
        body = urllib.parse.urlencode(data, doseq=True).encode("utf-8") if data is not None else None
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.settings.p115_request_timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                raise P115Error("115 接口返回了不安全的重定向") from exc
            if exc.code in {401, 403}:
                raise P115Error("115 Cookie 无效、已过期或触发风控") from exc
            if exc.code == 429:
                raise P115Error("115 请求过于频繁，请稍后重试") from exc
            raise P115Error(f"115 请求失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise P115Error(f"115 连接失败（{type(exc).__name__}）") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise P115Error("115 返回了非 JSON 响应") from exc
        if not isinstance(payload, dict):
            raise P115Error("115 返回格式不兼容")
        return payload


def valid_p115_cookie(value: str) -> bool:
    raw = str(value or "")
    if "\r" in raw or "\n" in raw:
        return False
    names = {part.partition("=")[0].strip() for part in raw.split(";") if "=" in part}
    return {"UID", "CID", "SEID"}.issubset(names)


def _persist_open_tokens(settings: Settings, client: Any) -> None:
    access_token = str(getattr(client, "access_token", "")).strip()
    refresh_token = str(getattr(client, "refresh_token", "")).strip()
    if not access_token or not refresh_token:
        return
    if access_token == settings.p115_open_access_token and refresh_token == settings.p115_open_refresh_token:
        return
    env_path = Path(os.getenv("MEDIA_CONFIG_PATH", "/app/.env"))
    try:
        with env_file_lock():
            values: dict[str, str] = {}
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if "=" in line and not line.lstrip().startswith("#"):
                        key, value = line.split("=", 1)
                        values[key.strip()] = value.strip()
            values["P115_AUTH_MODE"] = "open"
            values["P115_OPEN_ACCESS_TOKEN"] = access_token
            values["P115_OPEN_REFRESH_TOKEN"] = refresh_token
            atomic_write_env(env_path, values)
            os.environ["P115_AUTH_MODE"] = "open"
            os.environ["P115_OPEN_ACCESS_TOKEN"] = access_token
            os.environ["P115_OPEN_REFRESH_TOKEN"] = refresh_token
            get_settings.cache_clear()
    except OSError:
        # A request already succeeded; do not turn it into a failed operation only because token persistence failed.
        return


def _prepare_p115_sdk_cache_env(settings: Settings) -> Path:
    """Keep p115client's import-time cache under MediaIndex's writable data dir."""
    home = Path(settings.cache_dir) / "p115client"
    cache_dir = home / ".p115client.cache.d"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise P115Error(f"115 SDK 缓存目录不可写：{cache_dir}") from exc
    os.environ["HOME"] = str(home)
    os.environ["XDG_CACHE_HOME"] = str(home / ".cache")
    const = sys.modules.get("p115client.const")
    if const is not None:
        setattr(const, "_CACHE_DIR", cache_dir)
    return cache_dir


@contextmanager
def _p115_sdk_cache_env(settings: Settings):
    """Temporarily expose a writable SDK home without leaking process-wide environment changes."""
    with _P115_SDK_ENV_LOCK:
        previous = {key: os.environ.get(key) for key in ("HOME", "XDG_CACHE_HOME")}
        cache_dir = _prepare_p115_sdk_cache_env(settings)
        try:
            yield cache_dir
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _probe_cloud_download_capability(sdk: Any, timeout: int) -> dict[str, Any]:
    probes = (
        ("quota_info_web", lambda: sdk.clouddownload_quota_info(type="web", timeout=timeout)),
        ("task_count_web", lambda: sdk.clouddownload_task_count(type="web", timeout=timeout)),
        ("task_list_web", lambda: sdk.clouddownload_task_list({"page": 1, "page_size": 1}, type="web", timeout=timeout)),
        ("downpath", lambda: sdk.clouddownload_downpath(1, timeout=timeout)),
        ("quota_info_ssp", lambda: sdk.clouddownload_quota_info(type="ssp", timeout=timeout)),
    )
    last_error: Exception | None = None
    for _name, probe in probes:
        try:
            payload = probe()
            _response_data(payload, "115 离线下载权限检测失败", root_fallback=True)
            return payload
        except Exception as exc:
            last_error = exc
            if _is_unsupported_p115_cloud_probe(exc):
                continue
            detail = _p115_sdk_error_message(exc)
            raise P115Error(f"115 离线下载权限检测失败：{detail}" if detail else "115 离线下载权限检测失败") from exc
    detail = _p115_sdk_error_message(last_error)
    raise P115Error(f"115 离线下载权限检测失败：{detail}" if detail else "115 离线下载权限检测失败") from last_error


def _is_unsupported_p115_cloud_probe(exc: Exception) -> bool:
    message = _p115_sdk_error_message(exc).casefold()
    return "undefined action" in message or "invalid action" in message or "action" in message and "undefined" in message


def _resolve_cloud_download_result(
    sdk: Any,
    url: str,
    target_cid: str,
    payload: dict[str, Any],
    *,
    timeout: int,
    wait_seconds: float,
) -> P115CloudDownloadResult:
    info_hash = _cloud_download_info_hash(url, payload)
    task_id = _first_nested_text(payload, ("task_id", "id", "info_hash", "hash"))
    deadline = time.monotonic() + max(0.0, wait_seconds)
    last_task: dict[str, Any] | None = None
    while True:
        task = _cloud_download_task_status(sdk, info_hash, task_id, timeout)
        if task:
            last_task = task
            status, message = _normalize_cloud_download_task(task)
            if status in {"done", "failed"}:
                return P115CloudDownloadResult(
                    payload,
                    target_cid,
                    status,
                    message,
                    task_id=task_id or _first_nested_text(task, ("task_id", "id")),
                    info_hash=info_hash or _first_nested_text(task, ("info_hash", "hash")),
                    task=task,
                )
        if time.monotonic() >= deadline:
            break
        time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))
    status, message = _normalize_cloud_download_task(last_task or {})
    if status == "submitted":
        message = "115 已接受离线下载任务，仍在处理中"
    return P115CloudDownloadResult(
        payload,
        target_cid,
        status if status != "failed" else "submitted",
        message,
        task_id=task_id,
        info_hash=info_hash,
        task=last_task,
    )


def _cloud_download_task_status(sdk: Any, info_hash: str, task_id: str, timeout: int) -> dict[str, Any] | None:
    probes: list[Any] = []
    if info_hash:
        probes.append(lambda: sdk.clouddownload_task(info_hash, type="web", timeout=timeout))
    probes.append(lambda: sdk.clouddownload_task_list({"page": 1, "page_size": 30}, type="web", timeout=timeout))
    probes.append(lambda: sdk.clouddownload_task_list({"page": 1, "page_size": 30, "stat": 12}, type="web", timeout=timeout))
    probes.append(lambda: sdk.clouddownload_task_list({"page": 1, "page_size": 30, "stat": 11}, type="web", timeout=timeout))
    probes.append(lambda: sdk.clouddownload_task_list({"page": 1, "page_size": 30, "stat": 9}, type="web", timeout=timeout))
    for probe in probes:
        try:
            payload = probe()
            _response_data(payload, "115 离线下载状态查询失败", root_fallback=True)
        except Exception:
            continue
        task = _select_cloud_download_task(payload, info_hash, task_id)
        if task:
            return task
    return None


def _select_cloud_download_task(payload: dict[str, Any], info_hash: str, task_id: str) -> dict[str, Any] | None:
    candidates = list(_iter_nested_dicts(payload))
    if info_hash or task_id:
        for item in candidates:
            values = {str(value).strip().lower() for value in item.values() if isinstance(value, (str, int))}
            if info_hash and info_hash.lower() in values:
                return item
            if task_id and task_id.lower() in values:
                return item
    for item in candidates:
        if any(key in item for key in ("status", "stat", "state", "percent", "progress", "info_hash", "task_id")):
            return item
    return None


def _normalize_cloud_download_task(task: dict[str, Any]) -> tuple[str, str]:
    if not task:
        return "submitted", ""
    status_value = _first_nested_text(task, ("status", "stat", "state", "status_text", "file_status")).casefold()
    percent = _first_nested_text(task, ("percent", "progress"))
    name = _first_nested_text(task, ("name", "file_name", "title"))
    error = _first_nested_text(task, ("error", "message", "msg", "fail_reason", "status_text"))
    if status_value in {"11", "done", "finish", "finished", "complete", "completed", "success", "saved"}:
        return "done", f"115 云下载已完成，文件已保存到目标目录" + (f"：{name}" if name else "")
    if status_value in {"9", "failed", "fail", "error"} or error and any(word in error for word in ("失败", "违规", "失效", "错误")):
        return "failed", f"115 云下载失败：{error or status_value}"
    if percent in {"100", "100.0", "100%"}:
        return "done", f"115 云下载已完成，文件已保存到目标目录" + (f"：{name}" if name else "")
    detail = f"，当前进度 {percent}" if percent else ""
    return "submitted", f"115 已接受离线下载任务，仍在处理中{detail}"


def _cloud_download_info_hash(url: str, payload: dict[str, Any]) -> str:
    match = re.search(r"btih:([A-Fa-f0-9]{32,40})", url)
    if match:
        return match.group(1).lower()
    return _first_nested_text(payload, ("info_hash", "hash"))


def _first_nested_text(payload: Any, keys: tuple[str, ...]) -> str:
    for item in _iter_nested_dicts(payload):
        for key in keys:
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _iter_nested_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_nested_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nested_dicts(child)


def _should_retry_p115_cloud_download(exc: Exception) -> bool:
    detail = _p115_sdk_error_payload(exc)
    code = _as_int(detail.get("errno") or detail.get("errNo") or detail.get("code") or detail.get("errcode"), 0)
    if code in {40100000, 40101017, 40101032, 990002}:
        return True
    return isinstance(exc, PermissionError)


def _p115_sdk_error_payload(exc: Exception | None) -> dict[str, Any]:
    if exc is None:
        return {}
    for arg in getattr(exc, "args", ()):
        if isinstance(arg, dict):
            return arg
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return _p115_sdk_error_payload(cause)
    return {}


def _p115_sdk_error_message(exc: Exception | None) -> str:
    detail = _p115_sdk_error_payload(exc)
    text = detail.get("error") or detail.get("message") or detail.get("msg") or detail.get("error_msg")
    code = detail.get("errno") or detail.get("errNo") or detail.get("code") or detail.get("errcode")
    if text and code:
        return f"{text}（错误码 {code}）"
    if text:
        return str(text)
    if code:
        return f"错误码 {code}"
    if exc is None:
        return ""
    raw = str(exc).strip()
    return raw if raw and raw != type(exc).__name__ else type(exc).__name__


def _is_retryable_open_transport_error(exc: Exception) -> bool:
    message = _p115_sdk_error_message(exc).casefold()
    return any(
        marker in message
        for marker in (
            "ssleoferror",
            "connection reset",
            "connection aborted",
            "remote end closed",
            "temporarily unavailable",
        )
    )


def _response_data(payload: dict[str, Any], fallback: str, *, root_fallback: bool = False) -> dict[str, Any]:
    success = payload.get("state") is True or payload.get("success") is True or payload.get("code") in {0, 200}
    if not success and root_fallback and any(key in payload for key in ("data", "id", "cid", "count")):
        success = True
    if not success:
        code = payload.get("errno") or payload.get("errNo") or payload.get("code") or "unknown"
        details = {
            4100008: "分享链接密码错误",
            4100010: "分享已取消",
            4100018: "分享链接已过期",
            4100024: "该文件已经转存过",
        }
        detail = details.get(_as_int(code, -1), "")
        raise P115Error(f"{fallback}：{detail}（错误码 {code}）" if detail else f"{fallback}（错误码 {code}）")
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _normalize_file(item: dict[str, Any], parent_path: str) -> P115File:
    is_dir = bool(item.get("is_dir")) or bool(item.get("cid") and not item.get("fid")) or str(item.get("fc")) == "0"
    file_id = item.get("fid") or item.get("file_id") or item.get("cid") or item.get("id") or ""
    parent_id = item.get("pid") or item.get("parent_id") or "0"
    # 115 Open returns `fn`, while the Cookie API returns `n` / `file_name`.
    name = str(item.get("n") or item.get("fn") or item.get("file_name") or item.get("name") or "").strip()
    path = f"{parent_path.rstrip('/')}/{name}" if parent_path else f"/{name}"
    return P115File(
        file_id=str(file_id),
        parent_id=str(parent_id),
        name=name,
        path=path,
        size=_as_int(item.get("s") or item.get("file_size") or item.get("size"), 0),
        is_dir=is_dir,
        pick_code=str(item.get("pc") or item.get("pick_code") or item.get("pickcode") or ""),
    )


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_name(value: str) -> str:
    name = str(value or "").strip()
    if not name or name in {".", ".."} or any(char in name for char in '<>\\/:"|?*'):
        raise P115Error("115 文件名包含不支持的字符")
    return name[:255]
