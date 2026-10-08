"""Bounded raw-source block cache for the optional optimizer worker.

Only verified asset identities name cache files. Every access still checks the
current signed token. This cache saves repeated reads; it cannot create bandwidth.
"""
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
import time

from app.services.playback import PlaybackError, PlaybackStream, open_playback_stream, verify_asset_token

BLOCK = 4 * 1024 * 1024
_lock = RLock()
_metrics_lock = RLock()
_metrics = {}
_pending = set()
_prefetch = ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-prefetch")


def asset_key(asset):
    identity = {key: asset.get(key) for key in ("provider", "account_id", "file_id", "revision", "sha1", "size")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def buffer_status(token: str, source_bps: float, remaining_seconds: float, position_seconds: float | None = None) -> dict:
    asset = verify_asset_token(token)
    root = os.environ.get("TRANSCODE_SOURCE_CACHE_DIR", "")
    if not root:
        return {"state": "cache_disabled"}
    key = asset_key(asset)
    with _metrics_lock:
        data = dict(_metrics.get(key, {}))
    samples = data.get("samples", [])
    total_time = sum(sample[1] for sample in samples)
    total_bytes = sum(sample[0] for sample in samples)
    if total_time < 2 or total_bytes < BLOCK * 2:
        return {"state": "insufficient_samples"}
    position = int(position_seconds * source_bps / 8) if position_seconds is not None and source_bps > 0 else data.get("position", 0)
    buffered = 0
    offset = position // BLOCK * BLOCK
    while True:
        path = Path(root) / f"{key}-{offset}.block"
        try:
            size = path.stat().st_size
        except OSError:
            break
        buffered += max(0, size - max(0, position - offset))
        if size < BLOCK:
            break
        offset += BLOCK
    return {**estimate(source_bps, total_bytes * 8 / total_time, remaining_seconds, buffered),
            "downloadBitrate": round(total_bytes * 8 / total_time), "bufferedBytes": buffered}


def prefetch_on_pause(token: str) -> bool:
    asset = verify_asset_token(token)
    if not os.environ.get("TRANSCODE_SOURCE_CACHE_DIR"):
        return False
    key = asset_key(asset)
    with _metrics_lock:
        if key in _pending or len(_pending) >= 2 or key not in _metrics:
            return False
        start = _metrics[key].get("position", 0) // BLOCK * BLOCK
        end = min(int(asset.get("size") or 0) - 1, start + 64 * 1024**2 - 1)
        if end < start:
            return False
        _pending.add(key)
    def run():
        from app.clients.p115 import P115Client
        deadline = time.monotonic() + 120
        try:
            # Fetch individual blocks, leaving the actual playback cursor unchanged.
            for offset in range(start, end + 1, BLOCK):
                if time.monotonic() >= deadline:
                    break
                for _ in cached_stream(token, f"bytes={offset}-{min(end, offset+BLOCK-1)}", P115Client.PLAYBACK_USER_AGENT, prefetch=True).chunks:
                    pass
        except (PlaybackError, OSError, ValueError):
            pass
        finally:
            with _metrics_lock:
                _pending.discard(key)
    _prefetch.submit(run)
    return True


def estimate(source_bps: float, download_bps: float, duration_seconds: float, buffered_bytes: int) -> dict:
    if min(source_bps, download_bps, duration_seconds) <= 0:
        return {"state": "insufficient_samples"}
    buffered_seconds = max(0, buffered_bytes) * 8 / source_bps
    deficit = max(0, 1 - download_bps / source_bps)
    needed_seconds = duration_seconds * deficit
    return {"state": "sustainable" if deficit == 0 else "source_bandwidth_limited",
            "bufferedSeconds": round(buffered_seconds, 1),
            "estimatedContinuousSeconds": round(min(duration_seconds, buffered_seconds / deficit), 1) if deficit else duration_seconds,
            "estimatedWaitSeconds": round(max(0, needed_seconds - buffered_seconds) * source_bps / download_bps),
            "additionalBufferBytes": round(max(0, needed_seconds - buffered_seconds) * source_bps / 8),
            "estimateOnly": True}


def cached_stream(token: str, range_header: str, user_agent: str, *, prefetch: bool = False) -> PlaybackStream:
    asset = verify_asset_token(token)
    root_value = os.environ.get("TRANSCODE_SOURCE_CACHE_DIR", "")
    if not root_value:
        return open_playback_stream(token, range_header, user_agent)
    size = int(asset.get("size") or 0)
    if size <= 0:
        return open_playback_stream(token, range_header, user_agent)
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip()) if range_header else None
    if range_header and (not match or not any(match.groups())):
        raise PlaybackError("播放范围请求无效")
    start, end = 0, size - 1
    if match:
        if not match[1]:
            start = max(0, size - int(match[2]))
        else:
            start = int(match[1]); end = min(end, int(match[2])) if match[2] else end
    if start > end or start >= size:
        raise PlaybackError("播放范围超出文件长度")
    key = asset_key(asset)
    root = Path(root_value)
    quota = max(BLOCK, int(os.environ.get("TRANSCODE_SOURCE_CACHE_BYTES", str(8 * 1024**3))))

    def chunks():
        for offset in range(start // BLOCK * BLOCK, end + 1, BLOCK):
            verify_asset_token(token)
            length = min(BLOCK, size - offset)
            path = root / f"{key}-{offset}.block"
            # Serialize fills: prevents duplicate cloud reads and quota races.
            # Cached bytes are copied before yielding; eviction cannot break readers.
            with _lock:
                root.mkdir(parents=True, exist_ok=True)
                data = path.read_bytes() if path.exists() and path.stat().st_size == length else b""
                if len(data) != length:
                    started = time.monotonic()
                    stream = open_playback_stream(token, f"bytes={offset}-{offset + length - 1}", user_agent)
                    try:
                        if stream.status_code != 206:
                            raise PlaybackError("播放上游未返回有效分段范围")
                        payload = bytearray()
                        for chunk in stream.chunks:
                            payload.extend(chunk)
                            if len(payload) > length:
                                raise PlaybackError("播放上游分段长度与范围不一致")
                        data = bytes(payload)
                    finally:
                        stream.chunks.close()
                    if len(data) != length:
                        raise PlaybackError("播放上游分段长度与范围不一致")
                    with _metrics_lock:
                        if key not in _metrics and len(_metrics) >= 32:
                            _metrics.pop(next(iter(_metrics)))
                        record = _metrics.setdefault(key, {})
                        record["samples"] = (record.get("samples", []) + [(length, max(.001, time.monotonic()-started))])[-16:]
                    # A killed previous process may leave a partial fill. This
                    # directory has one process owner, so none is active here.
                    for partial in root.glob("*.part"):
                        partial.unlink(missing_ok=True)
                    files = sorted(root.glob("*.block"), key=lambda item: item.stat().st_mtime)
                    used = sum(item.stat().st_size for item in files)
                    for old in files:
                        if used + length <= quota:
                            break
                        used -= old.stat().st_size
                        old.unlink()
                    temporary = path.with_suffix(".part")
                    try:
                        temporary.write_bytes(data)
                        temporary.replace(path)
                    finally:
                        temporary.unlink(missing_ok=True)
                os.utime(path, (time.time(), time.time()))
            if not prefetch:
                with _metrics_lock:
                    if key in _metrics:
                        _metrics[key]["position"] = min(end+1, offset+length)
            yield data[max(0, start - offset):min(length, end - offset + 1)]

    headers = {"Content-Length": str(end - start + 1), "Accept-Ranges": "bytes", "Content-Type": "application/octet-stream"}
    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return PlaybackStream(206 if range_header else 200, headers, chunks())
