from __future__ import annotations

import json
import math
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from app.clients.http import NoRedirectHandler
from app.core.config import Settings, get_settings


class QuarkError(RuntimeError):
    """A redacted, user-safe Quark API error."""


@dataclass(frozen=True)
class QuarkAccount:
    user_id: str
    nickname: str = ""


@dataclass(frozen=True)
class QuarkFile:
    file_id: str
    parent_id: str
    name: str
    size: int = 0
    is_dir: bool = False
    sha1: str = ""
    md5: str = ""


@dataclass(frozen=True)
class QuarkQrLogin:
    token: str
    qr_url: str
    cookie: str = ""


@dataclass(frozen=True)
class QuarkQrPoll:
    status: str
    cookie: str = ""


@dataclass(frozen=True)
class QuarkShareRef:
    share_id: str
    passcode: str = ""


@dataclass(frozen=True)
class QuarkShareFile:
    file_id: str
    parent_id: str
    name: str
    size: int = 0
    is_dir: bool = False
    share_fid_token: str = ""


@dataclass(frozen=True)
class QuarkShareSnapshot:
    share: QuarkShareRef
    share_token: str
    title: str
    files: tuple[QuarkShareFile, ...]


@dataclass(frozen=True)
class QuarkDownloadLink:
    """A short-lived Quark CDN link. Never serialize it outside a workflow."""

    file_id: str
    url: str


class QuarkClient:
    """Native Quark client with an explicit read/write boundary.

    Directory inspection and share inspection are read-only.  The caller must
    deliberately invoke the separate receive, rename, move, or mkdir commands
    before a cloud-side change can occur.  Requests use a closed host allow-list
    and never follow redirects so an authenticated Cookie cannot be forwarded to
    an arbitrary endpoint.
    """

    LOGIN_ORIGIN = "https://uop.quark.cn"
    PAN_ORIGIN = "https://pan.quark.cn"
    DRIVE_ORIGIN = "https://drive-pc.quark.cn"
    API_ORIGIN = "https://drive.quark.cn"
    TRUSTED_HOSTS = {"uop.quark.cn", "pan.quark.cn", "drive-pc.quark.cn", "drive.quark.cn", "su.quark.cn"}
    CLIENT_ID = "532"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) quark-cloud-drive/2.5.20 Chrome/100.0.4896.160 "
        "Electron/18.3.5.4-b478491100 Safari/537.36 Channel/pckk_other_ch"
    )
    _COOKIE_REFRESH_LOCK = threading.RLock()

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        handlers: list[Any] = [NoRedirectHandler()]
        proxy_url = str(getattr(self.settings, "proxy_url", "")).strip()
        if proxy_url:
            handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        self._opener = urllib.request.build_opener(*handlers)

    def configured(self) -> bool:
        return valid_quark_cookie(str(getattr(self.settings, "quark_cookie", "")))

    def start_qr_login(self) -> QuarkQrLogin:
        query = urllib.parse.urlencode({"client_id": self.CLIENT_ID, "v": "1.2", "request_id": uuid.uuid4().hex})
        payload, cookie = self._qr_request_json(f"{self.LOGIN_ORIGIN}/cas/ajax/getTokenForQrcodeLogin?{query}")
        token = _nested_text(payload, ("data", "members", "token"))
        if not token:
            raise QuarkError("夸克未返回扫码会话")
        query = urllib.parse.urlencode(
            {"token": token, "client_id": self.CLIENT_ID, "ssb": "weblogin", "uc_param_str": ""}
        )
        return QuarkQrLogin(token=token, qr_url=f"https://su.quark.cn/4_eMHBJ?{query}", cookie=cookie)

    def poll_qr_login(self, token: str, cookie: str = "") -> QuarkQrPoll:
        safe_token = str(token or "").strip()
        if not safe_token or len(safe_token) > 512 or any(char in safe_token for char in "\r\n"):
            raise QuarkError("扫码会话无效")
        query = urllib.parse.urlencode({"client_id": self.CLIENT_ID, "v": "1.2", "token": safe_token, "request_id": uuid.uuid4().hex})
        payload, current_cookie = self._qr_request_json(
            f"{self.LOGIN_ORIGIN}/cas/ajax/getServiceTicketByQrcodeToken?{query}", cookie=cookie
        )
        status = str(_nested_value(payload, ("status",)) or "")
        ticket = _nested_text(payload, ("data", "members", "service_ticket"))
        if ticket:
            login_cookie = self._cookie_from_ticket(ticket, current_cookie)
            return QuarkQrPoll(status="success", cookie=login_cookie)
        if status in {"400040", "400041", "400042", "50004002", "50004003", "50004004"}:
            return QuarkQrPoll(status="expired")
        # Quark has returned several undocumented intermediate status codes
        # while a QR code is still waiting to be scanned.  Treating every
        # unknown code as terminal used to consume the server-side session and
        # made the QR image disappear after the first poll.  Only the explicit
        # expiry codes above are terminal; a ticket remains the sole success
        # signal.
        return QuarkQrPoll(status="waiting", cookie=current_cookie)

    def account(self) -> QuarkAccount:
        payload = self._request_json(f"{self.PAN_ORIGIN}/account/info", params={"platform": "pc", "fr": "pc"})
        data = _nested_dict(payload, ("data",)) or payload
        user_id = _first_text(data, ("uid", "user_id", "id"))
        nickname = _first_text(data, ("nickname", "nick_name", "name"))
        if not user_id:
            user_id = _cookie_value(str(getattr(self.settings, "quark_cookie", "")), "__uid")
        # QAS only requires the account endpoint to return a non-empty data
        # object.  Quark has also shipped responses where nickname is present
        # but uid is omitted, so root-directory access remains the authoritative
        # credential check.
        if not data or (not user_id and not nickname):
            raise QuarkError("夸克账号信息返回格式不兼容")
        return QuarkAccount(user_id=user_id, nickname=nickname)

    def list_root(self) -> tuple[QuarkFile, ...]:
        return self.list_directory("0")

    def list_directory(self, parent_id: str) -> tuple[QuarkFile, ...]:
        """Keep the v0.6.14 single-page directory contract for old callers."""
        safe_parent = _safe_file_id(parent_id)
        if not safe_parent:
            raise QuarkError("夸克目录 ID 无效")
        payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/file/sort",
            params={"pr": "ucpro", "fr": "pc", "pdir_fid": safe_parent, "_page": "1", "_size": "200", "_fetch_total": "1"},
        )
        status = str(payload.get("status") or "")
        code = str(payload.get("code") or "")
        if (status and status not in {"0", "200"}) or (code and code not in {"0", "200"}):
            raise QuarkError("夸克 Cookie 无效、已过期或无法读取网盘目录")
        data = _nested_dict(payload, ("data",))
        if data is None:
            raise QuarkError("夸克目录返回格式不兼容")
        raw_items = data.get("list") or data.get("files") or []
        if not isinstance(raw_items, list):
            raise QuarkError("夸克目录返回格式不兼容")
        return tuple(_normalize_file(item) for item in raw_items if isinstance(item, dict))

    def list_directory_complete(self, parent_id: str) -> tuple[QuarkFile, ...]:
        """Read a fail-closed complete listing for destructive workflows."""
        safe_parent = _safe_file_id(parent_id)
        if not safe_parent:
            raise QuarkError("夸克目录 ID 无效")
        page = 1
        page_size = 200
        expected_total: int | None = None
        seen_ids: set[str] = set()
        result: list[QuarkFile] = []
        while True:
            payload = self._request_json(
                f"{self.DRIVE_ORIGIN}/1/clouddrive/file/sort",
                params={
                    "pr": "ucpro",
                    "fr": "pc",
                    "pdir_fid": safe_parent,
                    "_page": str(page),
                    "_size": str(page_size),
                    "_fetch_total": "1",
                },
            )
            status = str(payload.get("status") or "")
            code = str(payload.get("code") or "")
            if (status and status not in {"0", "200"}) or (code and code not in {"0", "200"}):
                raise QuarkError("夸克 Cookie 无效、已过期或无法读取网盘目录")
            data = _nested_dict(payload, ("data",))
            if data is None:
                raise QuarkError("夸克目录返回格式不兼容")
            raw_items = data.get("list") or data.get("files") or []
            if not isinstance(raw_items, list):
                raise QuarkError("夸克目录返回格式不兼容")
            normalized = [_normalize_file(item) for item in raw_items if isinstance(item, dict)]
            page_ids = [item.file_id for item in normalized]
            if len(page_ids) != len(set(page_ids)) or any(file_id in seen_ids for file_id in page_ids):
                raise QuarkError("夸克目录分页返回重复文件，无法确认清单完整")
            result.extend(normalized)
            seen_ids.update(page_ids)

            current_total = _directory_total(payload, data)
            if current_total is None:
                raise QuarkError("夸克目录未返回分页总数，无法确认清单完整")
            if expected_total is None:
                expected_total = current_total
            elif current_total != expected_total:
                raise QuarkError("夸克目录在分页读取期间发生变化，请重试")
            if len(result) > expected_total:
                raise QuarkError("夸克目录分页总数与文件清单不一致")
            if len(result) == expected_total:
                return tuple(result)
            if not raw_items:
                raise QuarkError("夸克目录分页提前结束，无法确认清单完整")
            page += 1
            if page > 10_000:
                raise QuarkError("夸克目录分页超出安全上限")

    def file_in_directory(self, parent_id: str, file_id: str) -> QuarkFile:
        """Read one file through its asserted parent directory.

        Quark's public client contract is not stable enough to trust a guessed
        standalone file-info endpoint.  Looking up the supplied ID in its
        actual parent directory also prevents a caller from substituting a
        stale or unrelated file ID at execution time.
        """
        safe_file_id = _safe_file_id(file_id)
        if not safe_file_id:
            raise QuarkError("夸克文件 ID 无效")
        matches = [item for item in self.list_directory(parent_id) if item.file_id == safe_file_id]
        if len(matches) != 1 or matches[0].is_dir:
            raise QuarkError("夸克源文件不存在、已变化或不是普通文件")
        return matches[0]

    def directory_id(self, path: str) -> str:
        """Resolve an existing absolute directory without creating it.

        Returning an empty string means that the requested directory is absent
        (or cannot be uniquely identified), which is intentionally distinct from
        ``ensure_directory``.  Transfer execution is the only workflow allowed
        to create a missing target directory.
        """
        return self._directory_id(path, complete=False)

    def directory_id_complete(self, path: str) -> str:
        """Resolve an existing path through complete directory listings."""
        return self._directory_id(path, complete=True)

    def _directory_id(self, path: str, *, complete: bool) -> str:
        safe_path = _safe_cloud_path(path)
        if safe_path == "/":
            return "0"
        current_id = "0"
        listing = self.list_directory_complete if complete else self.list_directory
        for component in (part for part in safe_path.split("/") if part):
            matches = [
                item
                for item in listing(current_id)
                if item.is_dir and item.name == component
            ]
            if len(matches) != 1:
                return ""
            current_id = matches[0].file_id
        return current_id

    def ensure_directory(self, path: str) -> str:
        safe_path = _safe_cloud_path(path)
        payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/file",
            method="POST",
            params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            data={"pdir_fid": "0", "file_name": "", "dir_path": safe_path, "dir_init_lock": False},
        )
        data = _command_data(payload, "夸克创建目标目录失败")
        file_id = _first_text(data, ("fid", "file_id", "id"))
        if not file_id:
            raise QuarkError("夸克创建目标目录未返回目录 ID")
        return file_id

    def save_share_files(self, snapshot: QuarkShareSnapshot, file_ids: list[str], destination_id: str) -> str:
        requested = list(dict.fromkeys(str(item).strip() for item in file_ids if _safe_file_id(item)))
        destination = _safe_file_id(destination_id)
        if not requested or not destination:
            raise QuarkError("夸克转存文件或目标目录无效")
        available = {item.file_id: item for item in snapshot.files if item.file_id and not item.is_dir}
        selected = [available[item] for item in requested if item in available]
        if len(selected) != len(requested) or any(not item.share_fid_token for item in selected):
            raise QuarkError("夸克分享内容已变化，无法安全提交转存")
        source_parents = {item.parent_id or "0" for item in selected}
        if len(source_parents) != 1:
            raise QuarkError("夸克单次转存只能提交同一分享目录中的文件")
        source_parent = next(iter(source_parents))
        if not _safe_file_id(source_parent):
            raise QuarkError("夸克分享源目录无效")
        payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/share/sharepage/save",
            method="POST",
            params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            data={
                "fid_list": [item.file_id for item in selected],
                "fid_token_list": [item.share_fid_token for item in selected],
                "to_pdir_fid": destination,
                "pwd_id": snapshot.share.share_id,
                "stoken": snapshot.share_token,
                "pdir_fid": source_parent,
                "scene": "link",
            },
        )
        data = _command_data(payload, "夸克转存提交失败")
        task_id = _first_text(data, ("task_id", "id"))
        if not task_id:
            raise QuarkError("夸克转存提交未返回任务 ID")
        return task_id

    def task(self, task_id: str, *, retry_index: int = 0) -> dict[str, Any]:
        safe_task_id = _safe_file_id(task_id)
        if not safe_task_id:
            raise QuarkError("夸克任务 ID 无效")
        try:
            safe_retry_index = max(0, int(retry_index))
        except (TypeError, ValueError) as exc:
            raise QuarkError("夸克任务重试序号无效") from exc
        payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/task",
            params={
                "pr": "ucpro",
                "fr": "pc",
                "uc_param_str": "",
                "task_id": safe_task_id,
                "retry_index": str(safe_retry_index),
            },
        )
        return _command_data(payload, "夸克转存任务查询失败")

    def wait_task(self, task_id: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        """Wait for one Quark remote task and fail closed on errors or timeout.

        Some Quark write endpoints complete synchronously and omit a task ID;
        an empty ID is therefore an explicit synchronous-success result.
        """
        raw_task_id = str(task_id or "").strip()
        if not raw_task_id:
            return {}
        safe_task_id = _safe_file_id(raw_task_id)
        if not safe_task_id:
            raise QuarkError("夸克任务 ID 无效")
        try:
            wait_seconds = (
                float(getattr(self.settings, "quark_request_timeout_seconds", 30))
                if timeout_seconds is None
                else float(timeout_seconds)
            )
        except (TypeError, ValueError) as exc:
            raise QuarkError("夸克任务等待时限无效") from exc
        if not math.isfinite(wait_seconds) or wait_seconds < 0:
            raise QuarkError("夸克任务等待时限无效")
        wait_seconds = min(300.0, wait_seconds)
        deadline = time.monotonic() + wait_seconds
        retry_index = 0
        while True:
            task = self.task(safe_task_id, retry_index=retry_index)
            status = _task_status(task)
            if status in {"2", "success", "succeeded", "done", "completed", "finished"}:
                return task
            if status in {"3", "4", "failed", "error", "cancelled", "canceled"}:
                raise QuarkError("夸克远程任务失败")
            now = time.monotonic()
            if now >= deadline:
                raise QuarkError("夸克远程任务等待超时")
            time.sleep(min(0.5, max(0.01, deadline - now)))
            retry_index += 1

    def rename_file(self, file_id: str, name: str) -> None:
        safe_id = _safe_file_id(file_id)
        safe_name = _safe_file_name(name)
        if not safe_id:
            raise QuarkError("夸克文件 ID 无效")
        payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/file/rename",
            method="POST",
            params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            data={"fid": safe_id, "file_name": safe_name},
        )
        _command_data(payload, "夸克文件改名失败")

    def move_files(self, file_ids: list[str], destination_id: str) -> str:
        safe_ids = list(dict.fromkeys(str(item).strip() for item in file_ids if _safe_file_id(item)))
        destination = _safe_file_id(destination_id)
        if not safe_ids or not destination:
            raise QuarkError("夸克移动文件或目标目录无效")
        payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/file/move",
            method="POST",
            params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            data={"action_type": 1, "to_pdir_fid": destination, "filelist": safe_ids, "exclude_fids": []},
        )
        data = _command_data(payload, "夸克文件移动失败")
        return _first_text(data, ("task_id", "id"))

    def copy_files(self, file_ids: list[str], destination_id: str) -> str:
        safe_ids = _validated_command_file_ids(file_ids, "夸克复制文件 ID 无效")
        destination = _safe_file_id(destination_id)
        if not destination:
            raise QuarkError("夸克复制目标目录无效")
        payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/file/copy",
            method="POST",
            params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            data={"action_type": 1, "to_pdir_fid": destination, "filelist": safe_ids, "exclude_fids": []},
        )
        data = _command_data(payload, "夸克文件复制失败")
        task_id = _first_text(data, ("task_id", "id"))
        self.wait_task(task_id)
        return task_id

    def trash_files(self, file_ids: list[str]) -> str:
        """Move exact owned-file IDs to Quark's recycle bin; never purge it."""
        safe_ids = _validated_command_file_ids(file_ids, "夸克回收站文件 ID 无效")
        payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/file/delete",
            method="POST",
            params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            data={"action_type": 2, "filelist": safe_ids, "exclude_fids": []},
        )
        data = _command_data(payload, "夸克文件移入回收站失败")
        task_id = _first_text(data, ("task_id", "id"))
        self.wait_task(task_id)
        return task_id

    def download_link(self, file_id: str) -> QuarkDownloadLink:
        """Request a signed link without downloading bytes."""
        safe_id = _safe_file_id(file_id)
        if not safe_id:
            raise QuarkError("夸克文件 ID 无效")
        payload = self._request_json(
            f"{self.API_ORIGIN}/1/clouddrive/file/download",
            method="POST",
            params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            data={"fids": [safe_id]},
        )
        values = _download_link_values(payload)
        if not isinstance(values, list) or not values or not isinstance(values[0], dict):
            raise QuarkError("夸克下载链接返回格式不兼容")
        url = _safe_quark_download_url(str(values[0].get("file_download_url") or values[0].get("download_url") or ""))
        if not url:
            raise QuarkError("夸克未返回受信任的下载链接")
        return QuarkDownloadLink(file_id=safe_id, url=url)

    def read_download_range(self, file_id: str, start: int, end: int, *, max_bytes: int = 32 * 1024 * 1024) -> bytes:
        """Read one bounded range from a trusted Quark CDN host."""
        if start < 0 or end < start:
            raise QuarkError("夸克下载范围无效")
        requested = end - start + 1
        if max_bytes <= 0 or requested > max_bytes:
            raise QuarkError("夸克下载范围超过安全上限")
        link = self.download_link(file_id)
        response = self._open_download_url(link.url, {"Range": f"bytes={start}-{end}"})
        try:
            status = int(getattr(response, "status", 200) or 200)
            if status not in {200, 206}:
                raise QuarkError("夸克下载范围请求失败")
            if status == 200 and start != 0:
                raise QuarkError("夸克下载链接不支持断点范围读取")
            body = response.read(max_bytes + 1)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if len(body) > max_bytes or len(body) > requested:
            raise QuarkError("夸克下载响应超过请求范围")
        if status == 206 and len(body) != requested:
            raise QuarkError("夸克下载范围响应长度不一致")
        return body

    def parse_share_url(self, share_url: str) -> QuarkShareRef:
        raw = str(share_url or "").strip()
        try:
            parsed = urllib.parse.urlsplit(raw)
        except ValueError as exc:
            raise QuarkError("夸克分享链接格式无效") from exc
        if parsed.scheme != "https" or parsed.hostname not in {"pan.quark.cn", "www.pan.quark.cn"}:
            raise QuarkError("只支持夸克分享链接")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[0] != "s" or not _safe_share_id(parts[1]):
            raise QuarkError("夸克分享链接格式无效")
        values = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        passcode = str((values.get("pwd") or values.get("passcode") or [""])[0]).strip()
        if passcode and (len(passcode) > 32 or not passcode.isalnum()):
            raise QuarkError("夸克分享提取码格式无效")
        return QuarkShareRef(share_id=parts[1], passcode=passcode)

    def inspect_share(self, share_url: str, *, max_files: int = 1000, max_depth: int = 8) -> QuarkShareSnapshot:
        """Read a shared file tree without saving it into the user's drive."""
        share = self.parse_share_url(share_url)
        token_payload = self._request_json(
            f"{self.DRIVE_ORIGIN}/1/clouddrive/share/sharepage/token",
            method="POST",
            params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            data={"pwd_id": share.share_id, "passcode": share.passcode},
        )
        data = _share_data(token_payload, "夸克分享链接无效、已过期或提取码错误")
        share_token = _first_text(data, ("stoken", "share_token"))
        if not share_token:
            raise QuarkError("夸克分享链接未返回访问令牌")
        files: list[QuarkShareFile] = []
        queue: list[tuple[str, int]] = [("0", 0)]
        title = ""
        while queue and len(files) < max_files:
            parent_id, depth = queue.pop(0)
            page = 1
            while len(files) < max_files:
                payload = self._request_json(
                    f"{self.DRIVE_ORIGIN}/1/clouddrive/share/sharepage/detail",
                    params={
                        "pr": "ucpro", "fr": "pc", "uc_param_str": "", "pwd_id": share.share_id,
                        "stoken": share_token, "pdir_fid": parent_id, "_page": str(page), "_size": "50",
                    },
                )
                page_data = _share_data(payload, "夸克分享文件读取失败")
                items = page_data.get("list") or page_data.get("files") or []
                if not isinstance(items, list):
                    raise QuarkError("夸克分享文件返回格式不兼容")
                normalized = [_normalize_share_file(item, parent_id) for item in items if isinstance(item, dict)]
                if not title and normalized:
                    title = normalized[0].name
                files.extend(normalized[: max_files - len(files)])
                if depth < max_depth:
                    queue.extend((item.file_id, depth + 1) for item in normalized if item.is_dir)
                if len(items) < 50:
                    break
                page += 1
                if page > 100:
                    raise QuarkError("夸克分享文件数量超过只读验证上限")
        if not files:
            raise QuarkError("夸克分享中未找到文件")
        return QuarkShareSnapshot(share=share, share_token=share_token, title=title, files=tuple(files))

    def _cookie_from_ticket(self, ticket: str, cookie: str = "") -> str:
        account_url = f"{self.PAN_ORIGIN}/account/info?{urllib.parse.urlencode({'st': ticket, 'lw': 'scan'})}"
        _, cookie, _ = self._qr_fetch(account_url, cookie=cookie)
        # The CAS response does not always include every cookie needed by the
        # drive API.  Match LitePan's flow by visiting the web app and reading
        # one root item, collecting incremental __pus/__puus values each time.
        _, cookie, _ = self._qr_fetch(
            f"{self.PAN_ORIGIN}/",
            cookie=cookie,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Upgrade-Insecure-Requests": "1"},
        )
        bootstrap_query = urllib.parse.urlencode(
            {"pr": "ucpro", "fr": "pc", "pdir_fid": "0", "_page": "1", "_size": "1", "_fetch_total": "1"}
        )
        try:
            _, cookie, _ = self._qr_fetch(
                f"{self.DRIVE_ORIGIN}/1/clouddrive/file/sort?{bootstrap_query}",
                cookie=cookie,
                headers={"Origin": self.PAN_ORIGIN, "Referer": f"{self.PAN_ORIGIN}/"},
            )
        except QuarkError:
            # The bootstrap only enriches rotating cookies.  The caller will
            # perform a real root-directory read immediately after saving.
            pass
        if not valid_quark_cookie(cookie):
            raise QuarkError("夸克扫码授权未返回有效 Cookie")
        return cookie

    def _qr_request_json(self, url: str, *, cookie: str = "") -> tuple[dict[str, Any], str]:
        raw, current_cookie, _ = self._qr_fetch(url, cookie=cookie)
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise QuarkError("夸克扫码接口返回了非 JSON 响应") from exc
        if not isinstance(payload, dict):
            raise QuarkError("夸克扫码接口返回格式不兼容")
        return payload, current_cookie

    def _qr_fetch(
        self,
        url: str,
        *,
        cookie: str = "",
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str, int]:
        current_url = url
        current_cookie = normalize_quark_cookie(cookie)
        for _hop in range(6):
            parsed = urllib.parse.urlsplit(current_url)
            if parsed.scheme != "https" or parsed.hostname not in self.TRUSTED_HOSTS:
                raise QuarkError("夸克扫码跳转地址不受信任")
            request_headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": f"{self.PAN_ORIGIN}/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
                **(headers or {}),
            }
            if current_cookie:
                request_headers["Cookie"] = current_cookie
            request = urllib.request.Request(current_url, headers=request_headers, method="GET")
            try:
                response = self._opener.open(
                    request, timeout=int(getattr(self.settings, "quark_request_timeout_seconds", 30))
                )
            except urllib.error.HTTPError as exc:
                if exc.code not in {301, 302, 303, 307, 308}:
                    if exc.code in {401, 403}:
                        raise QuarkError("夸克扫码授权失效或触发风控") from exc
                    raise QuarkError(f"夸克扫码请求失败（HTTP {exc.code}）") from exc
                response = exc
            except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
                raise QuarkError(f"夸克扫码连接失败（{type(exc).__name__}）") from exc
            with response:
                status = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
                response_headers = response.headers
                values = (response_headers.get_all("Set-Cookie") or []) if hasattr(response_headers, "get_all") else [response_headers.get("Set-Cookie", "")]
                current_cookie = _merge_quark_cookies(current_cookie, values)
                if status in {301, 302, 303, 307, 308}:
                    location = str(response_headers.get("Location", "") or "").strip()
                    if not location:
                        return b"", current_cookie, status
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue
                return response.read(8 * 1024 * 1024), current_cookie, status
        raise QuarkError("夸克扫码请求重定向过多")

    def _request_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        authenticated: bool = True,
        method: str = "GET",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if data is not None else None
        response = self._open(f"{url}?{query}" if query else url, authenticated=authenticated, method=method, body=body)
        with response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QuarkError("夸克返回了非 JSON 响应") from exc
        if not isinstance(payload, dict):
            raise QuarkError("夸克返回格式不兼容")
        return payload

    def _open(self, url: str, *, authenticated: bool, method: str = "GET", body: bytes | None = None) -> Any:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in self.TRUSTED_HOSTS:
            raise QuarkError("夸克请求地址不受信任")
        headers = {"Accept": "application/json, text/plain, */*", "User-Agent": self.USER_AGENT, "Referer": f"{self.PAN_ORIGIN}/"}
        if authenticated:
            cookie = normalize_quark_cookie(str(getattr(self.settings, "quark_cookie", "")))
            if not valid_quark_cookie(cookie):
                raise QuarkError("请先配置有效的夸克 Cookie")
            headers["Cookie"] = cookie
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            response = self._opener.open(
                request,
                timeout=int(getattr(self.settings, "quark_request_timeout_seconds", 30)),
            )
            self._refresh_cookie_from_response(response)
            return response
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                raise QuarkError("夸克接口返回了不安全的重定向") from exc
            if exc.code in {401, 403}:
                raise QuarkError("夸克 Cookie 无效、已过期或触发风控") from exc
            if exc.code == 429:
                raise QuarkError("夸克请求过于频繁，请稍后重试") from exc
            raise QuarkError(f"夸克请求失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
            raise QuarkError(f"夸克连接失败（{type(exc).__name__}）") from exc

    def _refresh_cookie_from_response(self, response: Any) -> None:
        """Keep Quark's rotating cookies for the immediately following CDN read.

        Quark can accept a stale ``__puus`` for a drive API call while rotating
        it in ``Set-Cookie``.  The signed download URL then rejects that stale
        value with HTTP 412.  Keep the refresh in memory; credentials are never
        logged or serialized into a transfer record.
        """
        response_headers = getattr(response, "headers", None)
        if response_headers is None:
            return
        values = (
            response_headers.get_all("Set-Cookie") or []
            if hasattr(response_headers, "get_all")
            else [response_headers.get("Set-Cookie", "")]
        )
        if not any(values):
            return
        with self._COOKIE_REFRESH_LOCK:
            current = normalize_quark_cookie(str(getattr(self.settings, "quark_cookie", "")))
            refreshed = _merge_quark_cookies(current, values)
            if refreshed and refreshed != current:
                self.settings.quark_cookie = refreshed

    def _open_download_url(self, url: str, headers: dict[str, str]) -> Any:
        safe_url = _safe_quark_download_url(url)
        if not safe_url:
            raise QuarkError("夸克下载链接不受信任")
        cookie = normalize_quark_cookie(str(getattr(self.settings, "quark_cookie", "")))
        if not valid_quark_cookie(cookie):
            raise QuarkError("请先配置有效的夸克 Cookie")
        request = urllib.request.Request(
            safe_url,
            headers={"User-Agent": self.USER_AGENT, "Referer": f"{self.PAN_ORIGIN}/", "Cookie": cookie, **headers},
            method="GET",
        )
        try:
            return self._opener.open(request, timeout=int(getattr(self.settings, "quark_request_timeout_seconds", 30)))
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                raise QuarkError("夸克下载链接返回了不安全的重定向") from exc
            if exc.code in {401, 403}:
                raise QuarkError("夸克下载链接已失效或权限不足") from exc
            if exc.code == 416:
                raise QuarkError("夸克下载范围超出文件大小") from exc
            raise QuarkError(f"夸克下载请求失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
            raise QuarkError(f"夸克下载连接失败（{type(exc).__name__}）") from exc


def valid_quark_cookie(value: str) -> bool:
    return bool(normalize_quark_cookie(value))


def normalize_quark_cookie(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 16384 or "\r" in raw or "\n" in raw:
        return ""
    if raw[:7].casefold() == "cookie:":
        raw = raw[7:].strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        raw = raw[1:-1].strip()
    ignored = {"path", "domain", "expires", "max-age", "samesite", "secure", "httponly", "priority"}
    order: list[str] = []
    values: dict[str, str] = {}
    for part in raw.split(";"):
        name, separator, item_value = part.strip().partition("=")
        name = name.strip()
        item_value = item_value.strip()
        if not separator or not name or not item_value or name.casefold() in ignored:
            continue
        if len(name) > 128 or not all(char.isalnum() or char in {"_", "-", "."} for char in name):
            continue
        if name not in values:
            order.append(name)
        values[name] = item_value
    return "; ".join(f"{name}={values[name]}" for name in order)


def _cookie_pair(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip()


def _cookie_value(cookie: str, name: str) -> str:
    for part in normalize_quark_cookie(cookie).split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == name:
            return value.strip()
    return ""


def _merge_quark_cookies(existing: str, set_cookie_values: list[str | None]) -> str:
    merged = normalize_quark_cookie(existing)
    parts = [part.strip() for part in merged.split(";") if part.strip()]
    order: list[str] = []
    values: dict[str, str] = {}
    for part in parts:
        name, _, value = part.partition("=")
        if name not in values:
            order.append(name)
        values[name] = value
    for header in set_cookie_values:
        pair = _cookie_pair(str(header or ""))
        name, separator, value = pair.partition("=")
        if not separator or not name or not value or name in {"_gid", "isg", "l"} or name.startswith("_ga"):
            continue
        if name not in values:
            order.append(name)
        values[name] = value
    return "; ".join(f"{name}={values[name]}" for name in order)


def _nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_text(payload: dict[str, Any], path: tuple[str, ...]) -> str:
    value = _nested_value(payload, path)
    return str(value).strip() if value is not None else ""


def _nested_dict(payload: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any] | None:
    value = _nested_value(payload, path)
    return value if isinstance(value, dict) else None


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _directory_total(payload: dict[str, Any], data: dict[str, Any]) -> int | None:
    containers = (payload.get("metadata"), data.get("metadata"), data, payload)
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("_total", "total"):
            value = container.get(key)
            if value is None or isinstance(value, bool):
                continue
            try:
                total = int(value)
            except (TypeError, ValueError):
                continue
            if total >= 0:
                return total
    return None


def _task_status(task: dict[str, Any]) -> str:
    return _first_text(task, ("status", "state")).casefold()


def _validated_command_file_ids(file_ids: list[str], error: str) -> list[str]:
    raw_ids = [str(item or "").strip() for item in (file_ids or [])]
    if not raw_ids or any(_safe_file_id(item) != item for item in raw_ids):
        raise QuarkError(error)
    return list(dict.fromkeys(raw_ids))


def _normalize_file(item: dict[str, Any]) -> QuarkFile:
    file_id = _first_text(item, ("fid", "file_id", "id"))
    name = _first_text(item, ("file_name", "name"))
    if not file_id or not name:
        raise QuarkError("夸克目录包含无效文件项")
    is_dir = bool(item.get("dir")) or bool(item.get("is_dir")) or str(item.get("file_type", "")).lower() in {"0", "folder", "dir"}
    try:
        size = int(item.get("size") or item.get("file_size") or 0)
    except (TypeError, ValueError):
        size = 0
    return QuarkFile(
        file_id=file_id,
        parent_id=_first_text(item, ("pdir_fid", "parent_id", "pid")),
        name=name,
        size=size,
        is_dir=is_dir,
        sha1=_first_text(item, ("sha1", "file_sha1")).upper(),
        md5=_first_text(item, ("md5", "file_md5")).lower(),
    )


def _normalize_share_file(item: dict[str, Any], parent_id: str) -> QuarkShareFile:
    file = _normalize_file(item)
    return QuarkShareFile(
        file_id=file.file_id,
        parent_id=file.parent_id or parent_id,
        name=file.name,
        size=file.size,
        is_dir=file.is_dir,
        share_fid_token=_first_text(item, ("share_fid_token", "fid_token")),
    )


def _share_data(payload: dict[str, Any], error: str) -> dict[str, Any]:
    status = str(payload.get("status") or "")
    code = str(payload.get("code") or "")
    if status and status not in {"200", "0"} and code not in {"0", "200"}:
        raise QuarkError(error)
    data = _nested_dict(payload, ("data",))
    if data is None:
        raise QuarkError(error)
    return data


def _command_data(payload: dict[str, Any], error: str) -> dict[str, Any]:
    status = str(payload.get("status") or "")
    code = str(payload.get("code") or "")
    if (status and status not in {"200", "0"}) or (code and code not in {"0", "200"}):
        raise QuarkError(error)
    data = _nested_dict(payload, ("data",))
    return data if data is not None else {}


def _download_link_values(payload: dict[str, Any]) -> list[dict[str, Any]]:
    status = str(payload.get("status") or "")
    code = str(payload.get("code") or "")
    if (status and status not in {"200", "0"}) or (code and code not in {"0", "200"}):
        raise QuarkError("夸克下载链接获取失败")
    data = payload.get("data")
    values = data if isinstance(data, list) else data.get("list") if isinstance(data, dict) else []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _safe_share_id(value: str) -> bool:
    return bool(value) and len(value) <= 128 and all(char.isalnum() or char in {"-", "_"} for char in value)


def _safe_file_id(value: str) -> str:
    raw = str(value or "").strip()
    return raw if _safe_share_id(raw) else ""


def _safe_quark_download_url(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not hostname.endswith(".quark.cn"):
        return ""
    return raw


def _safe_cloud_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw.startswith("/"):
        raise QuarkError("夸克目标目录必须是绝对路径")
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part in {".", ".."} or any(char in part for char in "<>\\:\"|?*") for part in parts):
        raise QuarkError("夸克目标目录无效")
    return "/" + "/".join(parts)


def _safe_file_name(value: str) -> str:
    name = str(value or "").strip()
    if not name or name in {".", ".."} or len(name) > 255 or any(char in name for char in "<>\\/:\"|?*"):
        raise QuarkError("夸克文件名无效")
    return name
