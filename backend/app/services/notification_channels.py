from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from app.clients.http import open_url
from app.core.config import get_settings

_TOKEN_CACHE: dict[tuple[str, str, str], tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()


@dataclass(frozen=True)
class ChannelResult:
    provider: str
    ok: bool
    message: str


def send_configured_channels(title: str, message: str, action_page: str = "") -> list[ChannelResult]:
    settings = get_settings()
    if not settings.notification_external_enabled:
        return []

    body = _message_body(title, message, action_page)
    results: list[ChannelResult] = []
    if settings.telegram_enabled:
        results.append(send_telegram(body))
    if settings.wecom_enabled:
        results.append(send_wecom(body))
    if settings.wecom_app_enabled:
        results.append(send_wecom_app(body))
    return results


def has_ready_channel() -> bool:
    settings = get_settings()
    return bool(
        (
            settings.telegram_enabled
            and settings.telegram_bot_token.strip()
            and settings.telegram_chat_id.strip()
        )
        or (settings.wecom_enabled and settings.wecom_key.strip())
        or (
            settings.wecom_app_enabled
            and settings.wecom_corp_id.strip()
            and settings.wecom_app_secret.strip()
            and settings.wecom_app_agent_id > 0
            and any(
                value.strip()
                for value in (
                    settings.wecom_app_to_user,
                    settings.wecom_app_to_party,
                    settings.wecom_app_to_tag,
                )
            )
        )
    )


def test_channel(provider: str) -> ChannelResult:
    body = "MediaIndex 通知渠道测试\n\n如果你收到这条消息，说明推送配置可用。"
    if provider == "telegram":
        return send_telegram(body)
    if provider == "wecom":
        return send_wecom(body)
    if provider == "wecom_app":
        return send_wecom_app(body)
    return ChannelResult(provider, False, "不支持的通知渠道")


def send_telegram(text: str, requester: Callable | None = None) -> ChannelResult:
    settings = get_settings()
    token = settings.telegram_bot_token.strip()
    chat_id = settings.telegram_chat_id.strip()
    if not token or not chat_id:
        return ChannelResult("telegram", False, "请先保存 Bot Token 和 Chat ID")
    try:
        host = _validated_origin(settings.telegram_api_host, "https://api.telegram.org")
    except ValueError as exc:
        return ChannelResult("telegram", False, str(exc))
    url = f"{host}/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode("utf-8")
    return _post_json("telegram", url, payload, {"Content-Type": "application/x-www-form-urlencoded"}, requester)


def send_wecom(text: str, requester: Callable | None = None) -> ChannelResult:
    settings = get_settings()
    key = settings.wecom_key.strip()
    if not key:
        return ChannelResult("wecom", False, "请先保存企业微信机器人 Key")
    try:
        origin = _validated_origin(settings.wecom_origin, "https://qyapi.weixin.qq.com")
    except ValueError as exc:
        return ChannelResult("wecom", False, str(exc))
    url = f"{origin}/cgi-bin/webhook/send?key={urllib.parse.quote(key)}"
    payload = json.dumps(
        {"msgtype": "text", "text": {"content": text}},
        ensure_ascii=False,
    ).encode("utf-8")
    return _post_json("wecom", url, payload, {"Content-Type": "application/json"}, requester)


def send_wecom_app(
    text: str,
    requester: Callable | None = None,
    *,
    to_user: str | None = None,
) -> ChannelResult:
    return _send_wecom_app_message(
        {"msgtype": "text", "text": {"content": text}},
        requester,
        to_user=to_user,
    )


def send_wecom_app_news(
    title: str,
    description: str,
    url: str,
    pic_url: str,
    requester: Callable | None = None,
    *,
    to_user: str | None = None,
) -> ChannelResult:
    if not title.strip() or not url.strip() or not pic_url.strip():
        return ChannelResult("wecom_app", False, "图文消息缺少标题、链接或海报地址")
    return _send_wecom_app_message(
        {
            "msgtype": "news",
            "news": {
                "articles": [
                    {
                        "title": title.strip()[:128],
                        "description": description.strip()[:512],
                        "url": url.strip(),
                        "picurl": pic_url.strip(),
                    }
                ]
            },
        },
        requester,
        to_user=to_user,
    )


def _send_wecom_app_message(
    message: dict[str, object],
    requester: Callable | None,
    *,
    to_user: str | None,
) -> ChannelResult:
    settings = get_settings()
    corp_id = settings.wecom_corp_id.strip()
    secret = settings.wecom_app_secret.strip()
    agent_id = settings.wecom_app_agent_id
    if not corp_id or not secret or agent_id <= 0:
        return ChannelResult("wecom_app", False, "请先保存企业 ID、应用 Secret 和 AgentId")
    recipients = (
        {"touser": to_user.strip(), "toparty": "", "totag": ""}
        if to_user is not None
        else {
            "touser": settings.wecom_app_to_user.strip(),
            "toparty": settings.wecom_app_to_party.strip(),
            "totag": settings.wecom_app_to_tag.strip(),
        }
    )
    if not any(recipients.values()):
        return ChannelResult("wecom_app", False, "成员、部门或标签至少填写一项")
    try:
        origin = _validated_origin(settings.wecom_origin, "https://qyapi.weixin.qq.com")
        token = _wecom_access_token(origin, corp_id, secret, requester)
        payload_data: dict[str, object] = {
            **message,
            "agentid": agent_id,
            "safe": 0,
            "enable_duplicate_check": 0,
        }
        payload_data.update({key: value for key, value in recipients.items() if value})
        payload = json.dumps(payload_data, ensure_ascii=False).encode("utf-8")
        data = _send_wecom_app_request(origin, token, payload, requester)
        if int(data.get("errcode", -1)) in {40014, 42001}:
            _invalidate_wecom_token(origin, corp_id, secret)
            token = _wecom_access_token(origin, corp_id, secret, requester)
            data = _send_wecom_app_request(origin, token, payload, requester)
        if int(data.get("errcode", -1)) != 0:
            return ChannelResult("wecom_app", False, str(data.get("errmsg") or "企业微信自建应用返回失败"))
        invalid = [
            str(data.get(key) or "").strip()
            for key in ("invaliduser", "invalidparty", "invalidtag")
            if str(data.get(key) or "").strip()
        ]
        if invalid:
            return ChannelResult("wecom_app", True, f"消息已发送，部分接收范围无效：{'; '.join(invalid)}")
        return ChannelResult("wecom_app", True, "消息已发送")
    except Exception as exc:
        return ChannelResult("wecom_app", False, _safe_exception_message(exc))


def _post_json(
    provider: str,
    url: str,
    payload: bytes,
    headers: dict[str, str],
    requester: Callable | None,
) -> ChannelResult:
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        data = _request_json(request, requester)
        if provider == "telegram" and data.get("ok") is not True:
            return ChannelResult(provider, False, str(data.get("description") or "Telegram 返回失败"))
        if provider == "wecom" and int(data.get("errcode", -1)) != 0:
            return ChannelResult(provider, False, str(data.get("errmsg") or "企业微信返回失败"))
        return ChannelResult(provider, True, "测试消息已发送")
    except Exception as exc:
        return ChannelResult(provider, False, _safe_exception_message(exc))


def _wecom_access_token(
    origin: str,
    corp_id: str,
    secret: str,
    requester: Callable | None,
) -> str:
    key = (origin, corp_id, secret)
    now = time.monotonic()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(key)
        if cached and cached[1] > now:
            return cached[0]
        query = urllib.parse.urlencode({"corpid": corp_id, "corpsecret": secret})
        request = urllib.request.Request(f"{origin}/cgi-bin/gettoken?{query}", method="GET")
        data = _request_json(request, requester)
        if int(data.get("errcode", -1)) != 0 or not str(data.get("access_token") or ""):
            raise RuntimeError(str(data.get("errmsg") or "企业微信 access_token 获取失败"))
        token = str(data["access_token"])
        expires_in = max(60, int(data.get("expires_in") or 7200) - 300)
        _TOKEN_CACHE[key] = (token, now + expires_in)
        return token


def _invalidate_wecom_token(origin: str, corp_id: str, secret: str) -> None:
    with _TOKEN_LOCK:
        _TOKEN_CACHE.pop((origin, corp_id, secret), None)


def _send_wecom_app_request(
    origin: str,
    token: str,
    payload: bytes,
    requester: Callable | None,
) -> dict:
    url = f"{origin}/cgi-bin/message/send?access_token={urllib.parse.quote(token)}"
    return _request_json(
        urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        ),
        requester,
    )


def _request_json(request: urllib.request.Request, requester: Callable | None) -> dict:
    response = requester(request, timeout=15) if requester else open_url(request, timeout=15)
    with response:
        status = int(getattr(response, "status", 200))
        raw = response.read().decode("utf-8", errors="replace")
    if status >= 400:
        raise RuntimeError(f"HTTP {status}")
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        raise RuntimeError("通知接口返回格式无效")
    return data


def _message_body(title: str, message: str, action_page: str) -> str:
    settings = get_settings()
    parts = [f"MediaIndex · {title}"]
    if message.strip():
        parts.append(message.strip())
    base_url = settings.public_base_url.strip().rstrip("/")
    if base_url:
        suffix = f"#{action_page}" if action_page else ""
        parts.append(f"{base_url}/{suffix}")
    return "\n\n".join(parts)


def _validated_origin(value: str, fallback: str) -> str:
    raw = (value or fallback).strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("通知 API 地址必须是完整的 HTTP/HTTPS 地址")
    return raw


def _safe_exception_message(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"access_token=[^&\s'\"]+", "access_token=***", message, flags=re.IGNORECASE)
    message = re.sub(r"/bot[^/\s'\"]+", "/bot***", message)
    return f"{type(exc).__name__}: {message}"[:500]
