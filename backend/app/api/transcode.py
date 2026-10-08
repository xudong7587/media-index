"""Optional worker gateway on the playback port; no change to original playback."""
import re
import secrets
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask

from app.services.playback import PlaybackError, open_playback_stream, verify_asset_token
from app.clients.p115 import P115Client
from app.services import transcode as service
from app.services import plugins
from app.services.playback_cache import cached_stream, buffer_status, prefetch_on_pause

router = APIRouter(prefix="/api/transcode", tags=["transcode"])
service.configure_access_log_redaction()


def call_worker(*args, **kwargs):
    try:
        return service.call_worker(*args, **kwargs)
    except service.TranscodeError as exc:
        raise HTTPException(exc.status, str(exc)) from None


def worker_config():
    try:
        return service.worker_config()
    except service.TranscodeError as exc:
        raise HTTPException(exc.status, str(exc)) from None


class SessionRequest(BaseModel):
    assetToken: str = Field(min_length=1, max_length=2048)
    profile: str = Field(pattern=r"^(4k|1440p|1080p|720p|adaptive)$")
    startPositionMs: int = Field(default=0, ge=0, le=604800000)
    delivery: str = Field(default="live", pattern=r"^(live|vod)$")
    videoBitrate: int | None = Field(default=None, ge=2000000, le=20000000)

    @model_validator(mode="after")
    def validate_bitrate(self):
        allowed = {"4k": {10000000, 15000000, 20000000}, "1440p": {6000000, 10000000}, "1080p": {4000000, 8000000}, "720p": {2000000, 4000000}}
        if self.videoBitrate is not None and self.videoBitrate not in allowed.get(self.profile, set()):
            raise ValueError("该分辨率不支持所选码率")
        return self


class BufferRequest(BaseModel):
    assetToken: str = Field(min_length=1, max_length=2048)
    sourceBitrate: int = Field(default=0, ge=0, le=1000000000)
    remainingSeconds: float = Field(default=0, ge=0, le=86400, allow_inf_nan=False)
    positionSeconds: float | None = Field(default=None, ge=0, le=86400, allow_inf_nan=False)


@router.post("/buffer/status")
def source_buffer_status(payload: BufferRequest, request: Request):
    if not getattr(request.app.state, "playback_cache_owner", True):
        return {"state": "cache_disabled", "reason": "use_playback_port"}
    if not plugins.enabled():
        raise HTTPException(503, "播放优化插件已停用")
    try:
        return buffer_status(payload.assetToken, payload.sourceBitrate, payload.remainingSeconds, payload.positionSeconds)
    except PlaybackError:
        raise HTTPException(403, "播放令牌无效") from None


@router.post("/buffer/prefetch")
def source_buffer_prefetch(payload: BufferRequest, request: Request):
    if not getattr(request.app.state, "playback_cache_owner", True):
        raise HTTPException(503, "请使用独立播放端口的缓存入口")
    if not plugins.enabled():
        raise HTTPException(503, "播放优化插件已停用")
    try:
        return {"started": prefetch_on_pause(payload.assetToken), "maximumBytes": 64 * 1024**2}
    except PlaybackError:
        raise HTTPException(403, "播放令牌无效") from None


@router.api_route("/buffer/source/{token}", methods=["GET", "HEAD"])
def original_cached_source(token: str, request: Request):
    if not getattr(request.app.state, "playback_cache_owner", True):
        raise HTTPException(503, "请使用独立播放端口的缓存入口")
    if not plugins.enabled() or not os.environ.get("TRANSCODE_SOURCE_CACHE_DIR"):
        raise HTTPException(503, "原片缓存未启用")
    try:
        asset = verify_asset_token(token)
        if asset.get("provider") != "p115":
            raise HTTPException(400, "首期缓存仅支持115来源")
        stream = (open_playback_stream(token, request.headers.get("range", ""), P115Client.PLAYBACK_USER_AGENT, head_only=True)
                  if request.method == "HEAD" else cached_stream(token, request.headers.get("range", ""), P115Client.PLAYBACK_USER_AGENT))
    except PlaybackError:
        raise HTTPException(409, "原片缓存来源暂时不可用") from None
    if request.method == "HEAD":
        return Response(status_code=stream.status_code, headers=stream.headers)
    return StreamingResponse(stream.chunks, status_code=stream.status_code, headers=stream.headers,
                             background=BackgroundTask(stream.chunks.close))


@router.get("/capabilities")
def capabilities():
    if not plugins.enabled():
        return {"available": False, "profiles": []}
    try:
        return call_worker("GET", "/capabilities").json()
    except HTTPException:
        return {"available": False, "profiles": []}


@router.post("/sessions")
def create_session(payload: SessionRequest):
    if not plugins.enabled():
        raise HTTPException(503, "播放优化插件已停用")
    try:
        asset = verify_asset_token(payload.assetToken)
    except PlaybackError:
        raise HTTPException(403, "播放令牌无效") from None
    if asset.get("provider") != "p115":
        raise HTTPException(400, "首期转码仅支持115来源")
    result = call_worker("POST", "/sessions", payload=payload.model_dump()).json()
    result["playlistUrl"] = f"/api/transcode/sessions/{result['sessionId']}/index.m3u8?st={result['sessionToken']}"
    return result


def validate_session_id(session_id):
    if not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise HTTPException(404, "会话不存在")


def validate_session_token(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise HTTPException(404, "会话不存在")


@router.api_route("/sessions/{session_id}", methods=["GET", "DELETE"])
def session_control(session_id: str, request: Request, st: str = ""):
    validate_session_id(session_id)
    validate_session_token(st)
    response = call_worker(request.method, f"/sessions/{session_id}", session_token=st)
    return Response(response.content, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.api_route("/sessions/{session_id}/{filename}", methods=["GET", "HEAD"])
def session_file(session_id: str, filename: str, request: Request, st: str = ""):
    validate_session_id(session_id)
    validate_session_token(st)
    if not re.fullmatch(r"index\.m3u8|variant[0-3]\.m3u8|(?:v[0-3])?segment\d{6}\.ts", filename):
        raise HTTPException(404, "文件不存在")
    response = call_worker("GET", f"/sessions/{session_id}/{filename}", session_token=st)
    return Response(b"" if request.method == "HEAD" else response.content,
                    media_type="application/vnd.apple.mpegurl" if filename.endswith("m3u8") else "video/mp2t",
                    headers={"Cache-Control": "no-store", "Content-Length": str(len(response.content))})


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, st: str = ""):
    validate_session_id(session_id)
    validate_session_token(st)
    return call_worker("POST", f"/sessions/{session_id}/pause", session_token=st).json()


@router.api_route("/source/{token}", methods=["GET", "HEAD"], include_in_schema=False)
def worker_source(token: str, request: Request):
    _, key = worker_config()
    if not secrets.compare_digest(request.headers.get("authorization", "").encode("utf-8"), ("Bearer " + key).encode("utf-8")):
        raise HTTPException(403, "访问被拒绝")
    try:
        if request.method == "HEAD" or not os.environ.get("TRANSCODE_SOURCE_CACHE_DIR") or not getattr(request.app.state, "playback_cache_owner", True):
            stream = open_playback_stream(token, request.headers.get("range", ""), P115Client.PLAYBACK_USER_AGENT, head_only=request.method == "HEAD")
        else:
            stream = cached_stream(token, request.headers.get("range", ""), P115Client.PLAYBACK_USER_AGENT)
    except PlaybackError as exc:
        # Only known playback classifications and a normalized byte range are
        # diagnostic data. Never log arbitrary provider messages/URLs/secrets.
        message = str(exc)
        known = {"播放范围请求无效", "播放范围超出文件长度", "无法连接网盘播放地址", "播放上游未返回有效分段范围", "播放上游分段范围与请求不一致", "播放上游分段长度与范围不一致"}
        reason = message if message in known or re.fullmatch(r"播放上游返回 HTTP \d{3}", message) else "provider_or_asset_failure"
        raw_range = request.headers.get("range", "").strip()
        safe_range = raw_range if re.fullmatch(r"bytes=\d*-\d*", raw_range) else "invalid_or_empty"
        logging.getLogger(__name__).warning("Transcode source rejected: %s; range=%s", reason, safe_range)
        raise HTTPException(409, "播放来源暂时不可用") from None
    if request.method == "HEAD":
        return Response(status_code=stream.status_code, headers=stream.headers)
    # ffprobe and seek abandon HTTP bodies early. Release their upstream socket
    # explicitly instead of waiting for generator garbage collection.
    return StreamingResponse(stream.chunks, status_code=stream.status_code, headers=stream.headers,
                             background=BackgroundTask(stream.chunks.close))
