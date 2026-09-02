from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.core.config import Settings


ORGANIZER_PROVIDER_ERRORS = (P115Error, QuarkError)


def _transient_quark_read_error(exc: QuarkError) -> bool:
    message = str(exc).casefold()
    permanent_markers = ("cookie", "凭据", "授权失效", "权限不足", "http 400", "http 401", "http 403", "http 404")
    transient_markers = (
        "连接失败", "超时", "timed out", "timeout", "请求过于频繁",
        "http 429", "http 500", "http 502", "http 503", "http 504", "分页",
    )
    return not any(marker in message for marker in permanent_markers) and any(
        marker in message for marker in transient_markers
    )


def _retry_quark_read(operation):
    """Retry a transient Quark read once; provider mutations are never replayed."""
    try:
        return operation()
    except QuarkError as exc:
        if not _transient_quark_read_error(exc):
            raise
        time.sleep(0.75)
        try:
            return operation()
        except QuarkError as retry_exc:
            raise QuarkError(f"{retry_exc}（读取已重试 1 次）") from retry_exc


def _ensure_quark_directory(client: QuarkClient, path: str) -> str:
    """Create one exact path and reconcile an ambiguous network failure.

    A timed-out POST does not prove that Quark rejected the mkdir.  Blindly
    replaying it can create duplicate folders, while failing immediately leaves
    an otherwise valid organizer job stranded.  Read the exact absolute path
    first; replay the idempotent path creation only after that read proves the
    folder does not exist, then reconcile once more if the replay also loses
    its response.
    """
    try:
        return client.ensure_directory(path)
    except QuarkError as first_error:
        if not _transient_quark_read_error(first_error):
            raise
        first_failure = first_error

    time.sleep(0.75)
    try:
        existing_id = _retry_quark_read(lambda: client.directory_id_complete(path))
    except QuarkError as read_error:
        raise QuarkError(
            f"{first_failure}；创建结果复核失败：{read_error}，未重复提交建目录请求"
        ) from read_error
    if existing_id:
        return existing_id

    try:
        return client.ensure_directory(path)
    except QuarkError as retry_error:
        if not _transient_quark_read_error(retry_error):
            raise
        retry_failure = retry_error

    time.sleep(1.5)
    try:
        existing_id = _retry_quark_read(lambda: client.directory_id_complete(path))
    except QuarkError as read_error:
        raise QuarkError(
            f"{retry_failure}；重试后结果复核失败：{read_error}"
        ) from read_error
    if existing_id:
        return existing_id
    raise QuarkError(f"{retry_failure}（已复核目录仍不存在，建目录已重试 1 次）")


@dataclass(frozen=True)
class RemoteEntry:
    file_id: str
    parent_id: str
    name: str
    size: int = 0
    is_dir: bool = False
    relative_path: str = ""


class OrganizerProvider(Protocol):
    provider: str
    request_timeout_seconds: int

    def configured(self) -> bool: ...
    def directory_id(self, path: str) -> str: ...
    def ensure_directory(self, path: str) -> str: ...
    def list_directory(self, directory_id: str) -> tuple[RemoteEntry, ...]: ...
    def rename(self, pairs: list[tuple[str, str]]) -> None: ...
    def move(self, file_ids: list[str], destination_id: str) -> None: ...
    def copy(self, file_ids: list[str], destination_id: str) -> None: ...
    def trash(self, file_id: str) -> None: ...


class P115OrganizerProvider:
    provider = "p115"

    def __init__(self, client: P115Client) -> None:
        self.client = client
        self.request_timeout_seconds = int(client.settings.p115_request_timeout_seconds)

    def configured(self) -> bool:
        return self.client.configured()

    def directory_id(self, path: str) -> str:
        value = self.client.directory_id(path)
        raw_path = str(path or "").strip().replace("\\", "/")
        is_root = bool(raw_path) and not raw_path.strip("/")
        return "" if value == "0" and not is_root else value

    def ensure_directory(self, path: str) -> str:
        return self.client.ensure_directory(path)

    def list_directory(self, directory_id: str) -> tuple[RemoteEntry, ...]:
        return tuple(
            RemoteEntry(item.file_id, item.parent_id, item.name, item.size, item.is_dir)
            for item in self.client.list_directory_complete(directory_id)
        )

    def rename(self, pairs: list[tuple[str, str]]) -> None:
        self.client.rename(pairs)

    def move(self, file_ids: list[str], destination_id: str) -> None:
        self.client.move(file_ids, destination_id)

    def copy(self, file_ids: list[str], destination_id: str) -> None:
        self.client.copy(file_ids, destination_id)

    def trash(self, file_id: str) -> None:
        self.client.trash_file(file_id)


class QuarkOrganizerProvider:
    provider = "quark"

    def __init__(self, client: QuarkClient) -> None:
        self.client = client
        self.request_timeout_seconds = int(client.settings.quark_request_timeout_seconds)

    def configured(self) -> bool:
        return self.client.configured()

    def directory_id(self, path: str) -> str:
        return _retry_quark_read(lambda: self.client.directory_id_complete(path))

    def ensure_directory(self, path: str) -> str:
        return _ensure_quark_directory(self.client, path)

    def list_directory(self, directory_id: str) -> tuple[RemoteEntry, ...]:
        return tuple(
            RemoteEntry(item.file_id, item.parent_id, item.name, item.size, item.is_dir)
            for item in _retry_quark_read(lambda: self.client.list_directory_complete(directory_id))
        )

    def rename(self, pairs: list[tuple[str, str]]) -> None:
        for file_id, name in pairs:
            self.client.rename_file(file_id, name)

    def move(self, file_ids: list[str], destination_id: str) -> None:
        task_id = self.client.move_files(file_ids, destination_id)
        self.client.wait_task(task_id)

    def copy(self, file_ids: list[str], destination_id: str) -> None:
        self.client.copy_files(file_ids, destination_id)

    def trash(self, file_id: str) -> None:
        self.client.trash_files([file_id])


def organizer_provider(settings: Settings, provider: str) -> OrganizerProvider:
    if provider == "p115":
        return P115OrganizerProvider(P115Client(settings))
    if provider == "quark":
        return QuarkOrganizerProvider(QuarkClient(settings))
    raise ValueError("云下载整理只支持 115 或夸克")
