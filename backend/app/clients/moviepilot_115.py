from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import Settings, get_settings


class MoviePilot115Error(RuntimeError):
    """A user-safe MoviePilot connection error."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class MoviePilot115Probe:
    connected: bool
    plugin_available: bool
    plugin_enabled: bool
    client_ready: bool
    plugin_running: bool
    capabilities: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["capabilities"] = list(self.capabilities)
        return result


class MoviePilot115Client:
    OPENAPI_PATH = "/api/v1/openapi.json"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def configured(self) -> bool:
        return bool(self.settings.moviepilot_base_url.strip() and self.settings.moviepilot_api_token.strip())

    @property
    def plugin_id(self) -> str:
        return self.settings.moviepilot_115_plugin_id.strip() or "P115StrmHelper"

    @property
    def plugin_base_path(self) -> str:
        return f"/api/v1/plugin/{urllib.parse.quote(self.plugin_id, safe='')}"

    @property
    def transfer_path(self) -> str:
        return f"{self.plugin_base_path}/add_transfer_share"

    def _url(self, path: str) -> str:
        if not self.configured():
            raise MoviePilot115Error("请先保存 MoviePilot API 地址和 Token")
        return f"{self.settings.moviepilot_base_url.rstrip('/')}/{path.lstrip('/')}"

    def get_json(self, path: str, *, timeout: int | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url(path),
            headers={
                "Accept": "application/json",
                "User-Agent": "MediaIndex/MoviePilot115",
                "X-API-KEY": self.settings.moviepilot_api_token,
            },
            method="GET",
        )
        request_timeout = timeout or self.settings.moviepilot_115_request_timeout_seconds
        try:
            with self._opener.open(request, timeout=request_timeout) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                raise MoviePilot115Error("MoviePilot API 拒绝重定向，请填写最终 API 根地址") from exc
            if exc.code in {401, 403}:
                raise MoviePilot115Error("MoviePilot API Token 无效或权限不足") from exc
            if exc.code == 404:
                raise MoviePilot115Error("MoviePilot 接口不存在，请确认 API 地址和插件版本") from exc
            raise MoviePilot115Error(f"MoviePilot 请求失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise MoviePilot115Error(f"MoviePilot 连接失败（{type(exc).__name__}）") from exc
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MoviePilot115Error("MoviePilot 返回了非 JSON 响应，请确认地址指向 API 端口") from exc
        if not isinstance(data, dict):
            raise MoviePilot115Error("MoviePilot 返回格式不兼容")
        return data

    def probe(self, *, timeout: int = 15) -> MoviePilot115Probe:
        document = self.get_json(self.OPENAPI_PATH, timeout=timeout)
        paths = document.get("paths")
        if not isinstance(paths, dict):
            raise MoviePilot115Error("MoviePilot OpenAPI 文档格式不兼容")
        plugin_available = f"{self.plugin_base_path}/get_status" in paths
        transfer_available = self.transfer_path in paths
        if not plugin_available:
            return MoviePilot115Probe(True, False, False, False, False, ())

        status = self.get_json(f"{self.plugin_base_path}/get_status", timeout=timeout)
        if status.get("code") != 0 or not isinstance(status.get("data"), dict):
            raise MoviePilot115Error("115 网盘 STRM 助手状态响应不兼容")
        details = status["data"]
        capabilities = ("external_organize",) if transfer_available else ()
        return MoviePilot115Probe(
            connected=True,
            plugin_available=True,
            plugin_enabled=bool(details.get("enabled")),
            client_ready=bool(details.get("has_client")),
            plugin_running=bool(details.get("running")),
            capabilities=capabilities,
        )
