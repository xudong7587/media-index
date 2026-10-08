from unittest.mock import Mock
import pytest

from app.services import playback_cache as cache
from app.services.playback import PlaybackError, PlaybackStream


def test_cache_reuses_cloud_bytes_and_preserves_ranges(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCODE_SOURCE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSCODE_SOURCE_CACHE_BYTES", "8")
    monkeypatch.setattr(cache, "BLOCK", 4)
    monkeypatch.setattr(cache, "verify_asset_token", lambda _: {"provider": "p115", "file_id": "x", "revision": 1, "size": 12})
    raw = b"abcdefghijkl"
    def upstream(token, requested, ua):
        start, end = map(int, requested[6:].split("-"))
        return PlaybackStream(206, {}, (value for value in [raw[start:end+1]]))
    read = Mock(side_effect=upstream)
    monkeypatch.setattr(cache, "open_playback_stream", read)
    first = cache.cached_stream("valid", "bytes=2-6", "ua")
    assert first.headers["Content-Range"] == "bytes 2-6/12"
    assert b"".join(first.chunks) == b"cdefg"
    assert b"".join(cache.cached_stream("valid", "bytes=3-5", "ua").chunks) == b"def"
    assert read.call_count == 2
    assert b"".join(cache.cached_stream("valid", "bytes=-3", "ua").chunks) == b"jkl"
    assert sum(path.stat().st_size for path in tmp_path.glob("*.block")) <= 8


def test_cached_bytes_never_bypass_revoked_token(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCODE_SOURCE_CACHE_DIR", str(tmp_path))
    def denied(_):
        raise PlaybackError("revoked")
    monkeypatch.setattr(cache, "verify_asset_token", denied)
    with pytest.raises(PlaybackError):
        cache.cached_stream("revoked", "bytes=0-1", "ua")
    assert not list(tmp_path.iterdir())


def test_wait_estimate_explains_sustained_source_deficit():
    result = cache.estimate(25_000_000, 15_000_000, 3600, 187_500_000)
    assert result["bufferedSeconds"] == 60
    assert result["estimatedContinuousSeconds"] == 150
    assert result["estimatedWaitSeconds"] == 2300
    assert cache.estimate(25_000_000, 30_000_000, 3600, 0)["state"] == "sustainable"
    assert cache.estimate(0, 0, 3600, 0)["state"] == "insufficient_samples"


def test_prefetch_is_bounded_and_keeps_playback_cursor(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCODE_SOURCE_CACHE_DIR", str(tmp_path))
    asset = {"provider": "p115", "file_id": "prefetch", "size": 100 * 1024**2}
    monkeypatch.setattr(cache, "verify_asset_token", lambda _: asset)
    key = cache.asset_key(asset)
    monkeypatch.setattr(cache, "_metrics", {key: {"position": 5 * 1024**2}})
    monkeypatch.setattr(cache, "_pending", set())
    functions = []
    monkeypatch.setattr(cache, "_prefetch", type("Executor", (), {"submit": lambda self, fn: functions.append(fn)})())
    requested = []
    def read(token, byte_range, ua, *, prefetch=False):
        assert prefetch
        requested.append(byte_range)
        return PlaybackStream(206, {}, iter(()))
    monkeypatch.setattr(cache, "cached_stream", read)
    assert cache.prefetch_on_pause("valid")
    assert not cache.prefetch_on_pause("valid")
    functions[0]()
    assert len(requested) == 16
    assert requested[0] == f"bytes={4*1024**2}-{8*1024**2-1}"
    assert cache._metrics[key]["position"] == 5 * 1024**2
    assert not cache._pending


def test_original_cache_endpoint_verifies_asset_before_stream(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import transcode
    monkeypatch.setenv("TRANSCODE_SOURCE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(transcode.plugins, "enabled", lambda: True)
    def denied(_):
        raise PlaybackError("revoked")
    monkeypatch.setattr(transcode, "verify_asset_token", denied)
    read = Mock()
    monkeypatch.setattr(transcode, "cached_stream", read)
    app = FastAPI();app.include_router(transcode.router)
    assert TestClient(app).get("/api/transcode/buffer/source/revoked").status_code == 409
    read.assert_not_called()


def test_management_process_never_owns_raw_cache(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import transcode
    app = FastAPI();app.state.playback_cache_owner = False;app.include_router(transcode.router)
    read = Mock()
    monkeypatch.setattr(transcode, "cached_stream", read)
    client = TestClient(app)
    assert client.get("/api/transcode/buffer/source/token").status_code == 503
    assert client.post("/api/transcode/buffer/prefetch", json={"assetToken": "token"}).status_code == 503
    assert client.post("/api/transcode/buffer/status", json={"assetToken": "token"}).json()["reason"] == "use_playback_port"
    read.assert_not_called()


@pytest.mark.parametrize("model", ["gateway", "worker"])
def test_bitrate_validation_keeps_old_clients(model):
    from app.api.transcode import SessionRequest
    from transcoder.app import CreateSession
    cls = SessionRequest if model == "gateway" else CreateSession
    assert cls(assetToken="a", profile="4k").videoBitrate is None
    assert cls(assetToken="a", profile="4k", videoBitrate=20_000_000).videoBitrate == 20_000_000
    with pytest.raises(ValueError):
        cls(assetToken="a", profile="720p", videoBitrate=20_000_000)
