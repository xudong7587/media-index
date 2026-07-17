from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from Crypto.Cipher import AES

from app.api.transfers import TransferCreate, _run_transfer_job, enqueue_transfer
from app.api.review import _run_confirmed_candidate, prepare_candidate_confirmation
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.db.database import db
from app.services.notification_channels import ChannelResult, send_wecom_app, send_wecom_app_news
from app.services.poster_cache import cache_tmdb_poster


@dataclass(frozen=True)
class WecomInbound:
    from_user: str
    command: str
    message_id: str


def verify_signature(
    signature: str,
    timestamp: str,
    nonce: str,
    encrypted: str,
    token: str,
) -> bool:
    if not all((signature, timestamp, nonce, encrypted, token)):
        return False
    digest = hashlib.sha1("".join(sorted((token, timestamp, nonce, encrypted))).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, signature)


def decrypt_message(encrypted: str, aes_key: str, expected_receive_id: str = "") -> str:
    key_text = aes_key.strip()
    if len(key_text) != 43:
        raise ValueError("EncodingAESKey 必须是 43 个字符")
    try:
        key = base64.b64decode(key_text + "=")
        ciphertext = base64.b64decode(encrypted)
    except Exception as exc:
        raise ValueError("企业微信加密数据格式无效") from exc
    if len(key) != 32 or not ciphertext or len(ciphertext) % 16:
        raise ValueError("企业微信加密数据长度无效")
    plaintext = AES.new(key, AES.MODE_CBC, key[:16]).decrypt(ciphertext)
    pad = plaintext[-1]
    if pad < 1 or pad > 32 or plaintext[-pad:] != bytes([pad]) * pad:
        raise ValueError("企业微信消息填充无效")
    plaintext = plaintext[:-pad]
    if len(plaintext) < 20:
        raise ValueError("企业微信消息长度无效")
    message_length = struct.unpack("!I", plaintext[16:20])[0]
    message_end = 20 + message_length
    if message_end > len(plaintext):
        raise ValueError("企业微信消息正文长度无效")
    message = plaintext[20:message_end].decode("utf-8")
    receive_id = plaintext[message_end:].decode("utf-8")
    if expected_receive_id and receive_id and receive_id != expected_receive_id:
        raise ValueError("企业微信回调的企业 ID 不匹配")
    return message


def parse_inbound_xml(xml_content: str) -> WecomInbound | None:
    root = ET.fromstring(xml_content)
    from_user = (root.findtext("FromUserName") or "").strip()
    message_type = (root.findtext("MsgType") or "").strip().lower()
    command = ""
    if message_type == "text":
        command = (root.findtext("Content") or "").strip()
    elif message_type == "event" and (root.findtext("Event") or "").strip().lower() == "click":
        command = (root.findtext("EventKey") or "").strip()
    if not from_user or not command:
        return None
    message_id = (root.findtext("MsgId") or "").strip()
    if not message_id:
        message_id = ":".join(
            (
                from_user,
                (root.findtext("CreateTime") or "").strip(),
                command,
            )
        )
    return WecomInbound(from_user=from_user, command=command, message_id=message_id)


def extract_encrypted_xml(body: bytes) -> str:
    if len(body) > 256 * 1024:
        raise ValueError("企业微信回调正文过大")
    root = ET.fromstring(body)
    encrypted = (root.findtext("Encrypt") or "").strip()
    if not encrypted:
        raise ValueError("企业微信回调缺少 Encrypt")
    return encrypted


def is_allowed_user(user_id: str) -> bool:
    raw = get_settings().wecom_callback_allowed_users.strip()
    if not raw:
        return True
    allowed = {item for item in re.split(r"[\s,;|]+", raw) if item}
    return user_id in allowed


def handle_command(command: str, from_user: str, public_base_url: str = "") -> None:
    if not is_allowed_user(from_user):
        send_wecom_app("MediaIndex\n\n你没有使用交互指令的权限。", to_user=from_user)
        return
    normalized = command.strip()
    if normalized in {"取消", "/cancel", "cancel"}:
        clear_interaction(from_user)
        send_wecom_app("MediaIndex\n\n当前选择已取消。", to_user=from_user)
        return
    if normalized.isdigit():
        if handle_interaction_choice(int(normalized), from_user, public_base_url):
            return
        send_wecom_app("MediaIndex\n\n当前没有等待选择的项目，请先发送资源名或 /review。", to_user=from_user)
        return
    if is_builtin_command(command):
        if normalized.split(maxsplit=1)[0].lower() in {"/review", "待确认"}:
            start_review_job_selection(from_user, public_base_url)
            return
        send_wecom_app(command_reply(command), to_user=from_user)
        return
    handle_resource_request(command, from_user, public_base_url)


def is_builtin_command(command: str) -> bool:
    normalized = command.strip().split(maxsplit=1)[0].lower()
    return normalized.startswith("/") or normalized in {
        "help",
        "帮助",
        "状态",
        "待确认",
        "追更",
        "愿望单",
        "通知",
    }


def parse_resource_request(command: str) -> tuple[str, str]:
    text = command.strip()
    target = "cloud"
    local_match = re.match(r"^本地(?:\s+|[：:]\s*)(.+)$", text, flags=re.DOTALL)
    cloud_match = re.match(r"^(?:网盘|云端)(?:\s+|[：:]\s*)(.+)$", text, flags=re.DOTALL)
    if local_match:
        target = "local"
        text = local_match.group(1).strip()
    elif cloud_match:
        text = cloud_match.group(1).strip()
    return target, text


def handle_resource_request(command: str, from_user: str, public_base_url: str = "") -> None:
    target, query = parse_resource_request(command)
    if not query:
        send_wecom_app("MediaIndex\n\n资源名不能为空。示例：沙丘2，或 本地 沙丘2", to_user=from_user)
        return
    client = TmdbClient()
    if not client.configured():
        send_wecom_app("MediaIndex\n\nTMDB 尚未配置，无法识别资源名称。", to_user=from_user)
        return
    try:
        search = client.search(query, "all")
        options = select_media_options(query, search.get("results") or [])
        if not options:
            send_wecom_app(f"MediaIndex\n\n没有找到“{query}”对应的影视条目。", to_user=from_user)
            return
        if len(options) > 1:
            save_interaction(
                from_user,
                "media",
                {"target": target, "query": query, "options": options, "public_base_url": public_base_url},
            )
            send_wecom_app(_media_options_reply(query, options), to_user=from_user)
            return
        _start_resource_transfer(options[0], target, query, from_user, public_base_url, client)
    except Exception as exc:
        send_wecom_app(
            f"MediaIndex\n\n处理“{query}”失败：{type(exc).__name__}",
            to_user=from_user,
        )
    return


def _start_resource_transfer(
    item: dict,
    target: str,
    query: str,
    from_user: str,
    public_base_url: str,
    client: TmdbClient | None = None,
) -> None:
    tmdb = client or TmdbClient()
    season_number = select_season_number(tmdb, item)
    payload = TransferCreate(
        tmdb_id=int(item["tmdb_id"]),
        media_type=str(item["media_type"]),
        title=str(item.get("title") or query),
        year=str(item.get("year") or ""),
        poster_url=str(item.get("poster_url") or ""),
        overview=str(item.get("overview") or ""),
        target=target,
        season_number=season_number,
    )
    started = enqueue_transfer(payload)
    destination = "本地" if target == "local" else "网盘"
    season_label = f" S{season_number:02d}" if season_number else ""
    title = str(item.get("title") or query)
    year = f" ({item.get('year')})" if item.get("year") else ""
    if started.get("duplicate"):
        send_wecom_app(
            f"MediaIndex\n\n{title}{year}{season_label} 已有进行中的{destination}任务。\n任务 #{started['id']}",
            to_user=from_user,
        )
        return

    send_wecom_app(
        f"MediaIndex\n\n已匹配：{title}{year}{season_label}\n保存到：{destination}\n任务 #{started['id']} 已开始搜索资源。",
        to_user=from_user,
    )
    poster_key = cache_tmdb_poster(str(item.get("poster_url") or ""))
    _run_transfer_job(payload, int(started["id"]))
    if _start_candidate_selection(int(started["id"]), from_user, public_base_url):
        return
    _send_transfer_result(
        int(started["id"]),
        title,
        destination,
        from_user,
        public_base_url,
        poster_key,
    )


def select_media_options(query: str, results: list[dict]) -> list[dict]:
    needle = _compact_title(query)
    ranked = []
    for item in results:
        title = _compact_title(str(item.get("title") or ""))
        if not title:
            continue
        if title == needle:
            rank = 0
        elif needle and needle in title:
            rank = 1
        elif title and title in needle:
            rank = 2
        else:
            rank = 3
        ranked.append((rank, item))
    ranked.sort(key=lambda pair: pair[0])
    relevant = [item for rank, item in ranked if rank <= 2]
    if relevant:
        return relevant[:5]
    return [item for _, item in ranked[:3]]


def select_media_match(query: str, results: list[dict]) -> dict | None:
    options = select_media_options(query, results)
    return options[0] if options else None


def select_season_number(client: TmdbClient, item: dict) -> int | None:
    if item.get("media_type") not in {"tv", "variety"}:
        return None
    detail = client.details(str(item["media_type"]), int(item["tmdb_id"]))
    seasons = detail.get("seasons") or []
    today = date.today().isoformat()
    aired = [
        int(season["season_number"])
        for season in seasons
        if int(season.get("season_number") or 0) > 0
        and (not season.get("air_date") or str(season["air_date"]) <= today)
    ]
    if aired:
        return max(aired)
    available = [int(season["season_number"]) for season in seasons if int(season.get("season_number") or 0) > 0]
    return max(available) if available else 1


def _compact_title(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _transfer_result(job_id: int, title: str, destination: str) -> tuple[str, str, str]:
    with db() as conn:
        row = conn.execute(
            "SELECT status,stage,message FROM transfer_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    if not row:
        return f"{title} 的任务记录不存在", f"任务 #{job_id}", ""
    status = str(row["status"] or "")
    message = str(row["message"] or "")
    if status == "done":
        heading = f"{title} 已完成{destination}转存"
        action_page = "tracking"
    elif status == "triggered":
        heading = f"{title} 已提交{destination}转存任务"
        action_page = "tracking"
    elif status == "needs_review":
        heading = f"{title} 需要在待确认中选择资源"
        action_page = "review"
    elif str(row["stage"] or "") == "no_resource":
        heading = f"{title} 暂无资源，已加入愿望单"
        action_page = "wishlist"
    else:
        heading = f"{title} 处理失败"
        action_page = "tracking"
    return heading, f"任务 #{job_id}\n{message}".strip(), action_page


def _send_transfer_result(
    job_id: int,
    title: str,
    destination: str,
    from_user: str,
    public_base_url: str,
    poster_key: str,
) -> None:
    heading, description, action_page = _transfer_result(job_id, title, destination)
    base_url = public_base_url.strip().rstrip("/")
    if base_url and poster_key:
        result = send_wecom_app_news(
            heading,
            description,
            f"{base_url}/#{action_page}" if action_page else f"{base_url}/",
            f"{base_url}/api/notifications/wecom/posters/{poster_key}",
            to_user=from_user,
        )
        if result.ok:
            return
    send_wecom_app(f"MediaIndex\n\n{heading}\n{description}".strip(), to_user=from_user)


def save_interaction(user_id: str, interaction_type: str, payload: dict) -> None:
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(timespec="seconds")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO wecom_interactions(user_id,interaction_type,payload_json,expires_at)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET interaction_type=excluded.interaction_type,
                payload_json=excluded.payload_json,expires_at=excluded.expires_at,
                updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, interaction_type, json.dumps(payload, ensure_ascii=False), expires_at),
        )


def load_interaction(user_id: str) -> tuple[str, dict] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT interaction_type,payload_json,expires_at FROM wecom_interactions WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        try:
            expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        except ValueError:
            expires_at = datetime.min.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            conn.execute("DELETE FROM wecom_interactions WHERE user_id=?", (user_id,))
            return None
    try:
        payload = json.loads(row["payload_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    return str(row["interaction_type"]), payload if isinstance(payload, dict) else {}


def clear_interaction(user_id: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM wecom_interactions WHERE user_id=?", (user_id,))


def handle_interaction_choice(choice: int, from_user: str, public_base_url: str) -> bool:
    interaction = load_interaction(from_user)
    broadcast_interaction = False
    if not interaction:
        interaction = load_interaction("*")
        broadcast_interaction = interaction is not None
    if not interaction:
        return False
    interaction_type, payload = interaction
    options = payload.get("options") or []
    if choice < 1 or choice > len(options):
        send_wecom_app(
            f"MediaIndex\n\n请输入 1-{len(options)} 之间的数字，或发送“取消”。",
            to_user=from_user,
        )
        return True
    selected = options[choice - 1]
    clear_interaction("*" if broadcast_interaction else from_user)
    if interaction_type == "media":
        try:
            _start_resource_transfer(
                selected,
                str(payload.get("target") or "cloud"),
                str(payload.get("query") or selected.get("title") or ""),
                from_user,
                public_base_url or str(payload.get("public_base_url") or ""),
            )
        except Exception as exc:
            send_wecom_app(f"MediaIndex\n\n开始转存失败：{type(exc).__name__}", to_user=from_user)
        return True
    if interaction_type == "review_job":
        _send_candidate_options(int(selected["job_id"]), from_user, public_base_url)
        return True
    if interaction_type == "candidate":
        _confirm_candidate_from_wecom(int(selected["candidate_id"]), from_user, public_base_url)
        return True
    return False


def start_review_job_selection(from_user: str, public_base_url: str) -> None:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.id AS job_id,COALESCE(NULLIF(j.display_title,''),t.title,w.title,m.title,'任务 #' || j.id) AS title,
                   j.media_type,j.season_number
            FROM transfer_jobs j
            LEFT JOIN tracking_tasks t ON t.id=j.task_id
            LEFT JOIN wishlist w ON w.id=j.wishlist_id
            LEFT JOIN media m ON m.tmdb_id=j.tmdb_id AND m.media_type=j.media_type
            WHERE j.status='needs_review' AND j.stage NOT IN ('superseded','dismissed')
            ORDER BY j.created_at DESC LIMIT 5
            """
        ).fetchall()
    options = [dict(row) for row in rows]
    if not options:
        send_wecom_app("MediaIndex 待确认任务\n\n暂无内容。", to_user=from_user)
        return
    if len(options) == 1:
        _send_candidate_options(int(options[0]["job_id"]), from_user, public_base_url)
        return
    save_interaction(from_user, "review_job", {"options": options})
    lines = [
        f"{index}. {_media_type_label(str(item.get('media_type') or ''))} {item['title']}"
        + (f" S{int(item['season_number']):02d}" if item.get("season_number") else "")
        for index, item in enumerate(options, start=1)
    ]
    send_wecom_app(
        "MediaIndex 待确认任务\n\n" + "\n".join(lines) + "\n\n回复数字选择任务，或发送“取消”。",
        to_user=from_user,
    )


def _start_candidate_selection(job_id: int, from_user: str, public_base_url: str) -> bool:
    with db() as conn:
        row = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if not row or row["status"] != "needs_review":
        return False
    _send_candidate_options(job_id, from_user, public_base_url)
    return True


def send_review_candidate_notifications(job_id: int, public_base_url: str) -> list[ChannelResult]:
    settings = get_settings()
    if not settings.wecom_app_enabled or not settings.wecom_callback_enabled:
        return []
    raw_users = settings.wecom_callback_allowed_users.strip() or settings.wecom_app_to_user.strip()
    users = []
    for user in re.split(r"[\s,;|]+", raw_users):
        user = user.strip()
        if user and user != "@all" and user not in users:
            users.append(user)
    results = []
    for user in users:
        interaction = load_interaction(user)
        if interaction and interaction[0] == "candidate" and int(interaction[1].get("job_id") or 0) == job_id:
            results.append(ChannelResult("wecom_app", True, f"{user} 已收到待确认候选"))
            continue
        results.append(_send_candidate_options(job_id, user, public_base_url))
    if not users and any(
        value.strip()
        for value in (settings.wecom_app_to_user, settings.wecom_app_to_party, settings.wecom_app_to_tag)
    ):
        interaction = load_interaction("*")
        if interaction and interaction[0] == "candidate" and int(interaction[1].get("job_id") or 0) == job_id:
            return [ChannelResult("wecom_app", True, "接收范围已收到待确认候选")]
        results.append(_send_candidate_options(job_id, "*", public_base_url))
    return results


def _send_candidate_options(job_id: int, from_user: str, public_base_url: str) -> ChannelResult:
    recipient_user = None if from_user == "*" else from_user
    with db() as conn:
        job = conn.execute(
            """
            SELECT j.id,COALESCE(NULLIF(j.display_title,''),t.title,w.title,m.title,'任务 #' || j.id) AS title,
                   COALESCE(NULLIF(t.poster_url,''),NULLIF(w.poster_url,''),m.poster_url,'') AS poster_url
            FROM transfer_jobs j
            LEFT JOIN tracking_tasks t ON t.id=j.task_id
            LEFT JOIN wishlist w ON w.id=j.wishlist_id
            LEFT JOIN media m ON m.tmdb_id=j.tmdb_id AND m.media_type=j.media_type
            WHERE j.id=? AND j.status='needs_review'
            """,
            (job_id,),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT id AS candidate_id,source_title,source,published_at,score,file_count
            FROM candidates
            WHERE job_id=? AND rejected=0 AND COALESCE(decision,'pending')='pending'
            ORDER BY score DESC,created_at DESC LIMIT 5
            """,
            (job_id,),
        ).fetchall()
    options = [dict(row) for row in rows]
    if not job or not options:
        return send_wecom_app(
            "MediaIndex\n\n该任务目前没有可确认的资源候选，请在网页待确认中查看。",
            to_user=recipient_user,
        )
    save_interaction(
        from_user,
        "candidate",
        {"options": options, "job_id": job_id, "public_base_url": public_base_url},
    )
    lines = []
    for index, item in enumerate(options, start=1):
        source = f" [{item['source']}]" if item.get("source") else ""
        files = f"，{int(item.get('file_count') or 0)} 个文件" if item.get("file_count") else ""
        lines.append(f"{index}. {_short(str(item.get('source_title') or '未命名资源'))}{source}{files}")
    description = "\n".join(lines) + "\n\n回复数字确认资源，或发送“取消”。"
    base_url = public_base_url.strip().rstrip("/")
    poster_key = cache_tmdb_poster(str(job["poster_url"] or ""))
    if base_url and poster_key:
        result = send_wecom_app_news(
            f"{job['title']} 需要确认",
            description,
            f"{base_url}/#review",
            f"{base_url}/api/notifications/wecom/posters/{poster_key}",
            to_user=recipient_user,
        )
        if result.ok:
            return result
    return send_wecom_app(
        f"MediaIndex 待确认\n\n{job['title']}\n\n{description}",
        to_user=recipient_user,
    )


def _confirm_candidate_from_wecom(candidate_id: int, from_user: str, public_base_url: str) -> None:
    try:
        candidate, job = prepare_candidate_confirmation(candidate_id)
    except Exception as exc:
        send_wecom_app(f"MediaIndex\n\n候选确认失败：{getattr(exc, 'detail', str(exc))}", to_user=from_user)
        return
    send_wecom_app(
        f"MediaIndex\n\n已选择资源，任务 #{job['id']} 正在重新匹配并转存。",
        to_user=from_user,
    )
    _run_confirmed_candidate(candidate, job, [])
    if _start_candidate_selection(int(job["id"]), from_user, public_base_url):
        return
    with db() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(NULLIF(j.display_title,''),t.title,w.title,m.title,'任务 #' || j.id) AS title,j.target,
                   COALESCE(t.poster_url,w.poster_url,m.poster_url,'') AS poster_url
            FROM transfer_jobs j
            LEFT JOIN tracking_tasks t ON t.id=j.task_id
            LEFT JOIN wishlist w ON w.id=j.wishlist_id
            LEFT JOIN media m ON m.tmdb_id=j.tmdb_id AND m.media_type=j.media_type
            WHERE j.id=?
            """,
            (job["id"],),
        ).fetchone()
    title = str(row["title"] if row else f"任务 #{job['id']}")
    destination = "本地" if row and row["target"] == "local" else "网盘"
    poster_key = cache_tmdb_poster(str(row["poster_url"] or "")) if row else ""
    _send_transfer_result(int(job["id"]), title, destination, from_user, public_base_url, poster_key)


def _media_options_reply(query: str, options: list[dict]) -> str:
    lines = [
        f"{index}. {_media_type_label(str(item.get('media_type') or ''))} "
        f"{item.get('title') or '未命名'}"
        + (f" ({item.get('year')})" if item.get("year") else "")
        for index, item in enumerate(options, start=1)
    ]
    return (
        f"MediaIndex\n\n“{query}”匹配到多个条目，请确认要转存的资源：\n\n"
        + "\n".join(lines)
        + "\n\n回复数字选择，或发送“取消”。"
    )


def _media_type_label(media_type: str) -> str:
    return {"movie": "电影", "tv": "剧集", "variety": "综艺"}.get(media_type, "影视")


def _short(value: str, limit: int = 88) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def command_reply(command: str) -> str:
    normalized = command.strip().split(maxsplit=1)[0].lower()
    aliases = {
        "帮助": "/help",
        "状态": "/status",
        "待确认": "/review",
        "追更": "/tracking",
        "愿望单": "/wishlist",
        "通知": "/notifications",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"/help", "help"}:
        return (
            "MediaIndex 指令\n\n"
            "/status  系统状态\n"
            "/review  待确认任务\n"
            "/tracking  追更任务\n"
            "/wishlist  愿望单\n"
            "/notifications  最近通知\n"
            "/help  指令帮助\n"
            "/cancel  取消当前选择\n\n"
            "发送资源名：默认保存到网盘\n"
            "发送“本地 资源名”：保存到本地"
        )
    if normalized in {"/status", "status"}:
        return _status_reply()
    if normalized == "/review":
        return _review_reply()
    if normalized == "/tracking":
        return _tracking_reply()
    if normalized == "/wishlist":
        return _wishlist_reply()
    if normalized == "/notifications":
        return _notifications_reply()
    return "MediaIndex\n\n未识别的指令。发送 /help 查看可用指令。"


def _status_reply() -> str:
    with db() as conn:
        active_tracking = conn.execute(
            "SELECT COUNT(*) FROM tracking_tasks WHERE status='active'"
        ).fetchone()[0]
        wishlist = conn.execute(
            "SELECT COUNT(*) FROM wishlist WHERE status IN ('pending','retry_wait','needs_review')"
        ).fetchone()[0]
        review = conn.execute(
            "SELECT COUNT(*) FROM transfer_jobs WHERE status='needs_review' AND stage NOT IN ('superseded','dismissed')"
        ).fetchone()[0]
        unread = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE is_read=0 AND is_cleared=0"
        ).fetchone()[0]
    return (
        "MediaIndex 状态\n\n"
        f"智能追更：{active_tracking}\n"
        f"愿望单待处理：{wishlist}\n"
        f"待确认：{review}\n"
        f"未读通知：{unread}"
    )


def _review_reply() -> str:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(t.title,w.title,m.title,'任务 #' || j.id) AS title
            FROM transfer_jobs j
            LEFT JOIN tracking_tasks t ON t.id=j.task_id
            LEFT JOIN wishlist w ON w.id=j.wishlist_id
            LEFT JOIN media m ON m.tmdb_id=j.tmdb_id AND m.media_type=j.media_type
            WHERE j.status='needs_review' AND j.stage NOT IN ('superseded','dismissed')
            ORDER BY j.created_at DESC LIMIT 5
            """
        ).fetchall()
    return _list_reply("待确认任务", [str(row["title"]) for row in rows])


def _tracking_reply() -> str:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT title,season_number,decision_state FROM tracking_tasks
            WHERE status='active' ORDER BY updated_at DESC LIMIT 5
            """
        ).fetchall()
    items = [
        f"{row['title']} S{int(row['season_number'] or 1):02d} ({row['decision_state'] or 'pending'})"
        for row in rows
    ]
    return _list_reply("智能追更", items)


def _wishlist_reply() -> str:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT title,status FROM wishlist
            WHERE status IN ('pending','retry_wait','needs_review')
            ORDER BY created_at DESC LIMIT 5
            """
        ).fetchall()
    return _list_reply("愿望单", [f"{row['title']} ({row['status']})" for row in rows])


def _notifications_reply() -> str:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT title FROM notifications WHERE is_cleared=0
            ORDER BY created_at DESC,id DESC LIMIT 5
            """
        ).fetchall()
    return _list_reply("最近通知", [str(row["title"]) for row in rows])


def _list_reply(title: str, items: list[str]) -> str:
    if not items:
        return f"MediaIndex {title}\n\n暂无内容。"
    lines = "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
    return f"MediaIndex {title}\n\n{lines}"
