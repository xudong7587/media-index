from __future__ import annotations

from dataclasses import dataclass

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.core.config import get_settings


class StrmInteractionError(ValueError):
    pass


@dataclass(frozen=True)
class StrmRootDirectory:
    provider: str
    name: str
    path: str


@dataclass(frozen=True)
class StrmDirectoryFailure:
    provider: str
    message: str


def list_strm_root_directories() -> tuple[list[StrmRootDirectory], list[StrmDirectoryFailure]]:
    settings = get_settings()
    if not settings.strm_output_root.strip():
        raise StrmInteractionError("STRM 输出目录尚未配置")
    directories: list[StrmRootDirectory] = []
    failures: list[StrmDirectoryFailure] = []
    enabled = False
    for provider in ("p115", "quark"):
        if not bool(getattr(settings, f"{provider}_strm_enabled", False)):
            continue
        enabled = True
        try:
            root_path = normalize_strm_cloud_path(settings.provider_strm_source_root(provider))
            if provider == "p115":
                client = P115Client(settings)
                directory_id = client.directory_id(root_path)
                if directory_id == "0" and root_path != "/":
                    raise P115Error("STRM 来源根目录不存在")
            else:
                client = QuarkClient(settings)
                directory_id = client.directory_id(root_path)
                if not directory_id:
                    raise QuarkError("STRM 来源根目录不存在")
            names = sorted(
                {
                    str(item.name).strip()
                    for item in client.list_directory(directory_id)
                    if item.is_dir and _safe_directory_name(str(item.name))
                },
                key=str.casefold,
            )
            directories.extend(
                StrmRootDirectory(
                    provider=provider,
                    name=name,
                    path=f"/{name}" if root_path == "/" else f"{root_path}/{name}",
                )
                for name in names
            )
        except (P115Error, QuarkError, StrmInteractionError) as exc:
            failures.append(StrmDirectoryFailure(provider=provider, message=str(exc)))
        except Exception as exc:
            failures.append(
                StrmDirectoryFailure(provider=provider, message=f"目录读取失败（{type(exc).__name__}）")
            )
    if not enabled:
        raise StrmInteractionError("没有已启用 STRM 生成的网盘")
    return directories, failures


def validate_strm_direct_child(root_path: str, selected_path: str) -> tuple[str, str]:
    root = normalize_strm_cloud_path(root_path)
    selected = normalize_strm_cloud_path(selected_path)
    prefix = "/" if root == "/" else f"{root}/"
    relative_path = selected[len(prefix):] if selected.startswith(prefix) else ""
    if not relative_path or "/" in relative_path:
        raise StrmInteractionError("只能扫描 STRM 来源根目录下的一级子目录")
    return root, selected


def normalize_strm_cloud_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw.startswith("/") or any(character in raw for character in "\r\n\x00"):
        raise StrmInteractionError("STRM 扫描目录必须是绝对路径")
    parts = [part for part in raw.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise StrmInteractionError("STRM 扫描目录不能包含 . 或 ..")
    return "/" + "/".join(parts) if parts else "/"


def _safe_directory_name(value: str) -> bool:
    name = str(value or "").strip()
    return bool(
        name
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
        and not any(character in name for character in "\r\n\x00")
    )
