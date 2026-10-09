from pathlib import Path
import logging
import json
import subprocess
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import transcode
from app.services.playback import PlaybackError
from transcoder import app as worker
from app.services.transcode import TranscodeAccessLogFilter


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("TRANSCODE_WORKER_URL", "http://worker:8098")
    monkeypatch.setenv("TRANSCODE_WORKER_KEY", "k" * 32)
    app = FastAPI()
    app.include_router(transcode.router)
    return TestClient(app)


def test_invalid_asset_never_reaches_worker(gateway, monkeypatch):
    def reject(token):
        raise PlaybackError("invalid")
    monkeypatch.setattr(transcode, "verify_asset_token", reject)
    call = Mock()
    monkeypatch.setattr(transcode, "call_worker", call)
    assert gateway.post("/api/transcode/sessions", json={"assetToken": "bad", "profile": "4k"}).status_code == 403
    call.assert_not_called()


@pytest.mark.parametrize("delivery", ["live", "vod"])
def test_session_contract_keeps_public_origin(gateway, monkeypatch, delivery):
    monkeypatch.setattr(transcode, "verify_asset_token", lambda token: {"provider": "p115"})
    result = {"sessionId": "a" * 32, "sessionToken": "secret", "playlistUrl": "http://worker/internal"}
    call = Mock(return_value=Mock(json=lambda: result.copy()))
    monkeypatch.setattr(transcode, "call_worker", call)
    response = gateway.post("/api/transcode/sessions", json={"assetToken": "valid", "profile": "1080p", "startPositionMs": 123000, "delivery": delivery})
    assert response.status_code == 200
    assert response.json()["playlistUrl"] == "/api/transcode/sessions/" + "a" * 32 + "/index.m3u8?st=secret"
    assert call.call_args.kwargs["payload"]["delivery"] == delivery


def test_worker_source_auth_before_cloud_access(gateway, monkeypatch):
    call = Mock()
    monkeypatch.setattr(transcode, "open_playback_stream", call)
    assert gateway.get("/api/transcode/source/token").status_code == 403
    call.assert_not_called()


def test_source_disconnect_releases_upstream_and_uses_consistent_ua(gateway, monkeypatch):
    import anyio
    from starlette.requests import Request
    closed = []
    def chunks():
        try:
            while True:
                yield b"media"
        finally:
            closed.append(True)
    body = chunks()
    # A pending yield models a stream that was opened before disconnect.
    next(body)
    call = Mock(return_value=Mock(status_code=206, headers={}, chunks=body))
    monkeypatch.setattr(transcode, "open_playback_stream", call)
    scope = {"type": "http", "method": "GET", "headers": [(b"authorization", b"Bearer " + b"k" * 32)],
             "asgi": {"spec_version": "2.0"}}
    response = transcode.worker_source("signed-token", Request(scope))
    async def receive():
        return {"type": "http.disconnect"}
    async def send(message):
        await anyio.sleep(0)
    async def run():
        await response(scope, receive, send)
    anyio.run(run)
    assert closed == [True]
    assert call.call_args.args[2] == transcode.P115Client.PLAYBACK_USER_AGENT


def test_source_provider_error_never_logs_private_values(gateway, monkeypatch, caplog):
    monkeypatch.setattr(transcode, "open_playback_stream", Mock(side_effect=PlaybackError("Cookie private-cookie https://private/source")))
    with caplog.at_level(logging.WARNING):
        response = gateway.get("/api/transcode/source/token", headers={"Authorization": "Bearer " + "k" * 32})
    assert response.status_code == 409
    assert "private-cookie" not in caplog.text and "https://private" not in caplog.text
    assert "provider_or_asset_failure" in caplog.text


def test_disabled_worker_and_path_traversal(gateway, monkeypatch):
    monkeypatch.delenv("TRANSCODE_WORKER_URL")
    assert gateway.get("/api/transcode/capabilities").json() == {"available": False, "profiles": []}
    assert gateway.get("/api/transcode/sessions/invalid/index.m3u8").status_code == 404
    assert gateway.get("/api/transcode/sessions/" + "a" * 32 + "/secret.env").status_code == 404


def test_worker_auth_and_segment_token(monkeypatch, tmp_path):
    manager = worker.Manager()
    manager.key = "k" * 32
    sid = "a" * 32
    folder = tmp_path / sid
    folder.mkdir()
    (folder / "index.m3u8").write_text("#EXTM3U\n#EXTINF:4,\nsegment000000.ts\n")
    process = Mock(poll=lambda: None)
    manager.sessions[sid] = {"token": "session-secret", "folder": folder, "process": process, "touched": worker.time.monotonic()}
    monkeypatch.setattr(worker, "manager", manager)
    client = TestClient(worker.app)
    route = f"/sessions/{sid}/index.m3u8"
    assert client.get(route).status_code == 403
    headers = {"Authorization": "Bearer " + manager.key, "X-Session-Token": "wrong"}
    assert client.get(route, headers=headers).status_code == 404
    headers["X-Session-Token"] = "session-secret"
    response = client.get(route, headers=headers)
    assert "segment000000.ts?st=session-secret" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_completed_encode_retained_until_expiry(tmp_path):
    manager = worker.Manager()
    folder = tmp_path / "a"
    folder.mkdir()
    process = Mock(poll=lambda: 0)
    manager.sessions["a"] = {"folder": folder, "process": process, "touched": worker.time.monotonic(), "token": "t"}
    manager.clean()
    assert "a" in manager.sessions
    manager.sessions["a"]["touched"] -= 91
    manager.clean()
    assert not folder.exists() and not manager.sessions


def test_capacity_includes_pending_probe(monkeypatch):
    manager = worker.Manager()
    manager.pending = manager.capacity
    monkeypatch.setattr(manager, "available", lambda: True)
    with pytest.raises(worker.HTTPException) as exc:
        manager.create(worker.CreateSession(assetToken="token", profile="4k"))
    assert exc.value.status_code == 429


def test_probe_failure_releases_reservation(monkeypatch):
    manager = worker.Manager()
    monkeypatch.setattr(manager, "available", lambda: True)
    monkeypatch.setattr(worker.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("ffprobe", 20)))
    with pytest.raises(worker.HTTPException) as exc:
        manager.create(worker.CreateSession(assetToken="token", profile="4k"))
    assert exc.value.status_code == 502
    assert manager.pending == 0 and not manager.sessions


def test_no_upscale_and_hardware_command():
    assert worker.output_size(7680, 4320, "4k") == (3840, 2160)
    assert worker.output_size(1280, 720, "4k") == (1280, 720)
    assert worker.output_size(1920, 800, "1080p") == (1920, 800)
    cmd = worker.encode_command("http://mediaindex/source", "header", Path("cache"), (3840,2160), 15000000, 123000)
    assert cmd[cmd.index("-ss") + 1] == "123.0"
    assert cmd[cmd.index("-c:v") + 1] == "av1"
    assert "h264_vaapi" in cmd
    assert "delete_segments+temp_file+independent_segments" in cmd
    assert "-readrate" in cmd


def test_1440p_and_aligned_master_command():
    assert worker.output_size(7680, 4320, "1440p") == (2560, 1440)
    assert worker.output_size(1920, 1080, "1440p") == (1920, 1080)
    command = worker.adaptive_command("source", "headers", Path("cache"), 7680, 4320, 0, True)
    assert "v:0,a:0 v:1,a:1 v:2,a:2 v:3,a:3" in command
    assert "index.m3u8" in command
    assert "[0:v:0]split=4[in0][in1][in2][in3]" in command[command.index("-filter_complex") + 1]


def test_access_logs_never_emit_source_or_session_credential():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s",
        ("client", "GET", "/api/transcode/source/private-asset-token?st=private-session-token", "1.1", 200), None)
    TranscodeAccessLogFilter().filter(record)
    assert "private-asset-token" not in record.getMessage()
    assert "private-session-token" not in record.getMessage()


def test_master_auth_is_carried_to_every_variant(monkeypatch, tmp_path):
    manager = worker.Manager()
    manager.key = "k" * 32
    sid = "a" * 32
    folder = tmp_path / sid
    folder.mkdir()
    (folder / "index.m3u8").write_text("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=9000000,RESOLUTION=1920x1080\nvariant2.m3u8\n")
    manager.sessions[sid] = {"token": "secret", "folder": folder, "process": Mock(poll=lambda: None), "touched": worker.time.monotonic()}
    monkeypatch.setattr(worker, "manager", manager)
    response = TestClient(worker.app).get(f"/sessions/{sid}/index.m3u8", headers={"Authorization": "Bearer " + manager.key,"X-Session-Token": "secret"})
    assert "RESOLUTION=1920x1080" in response.text
    assert "variant2.m3u8?st=secret" in response.text


def test_pause_freezes_and_stop_unfreezes_process(monkeypatch, tmp_path):
    manager = worker.Manager()
    manager.key = "k" * 32
    sid = "a" * 32
    folder = tmp_path / sid
    folder.mkdir()
    process = Mock(poll=lambda: None)
    manager.sessions[sid] = {"token": "secret", "folder": folder, "process": process, "touched": worker.time.monotonic()}
    monkeypatch.setattr(worker, "manager", manager)
    monkeypatch.setattr(worker.signal, "SIGSTOP", 19, raising=False)
    monkeypatch.setattr(worker.signal, "SIGCONT", 18, raising=False)
    headers = {"Authorization": "Bearer " + manager.key, "X-Session-Token": "secret"}
    client = TestClient(worker.app)
    assert client.post(f"/sessions/{sid}/pause", headers=headers).json() == {"paused": True}
    assert process.send_signal.call_args.args == (19,)
    assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 200
    assert process.send_signal.call_args.args == (18,)
    process.terminate.assert_called_once()
    assert not folder.exists()


def test_gateway_worker_session_playlist_segment_and_stop(gateway, monkeypatch, tmp_path):
    """Real HTTP adapters on both sides; only the cloud and FFmpeg process are fakes."""
    manager = worker.Manager()
    manager.key = "k" * 32
    manager.base = "http://mediaindex:8097"
    manager.root = tmp_path
    monkeypatch.setattr(manager, "available", lambda: True)
    monkeypatch.setattr(worker, "manager", manager)
    monkeypatch.setattr(transcode, "verify_asset_token", lambda token: {"provider": "p115"})
    metadata = {"streams": [{"codec_type": "video", "codec_name": "av1", "width": 7680, "height": 4320}], "format": {"duration": "1000"}}
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **kw: Mock(stdout=json.dumps(metadata).encode()))
    def launch(command, **kwargs):
        folder = Path(command[-1]).parent
        (folder / "index.m3u8").write_text("#EXTM3U\n#EXTINF:4,\nsegment000000.ts\n")
        (folder / "segment000000.ts").write_bytes(b"fixture-segment")
        return Mock(poll=lambda: None)
    monkeypatch.setattr(worker.subprocess, "Popen", launch)
    worker_client = TestClient(worker.app)
    class Transport:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, method, url, **kwargs):
            return worker_client.request(method, url.replace("http://worker:8098", ""), **kwargs)
    monkeypatch.setattr(transcode.service.httpx, "Client", Transport)
    response = gateway.post("/api/transcode/sessions", json={"assetToken": "signed-token", "profile": "1440p", "startPositionMs": 300000})
    assert response.status_code == 200
    session = response.json()
    assert (session["width"], session["height"]) == (2560,1440)
    assert session["startPositionMs"] == 300000
    playlist = gateway.get(session["playlistUrl"])
    assert playlist.status_code == 200
    segment = playlist.text.splitlines()[-1]
    base = session["playlistUrl"].split("index.m3u8")[0]
    assert gateway.get(base + segment).content == b"fixture-segment"
    head = gateway.head(base + segment)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(b"fixture-segment"))
    assert gateway.get(base + "segment000000.ts?st=wrong").status_code == 404
    control = base.rstrip("/") + "?st=" + session["sessionToken"]
    assert gateway.delete(control).status_code == 200
    assert not manager.sessions
def test_diagnostic_source_paths_hide_signed_asset_tokens():
    from app.services.transcode import redact_transcode_path
    assert redact_transcode_path('/api/transcode/source/private-token') == '/api/transcode/source/[redacted]'
    assert redact_transcode_path('/api/transcode/buffer/source/private-token') == '/api/transcode/buffer/source/[redacted]'
    assert redact_transcode_path('/api/transcode/capabilities') == '/api/transcode/capabilities'
