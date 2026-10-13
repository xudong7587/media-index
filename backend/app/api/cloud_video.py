"""Explicit asset-token authorization on every cloud HLS entry."""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.services import cloud_video as service

router = APIRouter(prefix="/api/cloud-video", tags=["cloud-video"])


class Discovery(BaseModel):
    assetToken: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")


class Selection(Discovery):
    variantId: str = Field(pattern=r"^[0-9a-f]{32}$")
    delivery: Literal["direct", "proxy"] = "direct"


def invoke(action, *args):
    try:
        return action(*args)
    except service.CloudVideoError as exc:
        raise HTTPException(exc.status, str(exc)) from None


def session(request: Request, sid: str):
    tokens = request.query_params.getlist("st")
    if len(tokens) != 1 or set(request.query_params) != {"st"}:
        raise HTTPException(403, "云端播放会话凭据无效")
    return invoke(service.authorize, sid, tokens[0], request.headers.get("user-agent", ""))


@router.post("/discover")
def discover(payload: Discovery, request: Request):
    manifest = invoke(service.discover, payload.assetToken, request.headers.get("user-agent", ""))
    return Response(json.dumps({"protocol": service.PROTOCOL,
                    "variants": [v.public() for v in manifest.variants]}),
                    media_type="application/json", headers={"Cache-Control": "no-store"})


@router.post("/sessions")
def create(payload: Selection, request: Request):
    result = invoke(service.create, payload.assetToken, payload.variantId, request.headers.get("user-agent", ""), payload.delivery)
    return Response(json.dumps(result), media_type="application/json", headers={"Cache-Control": "no-store"})


@router.delete("/sessions/{sid}")
def stop(sid: str, request: Request):
    service.stop(session(request, sid))
    return Response(status_code=204)


@router.get("/sessions/{sid}/index.m3u8")
def master(sid: str, request: Request):
    content = invoke(service.playlist, session(request, sid))
    return Response(content, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-store"})


@router.get("/sessions/{sid}/resources/{rid}")
def resource(sid: str, rid: str, request: Request):
    authorized = session(request, sid)
    _, kind = invoke(service.resource, authorized, rid)
    if kind == "playlist":
        return Response(invoke(service.playlist, authorized, rid), media_type="application/vnd.apple.mpegurl",
                        headers={"Cache-Control": "no-store"})
    upstream = invoke(service.open_resource, authorized, rid, request.headers.get("range", ""))
    if kind == "key":
        try:
            content = upstream.read(17)
            if len(content) != 16:
                raise HTTPException(502, "115 云端密钥长度无效")
            return Response(content, media_type="application/octet-stream", headers={"Cache-Control": "no-store"})
        finally:
            upstream.close()
    headers = {"Cache-Control": "no-store"}
    for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        value = upstream.headers.get(name)
        if value and "\r" not in value and "\n" not in value:
            headers[name] = value

    def chunks():
        try:
            read = getattr(upstream, "read1", None) or upstream.read
            while block := read(64 * 1024):
                yield block
        except Exception:
            raise RuntimeError("115 云端媒体读取中断") from None
        finally:
            upstream.close()

    return StreamingResponse(chunks(), status_code=upstream.status, headers=headers,
                             background=BackgroundTask(upstream.close))
