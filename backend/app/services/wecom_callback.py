from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import re
import struct
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterator

from Crypto.Cipher import AES

from app.api.transfers import TransferCreate, _run_transfer_batch, _run_transfer_job, enqueue_transfer
from app.api.review import _run_confirmed_candidate, prepare_candidate_confirmation
from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.db.database import db
from app.services.direct_link_transfer import (
    handle_direct_link_transfer,
    infer_direct_link_category,
    looks_like_download_link,
    prepare_direct_link_request,
    resolve_direct_link_resource_name,
)
from app.services.direct_movie import resolve_direct_movie_source
from app.services.emby_interaction import emby_status_reply
from app.services.cloud_download_targets import list_cloud_download_targets
from app.services.notification_channels import (
    ChannelResult,
    send_telegram,
    send_telegram_photo,
    send_wecom_app as _send_wecom_app,
    send_wecom_app_news as _send_wecom_app_news,
)
from app.services.poster_cache import cache_tmdb_poster
from app.services.strm_interaction import StrmInteractionError, list_strm_root_directories
from app.services.tracking_registration import TrackingRegistration, register_tracking_task
from app.services.media_planning import build_episode_coverage, build_media_plan, media_identity
from app.services.resource_probe import probe_resource_availability
from app.providers.registry import get_transfer_provider, resolve_provider_key


@dataclass(frozen=True)
class InteractionTransport:
    provider: str
    send_text: Callable[..., ChannelResult]
    send_news: Callable[..., ChannelResult]
    allowed_user: Callable[[str], bool]


_INTERACTION_TRANSPORT: contextvars.ContextVar[InteractionTransport | None] = contextvars.ContextVar(
    "media_index_interaction_transport", default=None
)


@contextmanager
def interaction_transport(transport: InteractionTransport) -> Iterator[None]:
    token = _INTERACTION_TRANSPORT.set(transport)
    try:
        yield
    finally:
        _INTERACTION_TRANSPORT.reset(token)


def send_wecom_app(
    text: str,
    requester: Callable | None = None,
    *,
    to_user: str | None = None,
    buttons: list[list[dict[str, str]]] | None = None,
) -> ChannelResult:
    transport = _INTERACTION_TRANSPORT.get()
    if transport and requester is None:
        return transport.send_text(text, to_user=to_user, buttons=buttons)
    return _send_wecom_app(text, requester, to_user=to_user)


def send_wecom_app_news(
    title: str,
    description: str,
    url: str,
    pic_url: str,
    requester: Callable | None = None,
    *,
    to_user: str | None = None,
) -> ChannelResult:
    transport = _INTERACTION_TRANSPORT.get()
    if transport and requester is None:
        return transport.send_news(
            title,
            description,
            url,
            pic_url,
            to_user=to_user,
        )
    return _send_wecom_app_news(
        title,
        description,
        url,
        pic_url,
        requester,
        to_user=to_user,
    )


def interaction_request_source() -> str:
    transport = _INTERACTION_TRANSPORT.get()
    return transport.provider if transport else "wecom"


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
    transport = _INTERACTION_TRANSPORT.get()
    allowed = transport.allowed_user(from_user) if transport else is_allowed_user(from_user)
    if not allowed:
        send_wecom_app("MediaIndex\n\n你没有使用交互指令的权限。", to_user=from_user)
        return
    normalized = command.strip()
    if normalized in {"取消", "/cancel", "cancel"}:
        clear_interaction(from_user)
        send_wecom_app("MediaIndex\n\n当前选择已取消。", to_user=from_user)
        return
    pending = load_interaction(from_user)
    direct_choice = parse_direct_link_choice(command) if pending and pending[0] == "direct_link" else None
    if direct_choice is not None:
        choice, title, year = direct_choice
        if normalized != str(choice) and not title:
            send_wecom_app(
                "MediaIndex\n\n如需提供整理用的准确名称，请在编号后发送媒体名称，例如：3 黑夜告白 2026。年份可省略。",
                to_user=from_user,
            )
            return
        handle_interaction_choice(
            choice,
            from_user,
            public_base_url,
            title=title,
            year=year,
        )
        return
    if normalized.isdigit():
        if handle_interaction_choice(int(normalized), from_user, public_base_url):
            return
        send_wecom_app("MediaIndex\n\n当前没有等待选择的项目，请先发送资源名、/review 或 /strm_directory。", to_user=from_user)
        return
    if is_builtin_command(command):
        shortcut = normalized.split(maxsplit=1)[0].lower()
        if shortcut == "/strm_directory":
            start_strm_directory_selection(from_user)
            return
        if shortcut in {"/strm_full", "/strm_incremental"}:
            from app.services.scheduler import schedule_interaction_strm_scans

            mode = "full" if shortcut == "/strm_full" else "incremental"
            jobs = schedule_interaction_strm_scans(mode)
            started = [item for item in jobs if item.get("ok")]
            skipped = [item for item in jobs if not item.get("ok")]
            lines = [f"已为 {provider_label(str(item['provider']))} 创建任务 #{item['job_id']}" for item in started]
            lines.extend(f"{provider_label(str(item['provider']))}：{item.get('message', '未执行')}" for item in skipped)
            if not lines:
                lines.append("没有已开启 STRM 生成且配置了扫描子目录的网盘。")
            send_wecom_app(f"MediaIndex STRM {'全量' if mode == 'full' else '增量'}扫描\n\n" + "\n".join(lines), to_user=from_user)
            return
        if shortcut == "/download":
            send_wecom_app("MediaIndex 添加下载\n\n请发送资源名称、夸克/115 分享链接、磁力、电驴或 HTTP 下载链接。", to_user=from_user)
            return
        if shortcut == "/tracking":
            reply = _tracking_reply()
            base_url = (public_base_url or get_settings().public_base_url).strip().rstrip("/")
            if base_url:
                reply += f"\n\n打开智能追更：{base_url}/#tracking"
            send_wecom_app(reply, to_user=from_user)
            return
        if normalized.split(maxsplit=1)[0].lower() in {"/review", "待确认"}:
            start_review_job_selection(from_user, public_base_url)
            return
        send_wecom_app(command_reply(command), to_user=from_user)
        return
    pending = load_interaction(from_user)
    if pending and pending[0] == "direct_link_metadata":
        title, year = parse_direct_link_metadata(command)
        if not title:
            send_wecom_app(
                "MediaIndex\n\n请补充资源名，例如：黑夜告白 2026。年份可省略。回复“取消”可放弃。",
                to_user=from_user,
            )
            return
        clear_interaction(from_user)
        start_direct_link_target_selection(
            str(pending[1].get("link") or ""),
            from_user,
            title=title,
            year=year,
            category=str(pending[1].get("category") or "movie"),
        )
        return
    if looks_like_download_link(command):
        start_direct_link_target_selection(command, from_user)
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
        "emby",
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
    pansou = PansouClient()
    preferred_share_urls: tuple[str, ...] = ()
    try:
        if pansou.configured():
            first_search = pansou.search_detailed(
                query,
                limit=100,
                timeout=get_settings().pansou_search_timeout_seconds,
                result_mode="all",
                refresh=True,
            )
            preferred_share_urls = tuple(
                dict.fromkeys(
                    str(item.get("share_url") or "").strip()
                    for item in first_search.items
                    if item.get("share_url")
                )
            )[:20]
    except Exception:
        # The authoritative transfer workflow performs its own bounded search.
        # A failed/empty preview must not prevent TMDB identification or the
        # existing no-resource -> wishlist path from producing user feedback.
        preferred_share_urls = ()

    try:
        client = TmdbClient()
        if not client.configured():
            send_wecom_app("MediaIndex\n\nTMDB 尚未配置，无法核对资源名称。", to_user=from_user)
            return
        media_query, requested_year = parse_media_name_query(query)
        search = client.search(media_query, "all")
        results = search.get("results") or []
        if requested_year:
            results = [item for item in results if str(item.get("year") or "") == requested_year]
        options = select_media_options(media_query, results)
        if not options:
            send_wecom_app(f"MediaIndex\n\n没有找到“{query}”对应的影视条目。", to_user=from_user)
            return
        if len(options) > 1:
            save_interaction(
                from_user,
                "media",
                {
                    "target": target,
                    "query": query,
                    "options": options,
                    "preferred_share_urls": preferred_share_urls,
                    "public_base_url": public_base_url,
                },
            )
            send_wecom_app(
                _media_options_reply(query, options),
                to_user=from_user,
                buttons=_choice_buttons(options),
            )
            return
        _start_resource_target_selection(
            options[0],
            target,
            query,
            from_user,
            public_base_url,
            preferred_share_urls=preferred_share_urls,
        )
    except Exception as exc:
        send_wecom_app(
            f"MediaIndex\n\n处理“{query}”失败：{type(exc).__name__}",
            to_user=from_user,
        )
    return


def parse_media_name_query(query: str) -> tuple[str, str]:
    text = str(query or "").strip()
    match = re.search(r"(?:\s|[（(])((?:19|20)\d{2})[）)]?\s*$", text)
    if not match:
        return text, ""
    title = text[: match.start()].strip(" \t（(")
    return (title or text), match.group(1)


def _start_resource_target_selection(
    item: dict,
    target: str,
    query: str,
    from_user: str,
    public_base_url: str,
    *,
    preferred_share_urls: tuple[str, ...] = (),
) -> None:
    if target != "cloud":
        _start_resource_transfer(
            item,
            target,
            query,
            from_user,
            public_base_url,
            preferred_share_urls=preferred_share_urls,
        )
        return

    options: list[dict[str, str]] = []
    errors: list[str] = []
    try:
        providers = _wecom_cloud_providers("cloud")
    except ValueError:
        providers = ()
    for provider in providers:
        try:
            targets = list_cloud_download_targets(provider)
        except (RuntimeError, ValueError) as exc:
            errors.append(f"{provider_label(provider)}：{_short(str(exc), 100)}")
            continue
        for target_option in targets:
            inferred_category = infer_direct_link_category(provider, target_option.child_name)
            media_type = str(item.get("media_type") or "movie")
            category = "movie" if media_type == "movie" else inferred_category if inferred_category != "movie" else "tv"
            options.append(
                {
                    "provider": provider,
                    "category": category,
                    "path": target_option.path,
                    "cloud_download_child": target_option.child_name,
                    "label": f"{provider_label(provider)} · {target_option.child_name}：{target_option.path}",
                }
            )
    if not options:
        detail = f"\n\n{'；'.join(errors)}" if errors else ""
        send_wecom_app(
            "MediaIndex\n\n当前已启用网盘的云下载根目录下没有可选直属子目录，请先检查网盘连接和云下载路径。"
            + detail,
            to_user=from_user,
        )
        return

    save_interaction(
        from_user,
        "resource_target",
        {
            "target": target,
            "query": query,
            "item": item,
            "options": options,
            "preferred_share_urls": list(preferred_share_urls),
            "public_base_url": public_base_url,
        },
    )
    lines = [f"{index}. {_short(option['label'], 100)}" for index, option in enumerate(options, start=1)]
    title = str(item.get("title") or query)
    year = f" ({item.get('year')})" if item.get("year") else ""
    send_wecom_app(
        f"MediaIndex\n\n已匹配：{title}{year}\n请选择要转存到的云下载子目录，并回复数字：\n\n"
        + "\n".join(lines)
        + "\n\n回复“取消”可放弃本次转存。",
        to_user=from_user,
        buttons=_choice_buttons(options),
    )


def _try_direct_movie(query: str, candidates: list[dict], target: str):
    try:
        provider_key = resolve_provider_key(target, None)
        inspector = get_transfer_provider(
            provider_key or "qas",
            qas=QasClient(),
            target=target,
        )
        result = resolve_direct_movie_source(
            query,
            candidates,
            inspector,
            provider_key=provider_key or "qas",
        )
    except Exception:
        return None
    return (result, provider_key) if result else None


def _start_resource_transfer(
    item: dict,
    target: str,
    query: str,
    from_user: str,
    public_base_url: str,
    client: TmdbClient | None = None,
    preferred_share_urls: tuple[str, ...] = (),
    cloud_download_child: str = "",
) -> None:
    if target == "cloud" and not str(cloud_download_child or "").strip():
        send_wecom_app(
            "MediaIndex\n\n未确认云下载子目录，请重新发送资源名并回复目录编号。",
            to_user=from_user,
        )
        return
    tmdb = client or TmdbClient()
    detail = (
        tmdb.details(str(item["media_type"]), int(item["tmdb_id"]))
        if item.get("media_type") in {"tv", "variety"} and int(item.get("tmdb_id") or 0) > 0
        else {}
    )
    season_number = select_season_number(tmdb, item, detail=detail)
    selected_provider = str(item.get("provider") or "").strip()
    providers = (
        (resolve_provider_key(target, selected_provider),)
        if selected_provider
        else _wecom_cloud_providers(target)
    )
    if len(providers) > 1:
        _start_wecom_provider_group(
            item,
            target,
            query,
            from_user,
            public_base_url,
            providers,
            season_number,
            preferred_share_urls,
        )
        return
    planned_urls, planned_episodes, preferred_only, media_plan = _interaction_transfer_snapshot(
        item,
        providers[0],
        season_number,
        preferred_share_urls,
    )
    payload = TransferCreate(
        tmdb_id=int(item["tmdb_id"]),
        media_type=str(item["media_type"]),
        title=str(item.get("title") or query),
        year=str(item.get("year") or ""),
        poster_url=str(item.get("poster_url") or ""),
        overview=str(item.get("overview") or ""),
        target=target,
        season_number=season_number,
        category=str(item.get("category") or ""),
        provider=providers[0],
        episode_numbers=planned_episodes,
        preferred_share_urls=planned_urls,
        preferred_share_only=preferred_only,
        simple_matching=str(item.get("media_type") or "") == "tv",
        skip_tmdb=bool(item.get("skip_tmdb")),
        request_source=interaction_request_source(),
        request_user=from_user,
        media_plan=media_plan,
    )
    started = enqueue_transfer(
        payload,
        interaction_cloud_download_child=cloud_download_child if target == "cloud" else "",
    )
    destination = "本地" if target == "local" else "网盘"
    season_label = f" S{season_number:02d}" if season_number else ""
    title = str(item.get("title") or query)
    year = f" ({item.get('year')})" if item.get("year") else ""
    if started.get("duplicate"):
        send_wecom_app(
            f"MediaIndex\n\n{title}{year}{season_label} 已有进行中的{destination}任务。\n任务 #{started['id']}",
            to_user=from_user,
        )
        if _is_ongoing_media(item, detail):
            _register_interaction_tracking(item, payload, int(started["id"]), from_user)
        return

    send_wecom_app(
        f"MediaIndex\n\n{'PanSou 已确认标准电影：' if item.get('skip_tmdb') else '已匹配：'}{title}{year}{season_label}\n保存到：{destination}\n任务 #{started['id']} 已开始搜索资源。",
        to_user=from_user,
    )
    poster_key = "" if item.get("skip_tmdb") else cache_tmdb_poster(str(item.get("poster_url") or ""))
    _run_transfer_job(
        payload,
        int(started["id"]),
        interaction_cloud_download_child=cloud_download_child if target == "cloud" else "",
    )
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
    if _is_ongoing_media(item, detail):
        _register_interaction_tracking(item, payload, int(started["id"]), from_user)


def _wecom_cloud_providers(target: str) -> tuple[str, ...]:
    if target != "cloud":
        return (resolve_provider_key(target, None),)
    settings = get_settings()
    interaction_provider_keys = getattr(settings, "interaction_provider_keys", None)
    enabled = interaction_provider_keys() if callable(interaction_provider_keys) else settings.enabled_provider_keys()
    providers: list[str] = []
    for provider in ("quark", "p115"):
        if provider not in enabled:
            continue
        try:
            providers.append(resolve_provider_key(target, provider))
        except ValueError:
            continue
    if providers:
        return tuple(dict.fromkeys(providers))
    return (resolve_provider_key(target, None),)


def _interaction_transfer_snapshot(
    item: dict,
    provider: str,
    season_number: int | None,
    preferred_share_urls: tuple[str, ...],
) -> tuple[list[str], list[int], bool, dict]:
    """Reuse the same verified short-lived resource plan as discovery and the extension."""
    title = str(item.get("title") or "")
    year = str(item.get("year") or "")
    media_type = str(item.get("media_type") or "movie")
    tmdb_id = int(item.get("tmdb_id") or 0)
    snapshot: dict = {}
    if tmdb_id > 0 and provider in {"quark", "p115", "qas"}:
        try:
            snapshot = probe_resource_availability(
                tmdb_id,
                media_type,
                season_number,
                title=title,
                year=year,
                refresh=False,
                provider=provider,
            )
        except Exception:
            snapshot = {}

    verified_urls = [str(url) for url in snapshot.get("transfer_share_urls") or () if str(url).strip()]
    reusable = bool(snapshot.get("ready") and snapshot.get("plan_reusable") and verified_urls)
    urls = verified_urls if reusable else [str(url) for url in preferred_share_urls if str(url).strip()]
    episode_numbers = (
        [int(number) for number in snapshot.get("episode_numbers") or () if int(number) > 0]
        if media_type != "movie"
        else []
    )
    coverage_data = snapshot.get("coverage") if reusable and isinstance(snapshot.get("coverage"), dict) else {}
    coverage = build_episode_coverage(
        total=coverage_data.get("total_episode_numbers") or (),
        aired=coverage_data.get("aired_episode_numbers") or (),
        available=coverage_data.get("available_episode_numbers") or episode_numbers,
        transferred=coverage_data.get("transferred_episode_numbers") or (),
    )
    plan = build_media_plan(
        entrypoint=interaction_request_source(),
        provider=provider,
        identity=media_identity(
            tmdb_id=tmdb_id,
            media_type=media_type,
            category=str(item.get("category") or ""),
            title=title,
            year=year,
            season_number=season_number,
        ),
        episode_numbers=episode_numbers,
        preferred_share_urls=urls,
        coverage=coverage,
    )
    return urls, episode_numbers, reusable, plan


def _start_wecom_provider_group(
    item: dict,
    target: str,
    query: str,
    from_user: str,
    public_base_url: str,
    providers: tuple[str, ...],
    season_number: int | None,
    preferred_share_urls: tuple[str, ...],
) -> None:
    title = str(item.get("title") or query)
    year = str(item.get("year") or "")
    season_label = f" S{season_number:02d}" if season_number else ""
    with db() as conn:
        batch_id = int(
            conn.execute(
                """
                INSERT INTO transfer_batches(
                    tmdb_id,media_type,display_title,target,status,message,providers_json,seasons_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    int(item.get("tmdb_id") or 0),
                    str(item.get("media_type") or "movie"),
                    title,
                    target,
                    "running",
                    "微信已同时启动多网盘转存",
                    json.dumps(list(providers), ensure_ascii=False),
                    json.dumps([season_number] if season_number is not None else [], ensure_ascii=False),
                ),
            ).lastrowid
        )

    jobs: list[tuple[TransferCreate, int, bool]] = []
    for provider in providers:
        planned_urls, planned_episodes, preferred_only, media_plan = _interaction_transfer_snapshot(
            item,
            provider,
            season_number,
            preferred_share_urls,
        )
        payload = TransferCreate(
            tmdb_id=int(item.get("tmdb_id") or 0),
            media_type=str(item.get("media_type") or "movie"),
            category=str(item.get("category") or ""),
            title=title,
            year=year,
            poster_url=str(item.get("poster_url") or ""),
            overview=str(item.get("overview") or ""),
            target=target,
            season_number=season_number,
            provider=provider,
            episode_numbers=planned_episodes,
            preferred_share_urls=planned_urls,
            preferred_share_only=preferred_only,
            simple_matching=str(item.get("media_type") or "") == "tv",
            skip_tmdb=bool(item.get("skip_tmdb")),
            request_source=interaction_request_source(),
            request_user=from_user,
            media_plan=media_plan,
        )
        started = enqueue_transfer(payload, batch_id=batch_id)
        job_id = int(started["id"])
        with db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)",
                (batch_id, job_id),
            )
        jobs.append((payload, job_id, bool(started.get("duplicate"))))

    provider_lines = "\n".join(
        f"{provider_label(payload.provider or '')}：任务 #{job_id}"
        for payload, job_id, _duplicate in jobs
    )
    send_wecom_app(
        f"MediaIndex\n\n{title}{f' ({year})' if year else ''}{season_label} 已同时启动夸克和 115 转存。\n"
        f"{provider_lines}\n\n两边结果会分别反馈；若一边先完成，另一边缺失，将自动尝试通过 OpenList 复制。",
        to_user=from_user,
    )

    try:
        _run_transfer_batch(batch_id, jobs)
    except Exception as exc:
        with db() as conn:
            conn.execute(
                "UPDATE transfer_batches SET status='failed',message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (f"微信多网盘任务执行失败：{type(exc).__name__}", batch_id),
            )
        send_wecom_app(
            f"MediaIndex\n\n{title} 多网盘转存执行失败：{type(exc).__name__}\n批次 #{batch_id}",
            to_user=from_user,
        )
        return

    for _payload, job_id, _duplicate in jobs:
        with db() as conn:
            state = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        if state and state["status"] == "needs_review":
            _start_candidate_selection(job_id, from_user, public_base_url)
    _send_wecom_provider_group_result(batch_id, title, from_user)


def _send_wecom_provider_group_result(batch_id: int, title: str, from_user: str) -> None:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id,provider,status,stage,message FROM transfer_jobs
            WHERE batch_id=? ORDER BY provider,id
            """,
            (batch_id,),
        ).fetchall()
        batch = conn.execute("SELECT status,message FROM transfer_batches WHERE id=?", (batch_id,)).fetchone()
    lines = [f"MediaIndex\n\n{title} 多网盘转存结果："]
    for row in rows:
        status = str(row["status"] or "")
        status_label = {
            "done": "已完成",
            "triggered": "已提交",
            "needs_review": "待确认资源",
            "failed": "失败",
            "running": "处理中",
        }.get(status, status or "未知")
        detail = _short(str(row["message"] or ""), 150)
        lines.append(f"{provider_label(str(row['provider'] or ''))}：{status_label}（任务 #{row['id']}）")
        if detail:
            lines.append(f"  {detail}")
    if batch:
        lines.append(f"整体：{_short(str(batch['message'] or ''), 180)}（批次 #{batch_id}）")
    send_wecom_app("\n".join(lines), to_user=from_user)


def select_media_options(query: str, results: list[dict]) -> list[dict]:
    needle = _compact_title(query)
    explicit_derivative_query = any(marker in needle for marker in _MEDIA_DERIVATIVE_MARKERS)
    ranked = []
    for item in results:
        title = _compact_title(str(item.get("title") or ""))
        if not title:
            continue
        if not explicit_derivative_query and any(marker in title for marker in _MEDIA_DERIVATIVE_MARKERS):
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


def select_season_number(client: TmdbClient, item: dict, *, detail: dict | None = None) -> int | None:
    if item.get("media_type") not in {"tv", "variety"}:
        return None
    resolved_detail = detail if detail is not None else client.details(str(item["media_type"]), int(item["tmdb_id"]))
    seasons = resolved_detail.get("seasons") or []
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


def _is_ongoing_media(item: dict, detail: dict) -> bool:
    return (
        item.get("media_type") in {"tv", "variety"}
        and int(item.get("tmdb_id") or 0) > 0
        and str(detail.get("status") or "").strip()
        in {"Returning Series", "In Production", "Planned", "Pilot"}
    )


def _register_interaction_tracking(
    item: dict,
    payload: TransferCreate,
    job_id: int,
    from_user: str,
) -> None:
    with db() as conn:
        row = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if not row or (
        str(row["status"] or "") not in {"done", "triggered"}
        and str(row["stage"] or "") != "no_resource"
    ):
        return
    try:
        result = register_tracking_task(
            TrackingRegistration(
                tmdb_id=payload.tmdb_id,
                media_type=payload.media_type,
                category=payload.category,
                title=payload.title,
                year=payload.year,
                poster_url=payload.poster_url,
                overview=payload.overview,
                season_number=int(payload.season_number or 1),
                save_target=payload.target,
                provider=payload.provider,
            )
        )
    except Exception as exc:
        transfer_state = "本次暂无资源" if str(row["stage"] or "") == "no_resource" else "转存已完成"
        send_wecom_app(
            f"MediaIndex\n\n{transfer_state}，但加入智能追更失败：{type(exc).__name__}",
            to_user=from_user,
        )
        return
    send_wecom_app(
        "MediaIndex\n\n"
        f"{item.get('title') or payload.title} 已加入智能追更；播出日期跟随 TMDB，"
        f"默认检查时间 {result.get('check_time') or get_settings().tracking_check_time}。",
        to_user=from_user,
    )


def _compact_title(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


_MEDIA_DERIVATIVE_MARKERS = (
    "幕后",
    "特辑",
    "纪录片",
    "花絮",
    "预告",
)


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


def handle_interaction_choice(
    choice: int,
    from_user: str,
    public_base_url: str,
    *,
    title: str = "",
    year: str = "",
) -> bool:
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
            _start_resource_target_selection(
                selected,
                str(payload.get("target") or "cloud"),
                str(payload.get("query") or selected.get("title") or ""),
                from_user,
                public_base_url or str(payload.get("public_base_url") or ""),
                preferred_share_urls=tuple(str(url) for url in payload.get("preferred_share_urls") or () if url),
            )
        except Exception as exc:
            send_wecom_app(f"MediaIndex\n\n开始转存失败：{type(exc).__name__}", to_user=from_user)
        return True
    if interaction_type == "resource_target":
        item = dict(payload.get("item") or {})
        item["provider"] = str(selected.get("provider") or "")
        item["category"] = str(selected.get("category") or item.get("category") or "")
        cloud_download_child = str(selected.get("cloud_download_child") or "").strip()
        if str(payload.get("target") or "cloud") == "cloud" and not cloud_download_child:
            send_wecom_app(
                "MediaIndex\n\n这次目录选择已过期，请重新发送资源名并选择当前云下载子目录。",
                to_user=from_user,
            )
            return True
        try:
            _start_resource_transfer(
                item,
                str(payload.get("target") or "cloud"),
                str(payload.get("query") or item.get("title") or ""),
                from_user,
                public_base_url or str(payload.get("public_base_url") or ""),
                preferred_share_urls=tuple(str(url) for url in payload.get("preferred_share_urls") or () if url),
                cloud_download_child=cloud_download_child,
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
    if interaction_type == "strm_directory":
        _schedule_selected_strm_directory(selected, from_user)
        return True
    if interaction_type == "direct_link":
        _transfer_direct_link_to_selected_folder(
            payload,
            selected,
            from_user,
            title=title,
            year=year,
        )
        return True
    return False


def start_strm_directory_selection(from_user: str) -> None:
    options, errors = _strm_directory_options()
    if not options:
        detail = "\n".join(errors) if errors else "没有可扫描的一级子目录。"
        send_wecom_app(f"MediaIndex STRM 指定目录扫描\n\n{detail}", to_user=from_user)
        return
    truncated = len(options) > 50
    options = options[:50]
    save_interaction(from_user, "strm_directory", {"options": options})
    lines = [f"{index}. {_short(str(item['label']), 48)}" for index, item in enumerate(options, start=1)]
    notes = []
    if truncated:
        notes.append("子目录较多，本次只显示前 50 个。")
    notes.extend(errors)
    suffix = f"\n\n{' '.join(notes)}" if notes else ""
    send_wecom_app(
        "MediaIndex STRM 指定目录扫描\n\n请选择来源根目录下的一级子目录，并回复数字：\n\n"
        + "\n".join(lines)
        + suffix
        + "\n\n回复“取消”可放弃本次扫描。",
        to_user=from_user,
        buttons=_choice_buttons(options),
    )


def _strm_directory_options() -> tuple[list[dict[str, str]], list[str]]:
    try:
        directories, failures = list_strm_root_directories()
    except StrmInteractionError as exc:
        return [], [f"{exc}。"]
    options = [
        {
            "provider": directory.provider,
            "path": directory.path,
            "label": f"{provider_label(directory.provider)}：{directory.name}",
        }
        for directory in directories
    ]
    errors = [
        f"{provider_label(failure.provider)}：{_short(failure.message, 72)}"
        for failure in failures
    ]
    return options, errors


def _schedule_selected_strm_directory(selected: dict, from_user: str) -> None:
    from app.services.scheduler import schedule_interaction_strm_directory_scan

    provider = str(selected.get("provider") or "")
    path = str(selected.get("path") or "")
    try:
        result = schedule_interaction_strm_directory_scan(provider, path)
    except Exception as exc:
        send_wecom_app(
            f"MediaIndex STRM 指定目录扫描\n\n创建任务失败：{_short(str(exc), 120)}",
            to_user=from_user,
        )
        return
    send_wecom_app(
        f"MediaIndex STRM 指定目录扫描\n\n已为 {provider_label(provider)} 的“{path.rsplit('/', 1)[-1]}”创建全量扫描任务 #{result['job_id']}。",
        to_user=from_user,
    )


def parse_direct_link_metadata(command: str) -> tuple[str, str]:
    text = str(command or "").strip()
    year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)
    year = year_match.group(1) if year_match else ""
    text = re.sub(r"年份?\s*[：:]?\s*(?:19|20)\d{2}", "", text, flags=re.IGNORECASE)
    if year_match:
        text = text.replace(year, " ")
    text = re.sub(r"^(?:资源名|片名|名称)\s*[：:]?\s*", "", text).strip(" ：:，,\t")
    return text, year


def parse_direct_link_choice(command: str) -> tuple[int, str, str] | None:
    match = re.fullmatch(r"\s*(\d+)(?:\s+(.+?))?\s*", str(command or ""), flags=re.DOTALL)
    if not match:
        return None
    title, year = parse_direct_link_metadata(match.group(2) or "")
    return int(match.group(1)), title, year


def start_direct_link_target_selection(
    command: str,
    from_user: str,
    *,
    title: str = "",
    year: str = "",
    category: str = "movie",
) -> None:
    try:
        request = prepare_direct_link_request(command, title=title, year=year, category=category)
    except ValueError as exc:
        send_wecom_app(f"MediaIndex\n\n{exc}", to_user=from_user)
        return
    options = [
        {
            "provider": option.provider,
            "path": option.path,
            "label": option.label,
            "category": (
                getattr(option, "category", "")
                if isinstance(getattr(option, "category", ""), str) and getattr(option, "category", "")
                else infer_direct_link_category(option.provider, option.label)
            ),
        }
        for option in request.options
    ]
    resource_name = resolve_direct_link_resource_name(command, request.provider) or "待识别资源"
    if not options:
        clear_interaction(from_user)
        send_wecom_app(
            f"MediaIndex\n\n已识别资源“{_short(resource_name, 80)}”，但云下载路径 {request.root_path} 下暂无可选子文件夹。请先在网盘中创建子文件夹后重试。",
            to_user=from_user,
        )
        return
    save_interaction(
        from_user,
        "direct_link",
        {
            "command": command,
            "link": request.link,
            "provider": request.provider,
            "root_path": request.root_path,
            "options": options,
            "title": title,
            "year": year,
            "category": category,
            "resource_name": resource_name,
        },
    )
    provider = provider_label(request.provider)
    lines = [f"{index}. {item['label']}" for index, item in enumerate(options, start=1)]
    send_wecom_app(
        f"MediaIndex\n\n即将把资源“{_short(resource_name, 80)}”通过 {provider} 转存到云下载路径：{request.root_path}\n\n"
        + "请回复数字选择目标文件夹：\n\n"
        + "\n".join(lines)
        + "\n\n如需提供后续整理用的准确名称，请在文件夹编号后发送媒体名称及年份，例如：3 黑夜告白 2026。年份可省略；这不会改变所选云下载文件夹。"
        + "\n\n回复“取消”可放弃本次转存。",
        to_user=from_user,
        buttons=_choice_buttons(options),
    )


def _transfer_direct_link_to_selected_folder(
    payload: dict,
    selected: dict,
    from_user: str,
    *,
    title: str = "",
    year: str = "",
) -> None:
    command = str(payload.get("command") or payload.get("link") or "")
    path = str(selected.get("path") or "").strip()
    provider = str(selected.get("provider") or payload.get("provider") or "")
    send_wecom_app(
        "MediaIndex\n\n开始转存",
        to_user=from_user,
    )
    request_kwargs = {"save_path": path}
    selected_title = title.strip() or str(payload.get("title") or "").strip()
    selected_year = year.strip() or str(payload.get("year") or "").strip()
    detected_name = str(payload.get("resource_name") or "").strip()
    if detected_name and detected_name != "待识别资源":
        request_kwargs["staging_name"] = detected_name
    if selected_title:
        request_kwargs.update(
            {
                "title": selected_title,
                "year": selected_year,
                "category": str(selected.get("category") or payload.get("category") or "movie"),
                "preserve_save_path": True,
            }
        )
    source = interaction_request_source()
    if source != "wecom":
        request_kwargs["request_source"] = source
    result = handle_direct_link_transfer(command, from_user, **request_kwargs)
    if result.ok:
        send_wecom_app(f"MediaIndex\n\n{result.message}", to_user=from_user)
    else:
        send_wecom_app(f"MediaIndex\n\n转存失败：{result.message}", to_user=from_user)


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
        buttons=_choice_buttons(options),
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
        buttons=_choice_buttons(options),
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


def _choice_buttons(options: list[dict]) -> list[list[dict[str, str]]]:
    buttons: list[list[dict[str, str]]] = []
    for index, item in enumerate(options, start=1):
        label = str(
            item.get("label")
            or item.get("source_title")
            or item.get("title")
            or f"选项 {index}"
        )
        buttons.append([{"text": f"{index}. {_short(label, 38)}", "callback_data": f"mi:choice:{index}"}])
    buttons.append([{"text": "取消", "callback_data": "mi:cancel"}])
    return buttons


def _media_type_label(media_type: str) -> str:
    return {"movie": "电影", "tv": "剧集", "variety": "综艺"}.get(media_type, "影视")


def _category_label(category: str) -> str:
    return {
        "movie": "电影",
        "tv": "电视剧",
        "anime": "动漫",
        "variety": "综艺",
        "documentary": "纪录片",
    }.get(category, category or "媒体")


def provider_label(provider: str) -> str:
    return {"qas": "夸克", "quark": "夸克", "p115": "115"}.get(provider, "网盘")


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
        "emby": "/emby",
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
            "/emby  Emby 媒体条目和活跃用户\n"
            "/strm_full  对已启用网盘执行 STRM 全量扫描\n"
            "/strm_incremental  对已启用网盘执行 STRM 增量扫描\n"
            "/strm_directory  选择来源根目录的一级子目录进行全量扫描\n"
            "/download  提示输入资源名或下载链接\n"
            "/help  指令帮助\n"
            "/cancel  取消当前选择\n\n"
            "发送资源名：搜索资源后选择网盘云下载子目录\n"
            "发送“本地 资源名”：保存到本地\n"
            "发送夸克/115 分享链接：选择对应网盘的云下载子目录\n"
            "发送磁力/电驴/HTTP 链接：选择 115 云下载子目录后提交离线下载"
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
    if normalized == "/emby":
        return emby_status_reply()
    return "MediaIndex\n\n未识别的指令。发送 /help 查看可用指令。"


def _status_reply() -> str:
    with db() as conn:
        active_tracking = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT 1 FROM tracking_tasks
                WHERE status='active'
                GROUP BY tmdb_id,media_type,season_number
            )
            """
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
            WITH recent_tasks AS (
                SELECT tmdb_id,media_type,COALESCE(season_number,1) AS season_number,
                       MAX(updated_at) AS latest_updated_at,MAX(id) AS latest_id
                FROM tracking_tasks
                WHERE status='active'
                GROUP BY tmdb_id,media_type,COALESCE(season_number,1)
                ORDER BY latest_updated_at DESC,latest_id DESC
                LIMIT 5
            )
            SELECT task.tmdb_id,task.media_type,task.title,task.season_number,
                   task.provider,task.decision_state,task.updated_at,task.id
            FROM recent_tasks AS recent
            JOIN tracking_tasks AS task
              ON task.tmdb_id=recent.tmdb_id
             AND task.media_type=recent.media_type
             AND COALESCE(task.season_number,1)=recent.season_number
            WHERE task.status='active'
            ORDER BY recent.latest_updated_at DESC,recent.latest_id DESC,task.updated_at DESC,task.id DESC
            """
        ).fetchall()
    grouped: dict[tuple[int, str, int], dict] = {}
    for row in rows:
        key = (int(row["tmdb_id"]), str(row["media_type"]), int(row["season_number"] or 1))
        task = grouped.setdefault(
            key,
            {
                "title": str(row["title"]),
                "season_number": int(row["season_number"] or 1),
                "states": [],
            },
        )
        task["states"].append((str(row["provider"] or ""), str(row["decision_state"] or "pending")))
    items = []
    provider_order = {"qas": 0, "quark": 1, "p115": 2}
    for task in list(grouped.values())[:5]:
        states = sorted(task["states"], key=lambda item: provider_order.get(item[0], 99))
        unique_states = list(dict.fromkeys(state for _provider, state in states))
        if len(unique_states) == 1:
            state_summary = unique_states[0]
        else:
            state_summary = "；".join(f"{provider_label(provider)} {state}" for provider, state in states)
        items.append(f"{task['title']} S{task['season_number']:02d} ({state_summary})")
    return _list_reply("智能追更", items)


def _wishlist_reply() -> str:
    with db() as conn:
        rows = conn.execute(
            """
            WITH recent_media AS (
                SELECT tmdb_id,media_type,MAX(created_at) AS latest_created_at,MAX(id) AS latest_id
                FROM wishlist
                GROUP BY tmdb_id,media_type
                ORDER BY latest_created_at DESC,latest_id DESC
                LIMIT 5
            )
            SELECT wish.tmdb_id,wish.media_type,wish.title,wish.season_number,
                   wish.provider,wish.status,COALESCE(wish.enabled,1) AS enabled
            FROM recent_media AS recent
            JOIN wishlist AS wish
              ON wish.tmdb_id=recent.tmdb_id AND wish.media_type=recent.media_type
            ORDER BY recent.latest_created_at DESC,recent.latest_id DESC,wish.id DESC
            """
        ).fetchall()
    grouped: dict[tuple[int, str], dict] = {}
    for row in rows:
        key = (int(row["tmdb_id"]), str(row["media_type"]))
        item = grouped.setdefault(
            key,
            {
                "title": str(row["title"]),
                "season_number": int(row["season_number"] or 0),
                "states": [],
            },
        )
        status = str(row["status"] or "pending") if bool(row["enabled"]) else "已停用"
        item["states"].append((str(row["provider"] or ""), status))
    items: list[str] = []
    provider_order = {"qas": 0, "quark": 1, "p115": 2}
    for item in grouped.values():
        states = sorted(item["states"], key=lambda value: provider_order.get(value[0], 99))
        state_text = "；".join(f"{provider_label(provider)} {status}" for provider, status in states)
        season_text = f" S{item['season_number']:02d}" if item["season_number"] else ""
        items.append(f"{item['title']}{season_text} ({state_text})")
    return _list_reply("愿望单", items)


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
