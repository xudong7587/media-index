"""Asset-scoped, bounded 115 HLS sessions, independent of the FFmpeg worker."""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field

from app.clients.p115 import P115Error
from app.clients.p115_video import P115VideoClient, P115VideoAuthError, attributes, manifest_lines, media_url
from app.services.playback import PlaybackError, verify_asset_token

PROTOCOL = "mediaindex-cloud-video-v1"
_LOCK = threading.RLock()
_SESSIONS: dict[str, "Session"] = {}
_IDLE_SECONDS = 7200
_MAX_LIFETIME = 28800
_MAX_SESSIONS = 32
_MAX_RESOURCES = 16384


class CloudVideoError(RuntimeError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _asset(token: str) -> dict:
    try:
        asset = verify_asset_token(token)
    except PlaybackError:
        raise CloudVideoError("播放令牌无效或已失效", 403) from None
    if asset.get("provider") != "p115":
        raise CloudVideoError("此影片不是可识别的 115 来源")
    return asset


def discover(token: str, user_agent: str):
    asset = _asset(token)
    try:
        return P115VideoClient().discover(str(asset["file_id"]), user_agent)
    except P115VideoAuthError as exc:
        raise CloudVideoError(str(exc), 401) from None
    except P115Error as exc:
        raise CloudVideoError(str(exc)) from None
    except Exception:
        raise CloudVideoError("115 云端清晰度查询未完成") from None


@dataclass
class Session:
    id: str
    secret: str
    asset_token: str
    user_agent: str
    master: bytes
    base_url: str
    delivery: str = "direct"
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    resources: dict[str, tuple[str, str]] = field(default_factory=dict)


def _prune(now: float):
    for sid, session in list(_SESSIONS.items()):
        if now - session.touched >= _IDLE_SECONDS or now - session.created >= _MAX_LIFETIME:
            del _SESSIONS[sid]


def create(token: str, variant_id: str, user_agent: str, delivery: str = "direct") -> dict:
    if delivery not in ("direct", "proxy"):
        raise CloudVideoError("云端播放传输方式无效", 400)
    # Reserve no session for failed/unknown variants. Resolve URLs again rather
    # than cache provider links between menu discovery and user selection.
    manifest = discover(token, user_agent)
    variant = next((v for v in manifest.variants if v.id == variant_id), None)
    if variant is None:
        raise CloudVideoError("115 清晰度已变化，请重新打开清晰度菜单")
    session = Session(secrets.token_hex(16), secrets.token_urlsafe(32), token,
                      user_agent, manifest.selected(variant), manifest.url, delivery)
    # Validate every master URI before publishing a session.
    try:
        rewrite(session, session.master, session.base_url)
    except P115Error as exc:
        raise CloudVideoError(str(exc)) from None
    with _LOCK:
        _prune(time.monotonic())
        if len(_SESSIONS) >= _MAX_SESSIONS:
            raise CloudVideoError("云端播放会话已满，请稍后重试", 429)
        _SESSIONS[session.id] = session
    return {"protocol": PROTOCOL, "sessionId": session.id, "sessionToken": session.secret,
            "playlistUrl": f"/api/cloud-video/sessions/{session.id}/index.m3u8?st={session.secret}",
            "variant": variant.public(), "seekMode": "hls-vod", "delivery": session.delivery,
            "idleTimeoutSeconds": _IDLE_SECONDS}


def authorize(sid: str, secret: str, user_agent: str) -> Session:
    with _LOCK:
        _prune(time.monotonic())
        session = _SESSIONS.get(sid)
        if session is None or not secrets.compare_digest(session.secret, secret) or session.user_agent != user_agent:
            raise CloudVideoError("云端播放会话失效，请重新选择清晰度", 403)
        _asset(session.asset_token)
        session.touched = time.monotonic()
        return session


def stop(session: Session):
    with _LOCK:
        _SESSIONS.pop(session.id, None)


def rewrite(session: Session, body: bytes, base_url: str) -> bytes:
    lines = manifest_lines(body)
    # This feature promises a complete VOD timeline, not live/rolling HLS.
    if any(line.startswith("#EXTINF:") for line in lines) and "#EXT-X-ENDLIST" not in lines:
        raise P115Error("115 返回了非完整点播清单")

    def register(value: str, kind: str) -> str:
        target = media_url(value, base_url, upgrade_http=True)
        # Keep small manifests/keys authorized at the gateway. Video/audio/init
        # bytes go straight from the CDN to the player unless proxy was explicit.
        if kind == "media" and session.delivery == "direct":
            return target
        rid = hashlib.sha256((kind + "\n" + target).encode()).hexdigest()[:32]
        with _LOCK:
            if rid not in session.resources and len(session.resources) >= _MAX_RESOURCES:
                raise P115Error("115 云端清单资源过多")
            session.resources[rid] = (target, kind)
        return f"/api/cloud-video/sessions/{session.id}/resources/{rid}?st={session.secret}"

    result: list[str] = []
    next_kind = "media"
    for line in lines:
        if not line.startswith("#"):
            result.append(register(line, next_kind))
            next_kind = "media"
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            next_kind = "playlist"
        if "URI=" in line:
            tag = line.partition(":")[0]
            kinds = {"#EXT-X-MEDIA": "playlist", "#EXT-X-I-FRAME-STREAM-INF": "playlist",
                     "#EXT-X-KEY": "key", "#EXT-X-SESSION-KEY": "key", "#EXT-X-MAP": "media"}
            if tag not in kinds:
                raise P115Error("115 HLS 包含暂不支持的资源类型")
            attrs = attributes(line)
            if tag in ("#EXT-X-KEY", "#EXT-X-SESSION-KEY") and (
                    attrs.get("METHOD") != "AES-128" or attrs.get("KEYFORMAT", "identity") != "identity"):
                raise P115Error("115 HLS 使用了暂不支持的加密方式")
            value = attrs.get("URI", "")
            if f'URI="{value}"' not in line:
                raise P115Error("115 HLS 资源地址格式不兼容")
            line = line.replace(f'URI="{value}"', f'URI="{register(value, kinds[tag])}"')
        result.append(line)
    return ("\n".join(result) + "\n").encode()


def playlist(session: Session, resource_id: str = "") -> bytes:
    try:
        if not resource_id:
            return rewrite(session, session.master, session.base_url)
        target, kind = resource(session, resource_id)
        if kind != "playlist":
            raise CloudVideoError("云端资源类型无效", 400)
        body, final_url = P115VideoClient().read_manifest(target, session.user_agent)
        return rewrite(session, body, final_url)
    except P115Error as exc:
        raise CloudVideoError(str(exc)) from None
    except CloudVideoError:
        raise
    except Exception:
        raise CloudVideoError("115 云端清单读取失败", 502) from None


def resource(session: Session, resource_id: str) -> tuple[str, str]:
    with _LOCK:
        value = session.resources.get(resource_id)
    if value is None:
        raise CloudVideoError("云端资源不存在", 404)
    return value


def open_resource(session: Session, resource_id: str, range_header: str):
    target, kind = resource(session, resource_id)
    if kind == "playlist":
        raise CloudVideoError("云端资源类型无效", 400)
    try:
        return P115VideoClient().open_media(target, session.user_agent, range_header)[0]
    except P115Error as exc:
        raise CloudVideoError(str(exc), 502) from None
