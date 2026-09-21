from __future__ import annotations

import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_ENV_FILE_LOCK = threading.RLock()
# python-dotenv (used by pydantic-settings) strips surrounding whitespace and
# treats a leading quote or an inline ``#`` as syntax, so exactly those values
# are written double quoted.  JSON lists stay readable instead of being escaped.
_INLINE_COMMENT_MARKER = "#"
_VALUE_LEADING_QUOTES = ('"', "'")
_LINE_BREAKS = ("\r", "\n")
_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "r": "\r"}


@contextmanager
def env_file_lock() -> Iterator[None]:
    """Serialize read-modify-write operations on the runtime config file."""
    with _ENV_FILE_LOCK:
        yield


def encode_env_value(value: object) -> str:
    """Render one env-file value so a read-back returns exactly this value.

    Most values stay ``key=value``.  A value that the runtime would otherwise
    read back differently - because it carries leading/trailing whitespace, a
    ``#``, a quote, a backslash or a line break - is double quoted and escaped.
    """
    text = "" if value is None else str(value)
    if not text:
        return ""
    if (
        text == text.strip()
        and text[0] not in _VALUE_LEADING_QUOTES
        and _INLINE_COMMENT_MARKER not in text
        and not any(marker in text for marker in _LINE_BREAKS)
    ):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n") + '"'


def decode_env_value(raw: str) -> str:
    """Return the value a reader must see for one env-file line remainder."""
    text = str(raw)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return _unescape_env_value(text[1:-1])
    return text


def _unescape_env_value(text: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        replacement = _ESCAPES.get(following) if char == "\\" else None
        if replacement is None:
            decoded.append(char)
            index += 1
            continue
        decoded.append(replacement)
        index += 2
    return "".join(decoded)


def read_env_file(path: Path) -> dict[str, str]:
    """Read a runtime env file into decoded ``key -> value`` pairs."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, raw = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = decode_env_value(raw.strip())
    return values


def atomic_write_env(path: Path, values: dict[str, str], ordered_keys: list[str] | None = None) -> None:
    """Replace an env file atomically without exposing a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = ordered_keys or []
    requested = set(ordered)
    keys = [key for key in ordered if key in values]
    keys.extend(sorted(key for key in values if key not in requested))
    content = "\n".join(f"{key}={encode_env_value(values[key])}" for key in keys) + "\n"
    _back_up_env_file(path)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.chmod(temporary_name, 0o600)
        except OSError:
            pass
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
    _verify_env_file(path, values)


def _back_up_env_file(path: Path) -> None:
    """Keep the previous content beside the file so a bad write is recoverable."""
    if not path.is_file():
        return
    try:
        backup = path.with_name(f"{path.name}.bak")
        shutil.copyfile(path, backup)
        os.chmod(backup, 0o600)
    except OSError:
        # Losing the backup copy must not block the settings the user asked to save.
        return


def _verify_env_file(path: Path, expected: dict[str, str]) -> None:
    """Fail loudly when the file on disk does not read back as what we wrote."""
    written = read_env_file(path)
    expected_keys = {str(key) for key in expected}
    if set(written) != expected_keys:
        raise RuntimeError("环境文件写入校验失败：写入的键与回读结果不一致")
    for key, value in expected.items():
        if written[str(key)] != ("" if value is None else str(value)):
            raise RuntimeError(f"环境文件写入校验失败：{key} 回读值与写入值不一致")
