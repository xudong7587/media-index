from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.db.database import db
from app.domain.media import MediaTarget
from app.clients.pansou import infer_share_provider
from app.services.candidate_ranker import compact
from app.services.direct_link_transfer import extract_download_links


class ChannelMonitorError(RuntimeError):
    pass


_transfer_starter: Callable[[dict[str, Any], str, str, str], int] | None = None
_resource_transfer_starter: Callable[[int, str, str, str, str, str], None] | None = None


def configure_transfer_starter(starter: Callable[[dict[str, Any], str, str, str], int]) -> None:
    """Inject the application workflow at startup without importing HTTP routes."""
    global _transfer_starter
    _transfer_starter = starter


def configure_resource_transfer_starter(
    starter: Callable[[int, str, str, str, str, str], None],
) -> None:
    """Inject the asynchronous TG -> cloud-download workflow at startup."""
    global _resource_transfer_starter
    _resource_transfer_starter = starter


def list_channel_subscriptions() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM channel_subscriptions ORDER BY id DESC").fetchall()
    return [_subscription_view(dict(row)) for row in rows]


def delete_channel_subscriptions(subscription_ids: list[int]) -> dict[str, Any]:
    """Delete only MediaIndex's local TG selections and their local index."""
    normalized = list(dict.fromkeys(int(value) for value in subscription_ids if int(value) > 0))
    if not normalized:
        raise ChannelMonitorError("请至少选择一个要删除的频道")
    placeholders = ",".join("?" for _ in normalized)
    with db() as conn:
        rows = conn.execute(
            f"SELECT id,channel_id,display_name FROM channel_subscriptions WHERE id IN ({placeholders})",
            normalized,
        ).fetchall()
        found_ids = [int(row["id"]) for row in rows]
        if found_ids:
            found_placeholders = ",".join("?" for _ in found_ids)
            conn.execute(f"DELETE FROM channel_resources WHERE subscription_id IN ({found_placeholders})", found_ids)
            conn.execute(f"DELETE FROM channel_messages WHERE subscription_id IN ({found_placeholders})", found_ids)
            conn.execute(f"DELETE FROM channel_subscriptions WHERE id IN ({found_placeholders})", found_ids)
    found = set(found_ids)
    return {
        "deleted_ids": found_ids,
        "missing_ids": [value for value in normalized if value not in found],
        "deleted_channels": [str(row["display_name"] or row["channel_id"]) for row in rows],
        "message": f"已从 MediaIndex 删除 {len(found_ids)} 个频道及其本地索引；PanSou 频道配置未改变。",
    }


def upsert_channel_subscription(
    channel_id: str,
    *,
    display_name: str = "",
    enabled: bool = True,
    auto_transfer: bool = False,
    auto_save_resources: bool = False,
    positive_keywords: list[str] | None = None,
    negative_keywords: list[str] | None = None,
    auto_classify: bool = False,
    cloud_download_child: str = "",
    require_douban_match: bool = False,
    douban_titles: list[str] | None = None,
) -> dict[str, Any]:
    safe_channel_id = _safe_channel_id(channel_id)
    titles = _safe_titles(douban_titles or [])
    positive = _safe_keywords(positive_keywords or [])
    negative = _safe_keywords(negative_keywords or [])
    child = _safe_cloud_download_child(cloud_download_child)
    if auto_save_resources and not auto_classify and not child:
        raise ChannelMonitorError("关闭自动分类时必须指定云下载直属子目录")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO channel_subscriptions(
              channel_id,display_name,enabled,auto_transfer,auto_save_resources,
              positive_keywords_json,negative_keywords_json,auto_classify,cloud_download_child,
              require_douban_match,douban_titles_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(channel_id) DO UPDATE SET
              display_name=excluded.display_name,enabled=excluded.enabled,auto_transfer=excluded.auto_transfer,
              auto_save_resources=excluded.auto_save_resources,
              positive_keywords_json=excluded.positive_keywords_json,
              negative_keywords_json=excluded.negative_keywords_json,
              auto_classify=excluded.auto_classify,
              cloud_download_child=excluded.cloud_download_child,
              require_douban_match=excluded.require_douban_match,douban_titles_json=excluded.douban_titles_json,updated_at=CURRENT_TIMESTAMP
            """,
            (
                safe_channel_id, str(display_name or "").strip()[:120], int(enabled), int(auto_transfer),
                int(auto_save_resources), json.dumps(positive, ensure_ascii=False),
                json.dumps(negative, ensure_ascii=False), int(auto_classify), child,
                int(require_douban_match), json.dumps(titles, ensure_ascii=False),
            ),
        )
        row = conn.execute("SELECT * FROM channel_subscriptions WHERE channel_id=?", (safe_channel_id,)).fetchone()
    return _subscription_view(dict(row))


def classify_pansou_channel_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize structured PanSou channel evidence and mark existing rows."""
    with db() as conn:
        rows = conn.execute("SELECT channel_id FROM channel_subscriptions").fetchall()
    existing = {_channel_identity_key(str(row["channel_id"])) for row in rows}
    classified: list[dict[str, Any]] = []
    seen_channels: set[str] = set()
    seen_unrecognized: set[str] = set()
    for source in sources:
        raw = str(source.get("raw_value") or "").strip()
        evidence_field = str(source.get("evidence_field") or "")
        channel_id = normalize_telegram_channel_id(raw, allow_plain_username=True)
        if not channel_id:
            key = raw.casefold()
            if not raw or key in seen_unrecognized:
                continue
            seen_unrecognized.add(key)
            classified.append({
                "raw_value": raw,
                "channel_id": "",
                "display_name": "",
                "status": "unrecognized",
                "reason": "PanSou 返回了来源字段，但它不是可验证的 t.me 链接、@username 或数字频道 ID",
                "evidence_field": evidence_field,
            })
            continue
        identity = _channel_identity_key(channel_id)
        if identity in seen_channels:
            continue
        seen_channels.add(identity)
        is_existing = identity in existing
        classified.append({
            "raw_value": raw,
            "channel_id": channel_id,
            "display_name": channel_id.removeprefix("@"),
            "status": "existing" if is_existing else "importable",
            "reason": "已存在，导入时会跳过且不会覆盖规则" if is_existing else "来自 PanSou 当前配置的 Telegram 频道列表",
            "evidence_field": evidence_field,
        })
    return classified


def import_pansou_channels(values: list[str]) -> dict[str, Any]:
    """Create only missing channel sources with side-effect-safe defaults."""
    normalized: list[str] = []
    unrecognized: list[str] = []
    seen: set[str] = set()
    for value in values:
        channel_id = normalize_telegram_channel_id(value, allow_plain_username=False)
        if not channel_id:
            unrecognized.append(str(value or "").strip())
            continue
        identity = _channel_identity_key(channel_id)
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(channel_id)

    with db() as conn:
        rows = conn.execute("SELECT channel_id FROM channel_subscriptions").fetchall()
    existing_identities = {_channel_identity_key(str(row["channel_id"])) for row in rows}
    imported: list[dict[str, Any]] = []
    existing: list[str] = []
    for channel_id in normalized:
        identity = _channel_identity_key(channel_id)
        if identity in existing_identities:
            existing.append(channel_id)
            continue
        imported.append(upsert_channel_subscription(
            channel_id,
            display_name=channel_id.removeprefix("@"),
            enabled=True,
            auto_transfer=False,
            auto_save_resources=False,
            positive_keywords=[],
            negative_keywords=[],
            auto_classify=False,
            cloud_download_child="",
            require_douban_match=False,
            douban_titles=[],
        ))
        existing_identities.add(identity)
    return {
        "imported": imported,
        "existing": existing,
        "unrecognized": [value for value in unrecognized if value],
        "message": f"已导入 {len(imported)} 个频道；跳过 {len(existing)} 个已有频道；无法识别 {len(unrecognized)} 个。",
    }


def process_channel_post(message: dict[str, Any]) -> dict[str, Any] | None:
    """Index a channel post, then apply its explicit auto-save or legacy wishlist policy."""
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    telegram_channel_id = str(chat.get("id") or "").strip()
    username_channel_id = normalize_telegram_channel_id(str(chat.get("username") or ""), allow_plain_username=True)
    message_id = int(message.get("message_id") or 0)
    text = str(message.get("text") or message.get("caption") or "").strip()
    if not telegram_channel_id or not message_id or not text:
        return None
    with db() as conn:
        subscription_row = conn.execute(
            """
            SELECT * FROM channel_subscriptions
            WHERE enabled=1 AND (channel_id=? COLLATE NOCASE OR channel_id=? COLLATE NOCASE)
            ORDER BY CASE WHEN channel_id=? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (telegram_channel_id, username_channel_id or "", telegram_channel_id),
        ).fetchone()
        if not subscription_row:
            return None
        subscription = dict(subscription_row)
        channel_id = str(subscription["channel_id"])
        existing = conn.execute(
            "SELECT * FROM channel_messages WHERE channel_id=? AND message_id=?",
            (channel_id, message_id),
        ).fetchone()

    links = _share_links(text)
    if existing:
        with db() as conn:
            resource_ids = _index_resources(conn, dict(existing), subscription, message, text, links)
        _dispatch_auto_save_resources(subscription, resource_ids, text, channel_id)
        with db() as conn:
            current = conn.execute("SELECT * FROM channel_messages WHERE id=?", (int(existing["id"]),)).fetchone()
            return _message_view(conn, dict(current))

    auto_save_enabled = bool(subscription.get("auto_save_resources"))
    filter_ok, filter_message = _channel_filter_result(text, subscription)
    match = _match_wishlist(text)
    douban_required = bool(subscription["require_douban_match"])
    douban_ok = _matches_titles(text, _parse_titles(subscription["douban_titles_json"]))
    if not links:
        state, message_safe, wishlist = "ignored", "未发现支持的网盘分享、磁力、电驴或下载链接", None
    elif auto_save_enabled and not filter_ok:
        state, message_safe, wishlist = "ignored", filter_message, None
    elif auto_save_enabled:
        state, message_safe, wishlist = "transfer_queued", "已通过频道关键词规则，正在提交云下载暂存", None
    elif not match:
        state, message_safe, wishlist = "needs_review", "已进入全局候选索引；未命中精确愿望单，不自动转存", None
    elif douban_required and not douban_ok:
        state, message_safe, wishlist = "ignored", "命中愿望清单，但未命中当前豆瓣榜单过滤", match
    else:
        state, message_safe, wishlist = "matched", "已进入全局候选索引并命中统一愿望单规则", match
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO channel_messages(subscription_id,channel_id,message_id,text_preview,link_count,matched_wishlist_id,state,message_safe)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                int(subscription["id"]), channel_id, message_id, _safe_preview(text), len(links),
                wishlist["id"] if wishlist else None, state, message_safe,
            ),
        )
        row_id = int(cursor.lastrowid)
        row = conn.execute("SELECT * FROM channel_messages WHERE id=?", (row_id,)).fetchone()
        resource_ids = _index_resources(conn, dict(row), subscription, message, text, links)
    if state == "transfer_queued":
        _dispatch_auto_save_resources(subscription, resource_ids, text, channel_id)
    elif state == "matched" and bool(subscription["auto_transfer"]):
        provider, share_url = links[0]
        job_id = _enqueue_transfer(wishlist, share_url, channel_id, provider)
        with db() as conn:
            conn.execute(
                "UPDATE channel_messages SET state='transfer_started',transfer_job_id=?,message_safe=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id, f"已按统一规则创建{'115' if provider == 'p115' else '夸克'}转存任务", row_id),
            )
    with db() as conn:
        row = conn.execute("SELECT * FROM channel_messages WHERE id=?", (row_id,)).fetchone()
        return _message_view(conn, dict(row))


def complete_channel_resource_transfer(
    resource_id: int,
    *,
    ok: bool,
    job_id: int | None,
    message: str,
) -> None:
    """Persist one asynchronous channel transfer result without exposing its link."""
    safe_message = re.sub(r"(?:magnet:\?\S+|ed2k://\S+|https?://\S+)", "资源链接", str(message or ""))[:500]
    with db() as conn:
        row = conn.execute(
            "SELECT channel_message_id FROM channel_resources WHERE id=?",
            (int(resource_id),),
        ).fetchone()
        if not row:
            return
        message_id = int(row["channel_message_id"])
        conn.execute(
            """UPDATE channel_resources SET transfer_state=?,transfer_job_id=?,transfer_message=?,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            ("done" if ok else "failed", job_id, safe_message, int(resource_id)),
        )
        states = conn.execute(
            "SELECT transfer_state,transfer_job_id FROM channel_resources WHERE channel_message_id=?",
            (message_id,),
        ).fetchall()
        queued = sum(1 for item in states if str(item["transfer_state"] or "") == "queued")
        failed = sum(1 for item in states if str(item["transfer_state"] or "") == "failed")
        done = sum(1 for item in states if str(item["transfer_state"] or "") == "done")
        first_job_id = next((int(item["transfer_job_id"]) for item in states if item["transfer_job_id"]), None)
        if queued:
            state = "transfer_queued"
            summary = f"已提交 {done} 个资源，{queued} 个正在处理" + (f"，{failed} 个失败" if failed else "")
        elif failed and done:
            state, summary = "transfer_partial", f"{done} 个资源已提交云下载，{failed} 个失败"
        elif failed:
            state, summary = "transfer_failed", f"{failed} 个资源提交失败，请查看任务详情"
        else:
            state, summary = "transfer_started", f"{done} 个资源已提交云下载，等待自动整理"
        conn.execute(
            """UPDATE channel_messages SET state=?,message_safe=?,transfer_job_id=?,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (state, summary, first_job_id, message_id),
        )


def classify_channel_resource(text: str) -> str:
    """Return a conservative media category from explicit channel-post evidence."""
    value = str(text or "").casefold()
    rules = (
        ("variety", ("综艺", "真人秀", "variety")),
        ("concert", ("演唱会", "音乐会", "concert")),
        ("documentary", ("纪录片", "纪录", "documentary")),
        ("anime", ("动漫", "动画", "番剧", "anime")),
        ("tv", ("电视剧", "剧集", "连续剧", "短剧", "全剧", "season", "episode")),
        ("movie", ("电影", "影片", "movie", "bluray", "web-dl", "remux")),
    )
    matched = [category for category, tokens in rules if any(token in value for token in tokens)]
    if "tv" not in matched and re.search(r"\bS\d{1,2}(?:E\d{1,3})?\b|\bE\d{1,3}\b|全\s*\d+\s*集", str(text or ""), re.IGNORECASE):
        matched.append("tv")
    unique = list(dict.fromkeys(matched))
    return unique[0] if len(unique) == 1 else ""


def list_channel_messages(limit: int = 100) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT m.*,s.display_name FROM channel_messages m
            JOIN channel_subscriptions s ON s.id=m.subscription_id
            ORDER BY m.created_at DESC,m.id DESC LIMIT ?
            """,
            (max(1, min(int(limit), 300)),),
        ).fetchall()
    with db() as conn:
        return [_message_view(conn, dict(row)) for row in rows]


def search_channel_resources(target: MediaTarget, *, limit: int = 100) -> list[dict[str, Any]]:
    """Return enabled-channel candidates matching any stable TMDB title alias."""
    aliases = tuple(
        value for value in dict.fromkeys(compact(title) for title in target.search_titles)
        if len(value) >= 2 and not value.isdigit()
    )
    if not aliases:
        return []
    try:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT r.*,s.display_name FROM channel_resources r
                JOIN channel_subscriptions s ON s.id=r.subscription_id
                WHERE s.enabled=1
                ORDER BY CASE WHEN r.published_at='' THEN 1 ELSE 0 END,
                         r.published_at DESC,r.id DESC
                LIMIT 2000
                """
            ).fetchall()
    except sqlite3.OperationalError:
        # Resolvers are also used in isolated unit tests and maintenance tools
        # before application startup has initialized the optional source index.
        return []
    matched: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        haystack = str(row.get("search_text") or "")
        if not any(alias in haystack for alias in aliases):
            continue
        matched.append(
            {
                "share_url": row["share_url"],
                "title": row.get("source_title") or target.title,
                "content": row.get("content_preview") or "",
                "source": f"telegram:{row.get('display_name') or row['channel_id']}",
                "published_at": row.get("published_at") or row.get("created_at") or "",
                "cloud_type": "115" if row.get("provider") == "p115" else "quark",
                "provider": row.get("provider") or "",
            }
        )
        if len(matched) >= max(1, min(int(limit), 300)):
            break
    return matched


def update_channel_sync_status(channel_id: str, *, error: str = "", resource_found: bool = False) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE channel_subscriptions
            SET last_checked_at=CURRENT_TIMESTAMP,last_error=?,
                last_resource_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE last_resource_at END,
                updated_at=CURRENT_TIMESTAMP
            WHERE channel_id=?
            """,
            (str(error or "")[:500], int(resource_found), channel_id),
        )


def _enqueue_transfer(wishlist: dict[str, Any], share_url: str, channel_id: str, provider: str) -> int:
    if _transfer_starter is None:
        raise ChannelMonitorError("频道转存工作流尚未初始化")
    return _transfer_starter(wishlist, share_url, channel_id, provider)


def _dispatch_auto_save_resources(
    subscription: dict[str, Any],
    resource_ids: list[int],
    text: str,
    channel_id: str,
) -> None:
    if not bool(subscription.get("auto_save_resources")):
        return
    accepted, reason = _channel_filter_result(text, subscription)
    if not accepted:
        return
    category = classify_channel_resource(text) if bool(subscription.get("auto_classify")) else "movie"
    if bool(subscription.get("auto_classify")) and not category:
        _fail_channel_resources(resource_ids, "资源分类不唯一，已停止自动转存；请补充明确分类词或改为指定子目录")
        return
    child = str(subscription.get("cloud_download_child") or "").strip()
    if not bool(subscription.get("auto_classify")) and not child:
        _fail_channel_resources(resource_ids, "未指定云下载直属子目录，已停止自动转存")
        return
    with db() as conn:
        rows = conn.execute(
            f"SELECT id,provider,share_url,transfer_state FROM channel_resources WHERE id IN ({','.join('?' for _ in resource_ids)})",
            tuple(resource_ids),
        ).fetchall() if resource_ids else []
        pending = [dict(row) for row in rows if not str(row["transfer_state"] or "")]
        if pending:
            conn.executemany(
                "UPDATE channel_resources SET transfer_state='queued',transfer_message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                [(reason[:500], int(row["id"])) for row in pending],
            )
    for row in pending:
        if _resource_transfer_starter is None:
            complete_channel_resource_transfer(
                int(row["id"]), ok=False, job_id=None, message="TG 频道云下载工作流尚未初始化",
            )
            continue
        _resource_transfer_starter(
            int(row["id"]), str(row["share_url"]), channel_id,
            str(row["provider"]), category, child,
        )


def _fail_channel_resources(resource_ids: list[int], message: str) -> None:
    for resource_id in resource_ids:
        with db() as conn:
            state = conn.execute("SELECT transfer_state FROM channel_resources WHERE id=?", (int(resource_id),)).fetchone()
        if state and not str(state["transfer_state"] or ""):
            complete_channel_resource_transfer(int(resource_id), ok=False, job_id=None, message=message)


def _channel_filter_result(text: str, subscription: dict[str, Any]) -> tuple[bool, str]:
    haystack = str(text or "").casefold()
    positive = _parse_titles(str(subscription.get("positive_keywords_json") or "[]"))
    negative = _parse_titles(str(subscription.get("negative_keywords_json") or "[]"))
    blocked = next((item for item in negative if item.casefold() in haystack), "")
    if blocked:
        return False, f"命中反向关键词“{blocked}”，未自动转存"
    if positive and not any(item.casefold() in haystack for item in positive):
        return False, "未命中任何正向关键词，未自动转存"
    return True, "正向与反向关键词检查通过"


def _match_wishlist(text: str) -> dict[str, Any] | None:
    normalized = _compact(text)
    if len(normalized) < 2:
        return None
    with db() as conn:
        rows = conn.execute("SELECT * FROM wishlist WHERE status NOT IN ('deleted','completed') ORDER BY id DESC").fetchall()
    matches = []
    for row in rows:
        item = dict(row)
        title = _compact(str(item.get("title") or ""))
        if len(title) >= 2 and title in normalized:
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _share_links(text: str) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for clean in extract_download_links(text):
        _cloud_type, inferred_provider = infer_share_provider(clean)
        provider = inferred_provider or ("p115" if clean.casefold().startswith(("magnet:?", "ed2k://")) else "")
        item = (provider, clean)
        if provider and item not in values:
            values.append(item)
    return values[:10]


def _safe_channel_id(value: str) -> str:
    raw = str(value or "").strip()
    public_match = re.fullmatch(r"https://t\.me/(?:s/)?([A-Za-z0-9_]{5,32})/?", raw, re.IGNORECASE)
    if public_match:
        return f"@{public_match.group(1)}"
    if re.fullmatch(r"@[A-Za-z0-9_]{5,32}", raw):
        return raw
    if re.fullmatch(r"-?\d{1,20}", raw):
        return raw
    raise ChannelMonitorError("请输入 Telegram 频道 ID、@频道名或公开频道链接")


def normalize_telegram_channel_id(value: str, *, allow_plain_username: bool = False) -> str:
    raw = str(value or "").strip()
    if raw.casefold().startswith("tg:"):
        raw = raw[3:].strip()
    public_match = re.fullmatch(r"https?://(?:www\.)?t\.me/(?:s/)?([A-Za-z0-9_]{5,32})/?(?:\?.*)?", raw, re.IGNORECASE)
    if public_match:
        return f"@{public_match.group(1).lower()}"
    username_match = re.fullmatch(r"@([A-Za-z0-9_]{5,32})", raw)
    if username_match:
        return f"@{username_match.group(1).lower()}"
    if allow_plain_username and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", raw):
        return f"@{raw.lower()}"
    if re.fullmatch(r"-?\d{1,20}", raw):
        return raw
    return ""


def _channel_identity_key(value: str) -> str:
    normalized = normalize_telegram_channel_id(value, allow_plain_username=True)
    return normalized.casefold() if normalized else str(value or "").strip().casefold()


def _safe_titles(values: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if len(cleaned) > 1000 or any(len(value) > 160 or "\r" in value or "\n" in value for value in cleaned):
        raise ChannelMonitorError("豆瓣榜单标题无效")
    return cleaned


def _safe_keywords(values: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if len(cleaned) > 100 or any(len(value) > 100 or "\r" in value or "\n" in value for value in cleaned):
        raise ChannelMonitorError("频道关键词无效：最多 100 个，每个不超过 100 个字符")
    return cleaned


def _safe_cloud_download_child(value: str) -> str:
    child = str(value or "").strip()
    if not child:
        return ""
    if child in {".", ".."} or "/" in child or "\\" in child or any(char in child for char in "\x00\r\n"):
        raise ChannelMonitorError("云下载子目录必须是根目录下的单个直属文件夹名称")
    return child[:200]


def _parse_titles(raw: str) -> list[str]:
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [value for value in values if isinstance(value, str)]


def _matches_titles(text: str, titles: list[str]) -> bool:
    compact = _compact(text)
    return any((title := _compact(item)) and title in compact for item in titles)


def _compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _preview(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:500]


def _safe_preview(value: str) -> str:
    """Keep useful post context without persisting credentials or share URLs."""
    scrubbed = re.sub(
        r"(?:magnet:\?\S+|ed2k://\S+|https?://[^\s<>\]\[\"']+)",
        "[资源链接]",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    return _preview(scrubbed)


def _index_resources(
    conn,
    message_row: dict[str, Any],
    subscription: dict[str, Any],
    message: dict[str, Any],
    text: str,
    links: list[tuple[str, str]],
) -> list[int]:
    if not links:
        return []
    content = _safe_preview(text)
    title = _resource_title(text)
    published_at = _published_at(message.get("date"))
    message_url = str(message.get("message_url") or "").strip()[:500]
    resource_ids: list[int] = []
    for provider, share_url in links:
        conn.execute(
            """
            INSERT INTO channel_resources(
              channel_message_id,subscription_id,channel_id,message_id,provider,share_url,
              source_title,content_preview,search_text,message_url,published_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(channel_id,message_id,share_url) DO UPDATE SET
              provider=excluded.provider,source_title=excluded.source_title,
              content_preview=excluded.content_preview,search_text=excluded.search_text,
              message_url=excluded.message_url,published_at=excluded.published_at,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                int(message_row["id"]), int(subscription["id"]), str(message_row["channel_id"]),
                int(message_row["message_id"]), provider, share_url, title, content,
                compact(f"{title} {content}"), message_url, published_at,
            ),
        )
        saved = conn.execute(
            "SELECT id FROM channel_resources WHERE channel_id=? AND message_id=? AND share_url=?",
            (str(message_row["channel_id"]), int(message_row["message_id"]), share_url),
        ).fetchone()
        if saved:
            resource_ids.append(int(saved["id"]))
    return resource_ids


def _message_view(conn, row: dict[str, Any]) -> dict[str, Any]:
    count = conn.execute(
        "SELECT COUNT(*) AS count FROM channel_resources WHERE channel_message_id=?",
        (int(row["id"]),),
    ).fetchone()
    row["indexed_resource_count"] = int(count["count"] if count else 0)
    transfer_rows = conn.execute(
        "SELECT transfer_state,transfer_job_id FROM channel_resources WHERE channel_message_id=?",
        (int(row["id"]),),
    ).fetchall()
    row["transfer_job_ids"] = [int(item["transfer_job_id"]) for item in transfer_rows if item["transfer_job_id"]]
    row["transfer_states"] = [str(item["transfer_state"] or "") for item in transfer_rows]
    return row


def _resource_title(text: str) -> str:
    without_links = re.sub(
        r"(?:magnet:\?\S+|ed2k://\S+|https?://[^\s<>\]\[\"']+)",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    lines = [re.sub(r"\s+", " ", line).strip(" -—|｜") for line in without_links.splitlines()]
    return next((line[:240] for line in lines if line), _preview(without_links)[:240])


def _published_at(value: Any) -> str:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return raw[:80]


def _subscription_view(row: dict[str, Any]) -> dict[str, Any]:
    row["enabled"] = bool(row["enabled"])
    row["auto_transfer"] = bool(row["auto_transfer"])
    row["auto_save_resources"] = bool(row.get("auto_save_resources"))
    row["auto_classify"] = bool(row.get("auto_classify"))
    row["require_douban_match"] = bool(row["require_douban_match"])
    row["positive_keywords"] = _parse_titles(str(row.pop("positive_keywords_json", "[]")))
    row["negative_keywords"] = _parse_titles(str(row.pop("negative_keywords_json", "[]")))
    row["douban_titles"] = _parse_titles(str(row.pop("douban_titles_json", "[]")))
    return row
