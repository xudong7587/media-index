import json
from pathlib import Path
import re
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from transcoder import app as worker, vod


@pytest.fixture
def vod_session(monkeypatch, tmp_path):
    manager = worker.Manager()
    manager.key = "k" * 32
    manager.base = "http://mediaindex:8097"
    manager.root = tmp_path
    monkeypatch.setattr(worker, "manager", manager)
    monkeypatch.setattr(manager, "available", lambda: True)
    metadata = {"streams": [{"codec_type": "video", "codec_name": "av1", "width": 7680, "height": 4320}], "format": {"duration": "1000.5"}}
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **kw: Mock(stdout=json.dumps(metadata).encode()))
    launch = Mock()
    def encode(command, **kwargs):
        first = int(command[command.index("-start_number") + 1])
        template = command[command.index("-hls_segment_filename") + 1]
        for index in range(first, first + 4):
            Path(template.replace("%06d", f"{index:06d}")).write_bytes(f"segment-{index}".encode())
        return Mock(poll=lambda: None)
    launch.side_effect = encode
    monkeypatch.setattr(worker.subprocess, "Popen", launch)
    client = TestClient(worker.app)
    headers = {"Authorization": "Bearer " + manager.key}
    response = client.post("/sessions", headers=headers,
        json={"assetToken": "token", "profile": "1080p", "delivery": "vod", "startPositionMs": 300000})
    assert response.status_code == 200
    session = response.json()
    headers["X-Session-Token"] = session["sessionToken"]
    return client, manager, session, headers, launch


def test_vod_lists_full_duration_without_starting_encoder(vod_session):
    client, manager, session, headers, launch = vod_session
    response = client.get(f"/sessions/{session['sessionId']}/index.m3u8", headers=headers)
    assert session["seekMode"] == "hls-vod"
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in response.text and "#EXT-X-ENDLIST" in response.text
    durations = [float(x) for x in re.findall(r"#EXTINF:([\d.]+)", response.text)]
    assert sum(durations) == pytest.approx(1000.5)
    assert len(durations) == 251 and durations[-1] == .5
    assert "v2segment000000.ts?st=" in response.text
    launch.assert_not_called()


def test_hdr_session_carries_mapping_to_sought_vod_batch(vod_session, monkeypatch):
    client, manager, session, headers, launch = vod_session
    client.delete(f"/sessions/{session['sessionId']}", headers=headers)
    metadata = {'streams': [{'codec_type': 'video', 'codec_name': 'hevc', 'width': 3840,
                            'height': 2160, 'color_transfer': 'smpte2084'}], 'format': {'duration': '1000'}}
    monkeypatch.setattr(worker.subprocess, 'run', lambda *a, **kw: Mock(stdout=json.dumps(metadata).encode()))
    response = client.post('/sessions', headers={'Authorization': 'Bearer ' + manager.key},
                           json={'assetToken': 'token', 'profile': '720p', 'delivery': 'vod'})
    assert response.status_code == 200
    current = response.json()
    assert current['colorMode'] == 'hdr-to-sdr'
    headers['X-Session-Token'] = current['sessionToken']
    assert client.get(f"/sessions/{current['sessionId']}/v3segment000016.ts", headers=headers).status_code == 200
    command = launch.call_args.args[0]
    assert 'tin=smpte2084' in command[command.index('-vf') + 1]
    assert command[command.index('-color_trc') + 1] == 'bt709'


def test_selected_bitrate_reaches_vod_encoder(vod_session):
    client, manager, session, headers, launch = vod_session
    assert client.delete(f"/sessions/{session['sessionId']}", headers=headers).status_code == 200
    response = client.post("/sessions", headers={"Authorization": "Bearer " + manager.key},
                           json={"assetToken": "token", "profile": "4k", "videoBitrate": 10000000, "delivery": "vod"})
    assert response.status_code == 200
    current = response.json()
    assert (current["width"], current["height"]) == (3840, 2160)
    assert client.get(f"/sessions/{current['sessionId']}/v0segment000000.ts",
                     headers={**headers, "X-Session-Token": current["sessionToken"]}).status_code == 200
    command = launch.call_args.args[0]
    assert command[command.index("-b:v") + 1] == "10000000"
    assert command[command.index("-maxrate") + 1] == "10000000"


def test_seek_generates_only_requested_batch_and_cache_is_reused(vod_session):
    client, manager, session, headers, launch = vod_session
    base = f"/sessions/{session['sessionId']}/"
    assert client.get(base + "v2segment000040.ts", headers=headers).content == b"segment-40"
    command = launch.call_args.args[0]
    assert command[command.index("-ss") + 1] == "160"
    assert command[command.index("-t") + 1] == "16"
    assert "-readrate" not in command
    assert command[command.index("-output_ts_offset") + 1] == "160"
    assert len(list(manager.sessions[session["sessionId"]]["folder"].glob("*.ts"))) == 4
    assert client.get(base + "v2segment000041.ts", headers=headers).content == b"segment-41"
    assert launch.call_count == 1


def test_vod_rejects_out_of_range_or_other_profile_without_encoding(vod_session):
    client, manager, session, headers, launch = vod_session
    base = f"/sessions/{session['sessionId']}/"
    assert client.get(base + "variant0.m3u8", headers=headers).status_code == 404
    assert client.get(base + "v0segment000000.ts", headers=headers).status_code == 404
    assert client.get(base + "v2segment000251.ts", headers=headers).status_code == 404
    launch.assert_not_called()


def test_vod_pause_keeps_idle_session_and_expiry_cleans_it(vod_session):
    client, manager, session, headers, launch = vod_session
    sid = session["sessionId"]
    assert client.post(f"/sessions/{sid}/pause", headers=headers).json() == {"paused": True}
    manager.sessions[sid]["touched"] -= 1800
    manager.clean()
    assert sid in manager.sessions
    manager.sessions[sid]["touched"] -= 1801
    folder = manager.sessions[sid]["folder"]
    manager.clean()
    assert sid not in manager.sessions and not folder.exists()


def test_new_seek_cancels_previous_batch(vod_session):
    client, manager, session, headers, launch = vod_session
    base = f"/sessions/{session['sessionId']}/"
    client.get(base + "v2segment000000.ts", headers=headers)
    previous = manager.sessions[session["sessionId"]]["process"]
    client.get(base + "v2segment000080.ts", headers=headers)
    previous.terminate.assert_called_once()
    assert launch.call_count == 2


def test_master_advertises_actual_dimensions_and_all_variant_credentials():
    playlist = vod.master_playlist([(0,1920,1080,15000000),(1,1920,1080,10000000)], "token")
    assert playlist.count("RESOLUTION=1920x1080") == 2
    assert "variant0.m3u8?st=token" in playlist and "variant1.m3u8?st=token" in playlist
