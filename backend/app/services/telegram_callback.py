from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from app.clients.http import open_url
from app.core.config import get_settings
from app.services.notification_channels import (
    ChannelResult,
    answer_telegram_callback,
    send_telegram,
    send_telegram_photo,
)
from app.services.wecom_callback import (
    InteractionTransport,
    handle_command,
    interaction_transport,
)
from app.services.channel_monitor import process_channel_post


_POLL_THREAD: threading.Thread | None = None
_POLL_STOP = threading.Event()
_POLL_OFFSET = 0
_UPDATE_EXECUTOR: ThreadPoolExecutor | None = None


def start_telegram_poller() -> None:
    global _POLL_THREAD, _UPDATE_EXECUTOR
    if _POLL_THREAD and _POLL_THREAD.is_alive():
        return
    _POLL_STOP.clear()
    _UPDATE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="media-index-telegram-update")
    _POLL_THREAD = threading.Thread(target=_poll_loop, name="media-index-telegram", daemon=True)
    _POLL_THREAD.start()


def stop_telegram_poller() -> None:
    global _POLL_THREAD, _UPDATE_EXECUTOR
    _POLL_STOP.set()
    if _POLL_THREAD and _POLL_THREAD.is_alive():
        _POLL_THREAD.join(timeout=2)
    _POLL_THREAD = None
    if _UPDATE_EXECUTOR is not None:
        _UPDATE_EXECUTOR.shutdown(wait=False, cancel_futures=True)
        _UPDATE_EXECUTOR = None


def _poll_loop() -> None:
    global _POLL_OFFSET
    while not _POLL_STOP.is_set():
        settings = get_settings()
        token = settings.telegram_bot_token.strip()
        if not (settings.telegram_enabled or getattr(settings, "telegram_channel_source_enabled", False)) or not token:
            _POLL_STOP.wait(10)
            continue
        try:
            updates = _get_updates(token, _POLL_OFFSET)
            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = int(update.get("update_id") or 0)
                if update_id:
                    _POLL_OFFSET = max(_POLL_OFFSET, update_id + 1)
                _submit_telegram_update(update)
        except Exception:
            _POLL_STOP.wait(5)


def _submit_telegram_update(update: dict) -> bool:
    executor = _UPDATE_EXECUTOR
    if executor is None:
        return False
    executor.submit(handle_telegram_update, update, "")
    return True


def _get_updates(token: str, offset: int) -> list[dict]:
    settings = get_settings()
    host = settings.telegram_api_host.strip().rstrip("/") or "https://api.telegram.org"
    query = urllib.parse.urlencode(
        {
            "offset": offset,
            "timeout": 25,
            "allowed_updates": json.dumps(["message", "edited_message", "channel_post", "edited_channel_post", "callback_query"]),
        }
    )
    request = urllib.request.Request(
        f"{host}/bot{token}/getUpdates?{query}",
        method="GET",
    )
    with open_url(request, timeout=35) as response:
        if int(getattr(response, "status", 200)) >= 400:
            raise RuntimeError(f"Telegram polling HTTP {response.status}")
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError(str(data.get("description") if isinstance(data, dict) else "Telegram 轮询失败"))
    result = data.get("result") or []
    return result if isinstance(result, list) else []


def handle_telegram_update(update: dict, public_base_url: str = "") -> None:
    settings = get_settings()
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        if not settings.telegram_enabled:
            return
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        if not chat_id or not _is_allowed_chat(chat_id):
            _answer_callback(str(callback_query.get("id") or ""))
            return
        _answer_callback(str(callback_query.get("id") or ""))
        command = _callback_command(str(callback_query.get("data") or ""))
        if command:
            with interaction_transport(_transport(chat_id)):
                handle_command(command, chat_id, public_base_url)
        return

    channel_post = update.get("channel_post") or update.get("edited_channel_post")
    if isinstance(channel_post, dict):
        if getattr(settings, "telegram_channel_source_enabled", False):
            process_channel_post(channel_post)
        return
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    if not settings.telegram_enabled:
        return
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "").strip()
    if not text or not chat_id or not _is_allowed_chat(chat_id):
        return
    with interaction_transport(_transport(chat_id)):
        handle_command(text, chat_id, public_base_url)


def _transport(chat_id: str) -> InteractionTransport:
    return InteractionTransport(
        provider="telegram",
        send_text=lambda text, *, to_user=None, buttons=None: send_telegram(
            text,
            chat_id=to_user or chat_id,
            reply_markup=buttons,
        ),
        send_news=lambda title, description, url, pic_url, *, to_user=None: _send_news(
            title,
            description,
            url,
            pic_url,
            to_user or chat_id,
        ),
        allowed_user=_is_allowed_chat,
    )


def _send_news(
    title: str,
    description: str,
    url: str,
    pic_url: str,
    chat_id: str,
) -> ChannelResult:
    text = f"MediaIndex · {title}\n\n{description}"
    if url.strip():
        text = f"{text}\n\n{url.strip()}"
    if pic_url.strip():
        result = send_telegram_photo(text, pic_url, chat_id=chat_id)
        if result.ok:
            return result
    return send_telegram(text, chat_id=chat_id)


def _is_allowed_chat(chat_id: str) -> bool:
    configured = get_settings().telegram_chat_id.strip()
    allowed = {item for item in re.split(r"[\s,;|]+", configured) if item}
    return bool(allowed) and chat_id.strip() in allowed


def _callback_command(data: str) -> str:
    if data == "mi:cancel":
        return "/cancel"
    match = re.fullmatch(r"mi:choice:(\d+)", data)
    return match.group(1) if match else ""


def _answer_callback(callback_query_id: str) -> None:
    if callback_query_id:
        answer_telegram_callback(callback_query_id)
