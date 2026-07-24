from __future__ import annotations

import json
import os
import re
import shutil
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


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
        return valid_p115_cookie(self.settings.p115_cookie)

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

    def list_directory(self, cid: str | int = 0) -> tuple[P115File, ...]:
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
        payload = self._request_json("/files/getid", params={"path": path})
        data = _response_data(payload, "115 路径查询失败", root_fallback=True)
        value = data.get("id") or data.get("cid") or payload.get("id")
        return str(value or "0")

    def create_directory(self, name: str, parent_id: str | int = 0) -> str:
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
        data = {f"files_new_name[{file_id}]": _safe_name(name) for file_id, name in pairs}
        _response_data(self._request_json("/files/batch_rename", method="POST", data=data), "115 重命名失败")

    def move(self, file_ids: list[str], target_cid: str) -> None:
        if not file_ids:
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
        if source.is_dir or not source.file_id:
            raise P115Error("115 本地下载只支持已确认的文件")
        try:
            from p115client import P115Client as DownloadClient
        except ImportError as exc:
            raise P115Error("115 本地下载组件未安装") from exc

        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.media-index.part")
        user_agent = "Mozilla/5.0 MediaIndex/P115"
        try:
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
    name = str(item.get("n") or item.get("file_name") or item.get("name") or "").strip()
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
