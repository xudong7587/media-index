from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.clients.qas import QasClient
from app.core.config import get_settings
from app.services.notification_channels import has_ready_channel


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    providers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def notify_review_required(
    media_title: str,
    message: str,
    job_id: int,
    *,
    qas: QasClient | None = None,
    requester=None,
) -> NotificationResult:
    if get_settings().notification_external_enabled and has_ready_channel():
        # The terminal-job notification synchronizer sends this through MediaIndex's
        # own channels. Avoid sending the same review alert through QAS as well.
        return NotificationResult(True, providers=("mediaindex",))
    client = qas or QasClient()
    try:
        config = client.task_data().get("push_config") or {}
    except Exception as exc:
        return NotificationResult(False, errors=(f"qas_config:{type(exc).__name__}",))
    if not isinstance(config, dict):
        return NotificationResult(False, errors=("qas_push_config_invalid",))

    settings = get_settings()
    review_url = settings.public_base_url.rstrip("/") + "/#review" if settings.public_base_url else "MediaIndex 待确认页面"
    title = f"MediaIndex 需要确认：{media_title}"
    content = f"任务 #{job_id}\n{message}\n\n确认或重新搜索：{review_url}"
    send = requester or _request
    providers: list[str] = []
    errors: list[str] = []

    attempts = _build_attempts(config, title, content)
    for provider, url, data, headers, method in attempts:
        try:
            send(url, data, headers, method)
            providers.append(provider)
        except Exception as exc:
            errors.append(f"{provider}:{type(exc).__name__}")
    if not attempts:
        errors.append("no_supported_qas_notification_channel")
    return NotificationResult(bool(providers), tuple(providers), tuple(errors))


def _build_attempts(config: dict, title: str, content: str):
    attempts: list[tuple[str, str, dict | bytes | str, dict[str, str], str]] = []
    if config.get("BARK_PUSH"):
        base = str(config["BARK_PUSH"]).rstrip("/")
        url = base if base.startswith("http") else f"https://api.day.app/{base}"
        data = {"title": title, "body": content}
        for source, target in (
            ("BARK_GROUP", "group"),
            ("BARK_SOUND", "sound"),
            ("BARK_ICON", "icon"),
            ("BARK_LEVEL", "level"),
            ("BARK_URL", "url"),
        ):
            if config.get(source):
                data[target] = config[source]
        attempts.append(("bark", url, data, {"Content-Type": "application/json"}, "POST"))

    if config.get("PUSH_KEY"):
        key = str(config["PUSH_KEY"])
        legacy_match = re.match(r"sctp(\d+)t", key)
        serverchan_url = (
            f"https://{legacy_match.group(1)}.push.ft07.com/send/{key}.send"
            if legacy_match
            else f"https://sctapi.ftqq.com/{key}.send"
        )
        attempts.append(
            (
                "serverchan",
                serverchan_url,
                {"text": title, "desp": content.replace("\n", "\n\n")},
                {"Content-Type": "application/x-www-form-urlencoded"},
                "POST",
            )
        )

    if config.get("PUSH_PLUS_TOKEN"):
        attempts.append(
            (
                "pushplus",
                "https://www.pushplus.plus/send",
                {
                    "token": config["PUSH_PLUS_TOKEN"],
                    "title": title,
                    "content": content,
                    "topic": config.get("PUSH_PLUS_USER", ""),
                    "template": config.get("PUSH_PLUS_TEMPLATE", "markdown"),
                },
                {"Content-Type": "application/json"},
                "POST",
            )
        )

    if config.get("FSKEY"):
        attempts.append(
            (
                "feishu",
                f"https://open.feishu.cn/open-apis/bot/v2/hook/{config['FSKEY']}",
                {"msg_type": "text", "content": {"text": f"{title}\n\n{content}"}},
                {"Content-Type": "application/json"},
                "POST",
            )
        )

    if config.get("GOTIFY_URL") and config.get("GOTIFY_TOKEN"):
        attempts.append(
            (
                "gotify",
                f"{str(config['GOTIFY_URL']).rstrip('/')}/message?token={config['GOTIFY_TOKEN']}",
                {"title": title, "message": content, "priority": config.get("GOTIFY_PRIORITY", 0)},
                {"Content-Type": "application/x-www-form-urlencoded"},
                "POST",
            )
        )

    if config.get("TG_BOT_TOKEN") and config.get("TG_USER_ID"):
        host = str(config.get("TG_API_HOST") or "https://api.telegram.org").rstrip("/")
        attempts.append(
            (
                "telegram",
                f"{host}/bot{config['TG_BOT_TOKEN']}/sendMessage",
                {"chat_id": str(config["TG_USER_ID"]), "text": f"{title}\n\n{content}", "disable_web_page_preview": "true"},
                {"Content-Type": "application/x-www-form-urlencoded"},
                "POST",
            )
        )

    if config.get("NTFY_TOPIC"):
        base = str(config.get("NTFY_URL") or "https://ntfy.sh").rstrip("/")
        headers = {"Title": title, "Priority": str(config.get("NTFY_PRIORITY") or "3")}
        if config.get("NTFY_TOKEN"):
            headers["Authorization"] = f"Bearer {config['NTFY_TOKEN']}"
        attempts.append(("ntfy", f"{base}/{config['NTFY_TOPIC']}", content.encode("utf-8"), headers, "POST"))

    if config.get("QYWX_KEY"):
        origin = str(config.get("QYWX_ORIGIN") or "https://qyapi.weixin.qq.com").rstrip("/")
        attempts.append(
            (
                "wecom",
                f"{origin}/cgi-bin/webhook/send?key={config['QYWX_KEY']}",
                {"msgtype": "text", "text": {"content": f"{title}\n\n{content}"}},
                {"Content-Type": "application/json"},
                "POST",
            )
        )

    if config.get("WXPUSHER_APP_TOKEN") and (config.get("WXPUSHER_TOPIC_IDS") or config.get("WXPUSHER_UIDS")):
        topics = [int(value) for value in str(config.get("WXPUSHER_TOPIC_IDS") or "").split(";") if value.strip().isdigit()]
        uids = [value.strip() for value in str(config.get("WXPUSHER_UIDS") or "").split(";") if value.strip()]
        attempts.append(
            (
                "wxpusher",
                "https://wxpusher.zjiecode.com/api/send/message",
                {
                    "appToken": config["WXPUSHER_APP_TOKEN"],
                    "summary": title,
                    "content": f"# {title}\n\n{content}",
                    "contentType": 3,
                    "topicIds": topics,
                    "uids": uids,
                },
                {"Content-Type": "application/json"},
                "POST",
            )
        )

    if config.get("WEBHOOK_URL") and config.get("WEBHOOK_METHOD"):
        webhook_url = str(config["WEBHOOK_URL"]).replace("$title", urllib.parse.quote_plus(title)).replace(
            "$content", urllib.parse.quote_plus(content)
        )
        content_type = str(config.get("WEBHOOK_CONTENT_TYPE") or "text/plain")
        webhook_headers = _parse_headers(str(config.get("WEBHOOK_HEADERS") or ""))
        webhook_headers.setdefault("Content-Type", content_type)
        body_title = title.replace("\n", "\\n") if content_type == "application/json" else title
        body_content = content.replace("\n", "\\n") if content_type == "application/json" else content
        webhook_body = str(config.get("WEBHOOK_BODY") or "").replace("$title", body_title).replace("$content", body_content)
        if content_type == "application/json":
            try:
                webhook_data: dict | bytes | str = json.loads(webhook_body)
            except json.JSONDecodeError:
                webhook_data = webhook_body
        else:
            webhook_data = webhook_body
        attempts.append(("webhook", webhook_url, webhook_data, webhook_headers, str(config["WEBHOOK_METHOD"]).upper()))
    return attempts


def _parse_headers(value: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in value.splitlines():
        if ":" not in line:
            continue
        key, item = line.split(":", 1)
        if key.strip():
            headers[key.strip()] = item.strip()
    return headers


def _request(url: str, data: dict | bytes | str, headers: dict[str, str], method: str) -> None:
    if isinstance(data, bytes):
        body = data
    elif isinstance(data, str):
        body = data.encode("utf-8")
    elif headers.get("Content-Type") == "application/x-www-form-urlencoded":
        body = urllib.parse.urlencode(data).encode("utf-8")
    else:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=15) as response:
        if not 200 <= int(response.status) < 300:
            raise RuntimeError(f"http_{response.status}")
