from __future__ import annotations

import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_ENV_FILE_LOCK = threading.RLock()


@contextmanager
def env_file_lock() -> Iterator[None]:
    """Serialize read-modify-write operations on the runtime config file."""
    with _ENV_FILE_LOCK:
        yield


def atomic_write_env(path: Path, values: dict[str, str], ordered_keys: list[str] | None = None) -> None:
    """Replace an env file atomically without exposing a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = ordered_keys or []
    keys = [key for key in ordered if key in values]
    keys.extend(sorted(key for key in values if key not in set(ordered)))
    content = "\n".join(f"{key}={values[key]}" for key in keys) + "\n"
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
