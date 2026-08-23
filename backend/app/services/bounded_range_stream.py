from __future__ import annotations

import io
from collections.abc import Callable, Iterator


class RangeStreamError(RuntimeError):
    """A source stream did not satisfy the bounded-range contract."""


RangeReader = Callable[[int, int, int], bytes]


class BoundedRangeStream(io.RawIOBase):
    """Seekable, read-only stream backed by bounded remote range reads.

    The class intentionally owns no path and never creates a temporary file.
    ``read_range`` receives inclusive start/end positions and a hard byte cap;
    each ``read`` therefore has one bounded in-memory response.  It is suitable
    for SDKs that require a file-like upload source while retaining the ability
    to retry or seek to a multipart boundary.
    """

    def __init__(
        self,
        size: int,
        read_range: RangeReader,
        *,
        buffer_bytes: int = 8 * 1024 * 1024,
        on_read: Callable[[int], None] | None = None,
    ) -> None:
        if size < 0:
            raise RangeStreamError("远端文件大小无效")
        if buffer_bytes <= 0:
            raise RangeStreamError("流式缓冲上限无效")
        self._size = int(size)
        self._read_range = read_range
        self._buffer_bytes = int(buffer_bytes)
        self._on_read = on_read
        self._position = 0
        self._closed = False

    @property
    def buffer_bytes(self) -> int:
        return self._buffer_bytes

    def readable(self) -> bool:
        return not self._closed

    def seekable(self) -> bool:
        return not self._closed

    def writable(self) -> bool:
        return False

    def tell(self) -> int:
        self._ensure_open()
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self._ensure_open()
        origin = 0 if whence == io.SEEK_SET else self._position if whence == io.SEEK_CUR else self._size if whence == io.SEEK_END else None
        if origin is None:
            raise ValueError("无效的 seek 起点")
        destination = origin + int(offset)
        if destination < 0:
            raise ValueError("不能 seek 到文件开头之前")
        self._position = min(destination, self._size)
        return self._position

    def read(self, size: int = -1) -> bytes:
        self._ensure_open()
        if self._position >= self._size:
            return b""
        requested = self._size - self._position if size is None or size < 0 else min(int(size), self._size - self._position)
        requested = min(requested, self._buffer_bytes)
        if requested <= 0:
            return b""
        start = self._position
        end = start + requested - 1
        data = self._read_range(start, end, self._buffer_bytes)
        if not isinstance(data, bytes) or len(data) != requested:
            raise RangeStreamError("远端范围读取长度与请求不一致")
        self._position += len(data)
        if self._on_read:
            self._on_read(self._position)
        return data

    def readinto(self, buffer: bytearray | memoryview) -> int:
        view = memoryview(buffer).cast("B")
        data = self.read(len(view))
        view[: len(data)] = data
        return len(data)

    def close(self) -> None:
        self._closed = True
        super().close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("I/O operation on closed stream")


def iter_range_chunks(size: int, read_range: RangeReader, *, chunk_bytes: int = 8 * 1024 * 1024) -> Iterator[bytes]:
    """Yield every remote byte exactly once, with the same bounded contract."""
    with BoundedRangeStream(size, read_range, buffer_bytes=chunk_bytes) as stream:
        while chunk := stream.read(chunk_bytes):
            yield chunk
