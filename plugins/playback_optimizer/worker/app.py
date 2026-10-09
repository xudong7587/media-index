"""Internal, separately versioned FFmpeg worker. Never expose its port publicly."""
import asyncio
import contextlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from urllib.parse import quote, urlsplit
import uuid

try:
    from . import vod, subtitles, hdr
    from .hardware import HardwareDetector
except ImportError:
    import vod  # Standalone container entry point.
    import subtitles
    import hdr
    from hardware import HardwareDetector

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

PROFILES = {"4k": (3840, 2160, 15000000), "1440p": (2560, 1440, 10000000), "1080p": (1920, 1080, 8000000), "720p": (1280, 720, 4000000)}
BITRATES = {"4k": (10000000, 15000000, 20000000), "1440p": (6000000, 10000000), "1080p": (4000000, 8000000), "720p": (2000000, 4000000)}


class CreateSession(BaseModel):
    assetToken: str = Field(pattern=r"^[A-Za-z0-9_-]{1,2048}$")
    profile: str = Field(pattern=r"^(4k|1440p|1080p|720p|adaptive)$")
    startPositionMs: int = Field(default=0, ge=0, le=604800000)
    delivery: str = Field(default="live", pattern=r"^(live|vod)$")
    videoBitrate: int | None = Field(default=None, ge=2000000, le=20000000)

    @model_validator(mode="after")
    def validate_bitrate(self):
        if self.videoBitrate is not None and self.videoBitrate not in BITRATES.get(self.profile, ()):
            raise ValueError("Unsupported bitrate for profile")
        return self


def output_size(width, height, profile):
    maximum_w, maximum_h, _ = PROFILES[profile]
    ratio = min(1, maximum_w / width, maximum_h / height)
    return max(2, int(width * ratio) // 2 * 2), max(2, int(height * ratio) // 2 * 2)


def encode_command(source, headers, folder, size, bitrate, start_ms, input_codec="av1", color_transfer=""):
    # argv only, no shell; readrate and rolling HLS bound storage and read-ahead.
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-filter_threads", "2", "-filter_complex_threads", "2",
            "-init_hw_device", "vaapi=va:/dev/dri/renderD128", "-hwaccel", "vaapi",
            "-hwaccel_output_format", "vaapi", "-rw_timeout", "15000000",
            "-format_whitelist", "mov,matroska,webm,mpegts,avi,flv",
            "-protocol_whitelist", "http,https,tcp,tls,crypto", "-headers", headers,
            "-ss", str(start_ms / 1000), "-readrate", "1", "-c:v", input_codec, "-i", source,
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
            "-vf", hdr.scale_filter(size, color_transfer),
            "-c:v", "h264_vaapi", "-profile:v", "high", "-b:v", str(bitrate),
            "-maxrate", str(bitrate), "-bufsize", str(bitrate * 2),
            "-force_key_frames", "expr:gte(t,n_forced*4)", "-c:a", "aac", "-ac", "2", "-b:a", "192k",
            *hdr.output_options(color_transfer),
            "-f", "hls", "-hls_time", "4", "-hls_list_size", "12", "-hls_delete_threshold", "3",
            "-hls_flags", "delete_segments+temp_file+independent_segments",
            "-hls_segment_filename", str(folder / "segment%06d.ts"), str(folder / "index.m3u8")]


def adaptive_command(source, headers, folder, width, height, start_ms, has_audio, input_codec="av1", color_transfer=""):
    """One decode, aligned renditions: a real HLS multivariant stream."""
    command = encode_command(source, headers, folder, (width, height), 15000000, start_ms, input_codec)
    command = command[:command.index("-map")]
    filters = ["[0:v:0]split=4[in0][in1][in2][in3]"]
    for index, profile in enumerate(PROFILES):
        w, h = output_size(width, height, profile)
        filters.append(f"[in{index}]{hdr.scale_filter((w, h), color_transfer)}[out{index}]")
    command += ["-filter_complex", ";".join(filters)]
    variants = []
    for index, profile in enumerate(PROFILES):
        command += ["-map", f"[out{index}]"]
        if has_audio:
            command += ["-map", "0:a:0"]
        bitrate = PROFILES[profile][2]
        command += [f"-c:v:{index}", "h264_vaapi", f"-profile:v:{index}", "high",
                    f"-b:v:{index}", str(bitrate), f"-maxrate:v:{index}", str(bitrate),
                    f"-bufsize:v:{index}", str(bitrate * 2),
                    f"-force_key_frames:v:{index}", "expr:gte(t,n_forced*4)"]
        variants.append(f"v:{index},a:{index}" if has_audio else f"v:{index}")
    command += ["-sn", "-dn", "-c:a", "aac", "-ac", "2", "-b:a", "192k", *hdr.output_options(color_transfer), "-f", "hls",
                "-hls_time", "4", "-hls_list_size", "12", "-hls_delete_threshold", "3",
                "-hls_flags", "delete_segments+temp_file+independent_segments",
                "-var_stream_map", " ".join(variants), "-master_pl_name", "index.m3u8",
                "-hls_segment_filename", str(folder / "v%vsegment%06d.ts"), str(folder / "variant%v.m3u8")]
    return command


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.sessions = {}
        self.pending = 0
        self.key = os.environ.get("TRANSCODE_WORKER_KEY", "")
        self.base = os.environ.get("MEDIAINDEX_SOURCE_BASE", "").rstrip("/")
        self.root = Path(os.environ.get("TRANSCODE_CACHE_DIR", "/cache"))
        self.capacity = max(1, min(4, int(os.environ.get("TRANSCODE_MAX_SESSIONS", "1"))))
        self.ttl = 90
        self.vod_ttl = 3600
        self.hardware = HardwareDetector()

    def available(self):
        parsed = urlsplit(self.base)
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{32,128}", self.key) and parsed.scheme in {"http", "https"} and parsed.netloc
                    and not parsed.username and not parsed.query and not parsed.fragment
                    and shutil.which("ffmpeg") and shutil.which("ffprobe") and self.hardware.probe()["available"])

    def clean(self):
        def cache_size(folder):
            total = 0
            for path in folder.glob("*"):
                try:
                    total += path.stat().st_size
                except FileNotFoundError:
                    pass  # FFmpeg removes rolling segments concurrently.
            return total
        with self.lock:
            expired = [sid for sid, s in self.sessions.items() if time.monotonic() - s["touched"] > (self.vod_ttl if s.get("delivery") == "vod" else self.ttl)
                       or (s.get("delivery") != "vod" and s["process"].poll() not in {None, 0})
                       or cache_size(s["folder"]) > 384 * 1024 * 1024]
            for sid in expired:
                self.stop(sid)

    def stop(self, sid):
        with self.lock:
            s = self.sessions.pop(sid, None)
            if not s:
                return
            process = s["process"]
            if process is not None and process.poll() is None:
                if s.get("paused"):
                    process.send_signal(signal.SIGCONT)
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            shutil.rmtree(s["folder"])

    def get(self, sid, token):
        if not re.fullmatch(r"[0-9a-f]{32}", sid):
            raise HTTPException(404, "Session not found")
        with self.lock:
            s = self.sessions.get(sid)
            if not s or not secrets.compare_digest(token.encode("utf-8"), s["token"].encode("utf-8")):
                raise HTTPException(404, "Session not found")
            if time.monotonic() - s["touched"] > (self.vod_ttl if s.get("delivery") == "vod" else self.ttl):
                self.stop(sid)
                raise HTTPException(404, "Session expired")
            s["touched"] = time.monotonic()
            return s

    def create(self, payload):
        if not self.available():
            raise HTTPException(503, "Hardware worker not configured")
        self.clean()
        with self.lock:
            if len(self.sessions) + self.pending >= self.capacity:
                raise HTTPException(429, "Worker capacity reached")
            self.pending += 1
        folder = None
        process = None
        try:
            source = self.base + "/api/transcode/source/" + quote(payload.assetToken, safe="")
            headers = "Authorization: Bearer " + self.key + "\r\n"
            probe = subprocess.run(["ffprobe", "-v", "error", "-rw_timeout", "15000000", "-headers", headers,
                "-format_whitelist", "mov,matroska,webm,mpegts,avi,flv",
                "-protocol_whitelist", "http,https,tcp,tls,crypto", "-show_streams", "-show_format", "-of", "json", source],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True)
            metadata = json.loads(probe.stdout)
            video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
            duration = float(metadata["format"]["duration"])
            if not math.isfinite(duration) or duration <= payload.startPositionMs / 1000:
                raise HTTPException(400, "Position outside source")
            if payload.delivery == "vod" and duration > 86400:
                raise HTTPException(400, "VOD source exceeds 24 hours")
            width, height = int(video["width"]), int(video["height"])
            if not (2 <= width <= 16384 and 2 <= height <= 16384):
                raise HTTPException(400, "Invalid source dimensions")
            color_transfer = video.get("color_transfer", "")
            if any(s.get('dv_profile') == 5 for s in video.get('side_data_list', [])):
                raise HTTPException(503, "Dolby Vision profile 5 tone mapping not supported")
            input_codec = video.get("codec_name")
            if input_codec not in {"av1", "h264", "hevc", "vp9"}:
                raise HTTPException(503, "Unsupported hardware source codec")
            if self.hardware.report.get("available") and input_codec not in self.hardware.report["decodeCodecs"]:
                raise HTTPException(503, "GPU does not support this source codec")
            size = output_size(width, height, "4k" if payload.profile == "adaptive" else payload.profile)
            sid, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
            self.root.mkdir(parents=True, exist_ok=True)
            folder = self.root / sid
            folder.mkdir()
            subtitle = subtitles.selected_track(metadata['streams'])
            if subtitle and subtitle.get('codec_name') not in subtitles.TEXT_CODECS | subtitles.BITMAP_CODECS:
                raise HTTPException(503, 'This subtitle format cannot yet be preserved')
            if subtitle and payload.delivery != 'vod':
                raise HTTPException(503, 'Subtitle-preserving playback requires VOD delivery')
            if subtitle and subtitle.get('codec_name') in subtitles.TEXT_CODECS:
                subtitles.extract_fonts(source, headers, metadata['streams'], folder)
            command = (adaptive_command(source, headers, folder, width, height, payload.startPositionMs,
                       any(s.get("codec_type") == "audio" for s in metadata["streams"]), input_codec, color_transfer) if payload.profile == "adaptive"
                       else encode_command(source, headers, folder, size, payload.videoBitrate or PROFILES[payload.profile][2], payload.startPositionMs, input_codec, color_transfer))
            if payload.delivery == "live":
                command[command.index("-init_hw_device") + 1] = "vaapi=va:" + self.hardware.report.get("device", "/dev/dri/renderD128")
                process = subprocess.Popen(command,
                                           env=self.hardware.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.lock:
                self.sessions[sid] = {"token": token, "folder": folder, "process": process, "touched": time.monotonic(),
                    "delivery": payload.delivery, "profile": payload.profile, "source": source, "headers": headers,
                    "videoBitrate": payload.videoBitrate,
                    "subtitle": subtitle,
                    "width": width, "height": height, "codec": input_codec, "duration": duration, "colorTransfer": color_transfer,
                    "batch": None, "generation": 0}
            return {"sessionId": sid, "sessionToken": token, "startPositionMs": payload.startPositionMs,
                    "durationMs": round(duration * 1000), "width": size[0], "height": size[1],
                    "sourceBitrate": max(0, int(metadata["format"].get("bit_rate") or 0)),
                    "subtitleMode": "burned" if subtitle else "none", "colorMode": "hdr-to-sdr" if hdr.needs_mapping(video) else "source",
                    "videoCodec": "h264", "audioCodec": "aac", "heartbeatSeconds": 30,
                    "seekMode": "hls-vod" if payload.delivery == "vod" else "restart-session",
                    "playlistType": "vod" if payload.delivery == "vod" else "sliding-live"}
        except HTTPException:
            raise
        except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
            raise HTTPException(502, "Source probe or encoder startup failed") from None
        finally:
            with self.lock:
                self.pending -= 1
            if folder and not any(s["folder"] == folder for s in self.sessions.values()):
                if process and process.poll() is None:
                    process.kill()
                    process.wait()
                shutil.rmtree(folder, ignore_errors=True)

    def vod_file(self, sid, session, filename):
        profiles = list(PROFILES)
        allowed = range(len(profiles)) if session["profile"] == "adaptive" else [profiles.index(session["profile"])]
        if filename == "index.m3u8":
            if session["profile"] == "adaptive":
                options = [(i, *output_size(session["width"], session["height"], profiles[i]), PROFILES[profiles[i]][2]) for i in allowed]
                return vod.master_playlist(options, session["token"]).encode()
            return vod.media_playlist(session["duration"], allowed[0], session["token"]).encode()
        variant = re.fullmatch(r"variant([0-3])\.m3u8", filename)
        if variant:
            index = int(variant[1])
            if index not in allowed:
                raise HTTPException(404, "Variant unavailable")
            return vod.media_playlist(session["duration"], index, session["token"]).encode()
        segment = re.fullmatch(r"v([0-3])segment(\d{6})\.ts", filename)
        if not segment or int(segment[1]) not in allowed or int(segment[2]) >= vod.segment_count(session["duration"]):
            raise HTTPException(404, "Segment unavailable")
        profile_index, number = int(segment[1]), int(segment[2])
        first = number // vod.BATCH_SEGMENTS * vod.BATCH_SEGMENTS
        path = session["folder"] / filename
        with self.lock:
            if self.sessions.get(sid) is not session:
                raise HTTPException(404, "Session expired")
            if path.exists():
                return path.read_bytes()
            process = session["process"]
            batch = (profile_index, first)
            if session["batch"] != batch or process is None or process.poll() is not None:
                if process is not None and process.poll() is None:
                    # A seek or variant switch supersedes the old finite batch.
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                for partial in session["folder"].glob("*.tmp"):
                    partial.unlink(missing_ok=True)
                profile = profiles[profile_index]
                size = output_size(session["width"], session["height"], profile)
                command = encode_command(session["source"], session["headers"], session["folder"], size,
                                         session.get("videoBitrate") or PROFILES[profile][2], 0, session["codec"], session.get("colorTransfer", ""))
                command = vod.batch_command(command, session["folder"], profile_index, first, session["duration"])
                if session.get('subtitle'):
                    try:
                        start = first * vod.SEGMENT_SECONDS
                        if session['subtitle']['codec_name'] in subtitles.BITMAP_CODECS:
                            command = subtitles.burn_bitmap(command, session['subtitle']['index'], size)
                        else:
                            subtitles.extract_batch(session['source'], session['headers'], session['subtitle'],
                                session['folder'], start, min(session['duration'], start + vod.BATCH_SEGMENTS * vod.SEGMENT_SECONDS))
                            index = command.index('-vf') + 1
                            command[index] = subtitles.burn_filter(command[index], session['folder'], start)
                    except (OSError, ValueError, subprocess.SubprocessError):
                        raise HTTPException(502, 'Subtitle preparation failed') from None
                command[command.index("-init_hw_device") + 1] = "vaapi=va:" + self.hardware.report.get("device", "/dev/dri/renderD128")
                # Cache only a small working set. Never retain a complete rendition.
                cached = sorted(session["folder"].glob("*.ts"), key=lambda p: p.stat().st_mtime)
                while sum(p.stat().st_size for p in cached) > 96 * 1024 * 1024:
                    cached.pop(0).unlink(missing_ok=True)
                session["generation"] += 1
                session["batch"] = batch
                try:
                    session["process"] = subprocess.Popen(command, env=self.hardware.env, stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    session["process"] = None
                    raise HTTPException(502, "Encoder startup failed") from None
            generation = session["generation"]
        deadline = time.monotonic() + 25
        while True:
            with self.lock:
                if self.sessions.get(sid) is not session:
                    raise HTTPException(404, "Session expired")
                if session["generation"] != generation:
                    raise HTTPException(409, "Batch superseded by seek or quality switch")
                if path.exists():
                    return path.read_bytes()
                if session["process"].poll() is not None:
                    raise HTTPException(502, "Encoder stopped before segment completion")
            if time.monotonic() >= deadline:
                raise HTTPException(504, "Segment not ready")
            time.sleep(.1)


manager = Manager()


@contextlib.asynccontextmanager
async def lifespan(app):
    # Only our UUID-named cache directories belong to this service.
    if manager.root.exists():
        for folder in manager.root.iterdir():
            if folder.is_dir() and re.fullmatch(r"[0-9a-f]{32}", folder.name):
                shutil.rmtree(folder)
    async def reap():
        while True:
            await asyncio.sleep(5)
            await asyncio.to_thread(manager.clean)
    task = asyncio.create_task(reap())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        for sid in list(manager.sessions):
            manager.stop(sid)


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def authorize(request: Request, call_next):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", manager.key) or not secrets.compare_digest(request.headers.get("authorization", "").encode("utf-8"), ("Bearer " + manager.key).encode("utf-8")):
        return Response(status_code=403)
    return await call_next(request)


@app.get("/capabilities")
def capabilities():
    return {"protocol": "mediaindex-transcode-v1", "available": manager.available(), "profiles": list(PROFILES) if manager.available() else [],
            "multivariantProfile": "adaptive", "hardwareValidated": False, "seekMode": "restart-session", "vod": True,
            "hardware": manager.hardware.report, "bitrates": BITRATES}


@app.post("/sessions")
def create(payload: CreateSession):
    return manager.create(payload)


@app.api_route("/sessions/{sid}", methods=["GET", "DELETE"])
def control(sid: str, request: Request, x_session_token: str = Header(default="")):
    s = manager.get(sid, x_session_token)
    if request.method == "DELETE":
        manager.stop(sid)
        return {"stopped": True}
    if s.get("delivery") == "vod":
        return {"state": "encoding" if s["process"] is not None and s["process"].poll() is None else "idle"}
    return {"state": "running" if s["process"].poll() is None else "finished"}


@app.get("/sessions/{sid}/{filename}")
def file(sid: str, filename: str, x_session_token: str = Header(default="")):
    if not re.fullmatch(r"index\.m3u8|variant[0-3]\.m3u8|(?:v[0-3])?segment\d{6}\.ts", filename):
        raise HTTPException(404, "File not found")
    s = manager.get(sid, x_session_token)
    if s.get("delivery") == "vod":
        content = manager.vod_file(sid, s, filename)
        return Response(content, media_type="application/vnd.apple.mpegurl" if filename.endswith("m3u8") else "video/mp2t",
                        headers={"Cache-Control": "no-store"})
    path = s["folder"] / filename
    deadline = time.monotonic() + 25
    while not path.exists():
        if s["process"].poll() is not None:
            raise HTTPException(502, "Encoder stopped")
        if time.monotonic() >= deadline:
            raise HTTPException(504, "Segment not ready")
        time.sleep(.1)
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        raise HTTPException(404, "Segment outside rolling window") from None
    if filename.endswith("m3u8"):
        content = content.decode("utf-8").replace("\r\n", "\n")
        content = re.sub(r"^(variant[0-3]\.m3u8|(?:v[0-3])?segment\d{6}\.ts)$", lambda m: m[1] + "?st=" + s["token"], content, flags=re.MULTILINE)
        return Response(content, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-store"})
    return Response(content, media_type="video/mp2t", headers={"Cache-Control": "no-store"})


@app.post("/sessions/{sid}/pause")
def pause(sid: str, x_session_token: str = Header(default="")):
    s = manager.get(sid, x_session_token)
    with manager.lock:
        if s.get("delivery") == "vod":
            # No continuous encoder exists in VOD mode; finish the bounded in-flight batch.
            return {"paused": True}
        if not s.get("paused") and s["process"].poll() is None:
            if not hasattr(signal, "SIGSTOP"):
                raise HTTPException(503, "Pause requires Linux")
            s["process"].send_signal(signal.SIGSTOP)
            s["paused"] = True
    return {"paused": True}
