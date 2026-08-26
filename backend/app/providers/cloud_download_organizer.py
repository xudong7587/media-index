from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.core.config import Settings


ORGANIZER_PROVIDER_ERRORS = (P115Error, QuarkError)


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
        return self.client.directory_id_complete(path)

    def ensure_directory(self, path: str) -> str:
        return self.client.ensure_directory(path)

    def list_directory(self, directory_id: str) -> tuple[RemoteEntry, ...]:
        return tuple(
            RemoteEntry(item.file_id, item.parent_id, item.name, item.size, item.is_dir)
            for item in self.client.list_directory_complete(directory_id)
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
