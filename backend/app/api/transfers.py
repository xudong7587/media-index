import json
import re
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import require_user
from app.db.database import db
from app.services.transfer_service_v2 import execute_transfer_v2
from app.services.review_notification import notify_review_required
from app.services.wishlist_schedule import compute_wishlist_next_check, resolve_wishlist_target
from app.core.config import get_settings
from app.providers.registry import resolve_provider_key
from app.providers.status import normalize_provider_record, transfer_status_for_stage
from app.services.notifications import add_notification, sync_transfer_notifications
from app.services.openlist_sync import automatic_sync_allowed, sync_transfer_batch_storage, sync_transfer_outputs
from app.services.direct_link_transfer import handle_direct_link_transfer, prepare_direct_link_request

router = APIRouter(prefix="/api/transfers", tags=["transfers"], dependencies=[Depends(require_user)])


class TransferCreate(BaseModel):
    tmdb_id: int
    media_type: str
    category: str = ""
    title: str = ""
    year: str = ""
    poster_url: str = ""
    overview: str = ""
    target: str = "cloud"
    season_number: int | None = None
    provider: str | None = None
    episode_numbers: list[int] = Field(default_factory=list, max_length=1000)
    preferred_share_urls: list[str] = Field(default_factory=list, max_length=100)
    simple_matching: bool = False
    skip_tmdb: bool = False
    request_source: str = ""
    request_user: str = ""


class TransferBatchItem(BaseModel):
    provider: str
    season_number: int | None = None
    episode_numbers: list[int] = Field(default_factory=list, max_length=1000)
    preferred_share_url: str = ""


class TransferBatchCreate(BaseModel):
    tmdb_id: int
    media_type: str
    category: str = ""
    title: str = ""
    year: str = ""
    poster_url: str = ""
    overview: str = ""
    target: str = "cloud"
    items: list[TransferBatchItem] = Field(min_length=1, max_length=100)
    simple_matching: bool = False


class DirectLinkOptionsRequest(BaseModel):
    link: str = Field(min_length=1, max_length=20000)
    title: str = Field(default="", max_length=200)
    year: str = Field(default="", max_length=10)
    category: str = Field(default="movie", max_length=30)


class DirectLinkTransferCreate(BaseModel):
    link: str = Field(min_length=1, max_length=20000)
    save_path: str = Field(default="", max_length=1000)
    title: str = Field(default="", max_length=200)
    year: str = Field(default="", max_length=10)
    category: str = Field(default="movie", max_length=30)


@router.get("")
def list_transfers():
    with db() as conn:
        rows = conn.execute("SELECT * FROM transfer_jobs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [normalize_provider_record(dict(row)) for row in rows]


@router.get("/wecom-records")
def list_wecom_transfer_records(limit: int = Query(default=30, ge=1, le=100)):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id,display_title,media_type,provider,status,stage,message,save_path,
                   request_source,request_user,created_at,finished_at
            FROM transfer_jobs
            WHERE request_source IN ('wecom', 'telegram')
              AND NOT EXISTS (
                SELECT 1 FROM transfer_record_hidden hidden
                WHERE hidden.job_id=transfer_jobs.id
              )
            ORDER BY created_at DESC,id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


@router.delete("/wecom-records")
def clear_wecom_transfer_records():
    with db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO transfer_record_hidden(job_id)
            SELECT id FROM transfer_jobs WHERE request_source IN ('wecom', 'telegram')
            """
        )
    return {"ok": True}


@router.delete("/wecom-records/{job_id}")
def delete_wecom_transfer_record(job_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM transfer_jobs WHERE id=? AND request_source IN ('wecom', 'telegram')",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="微信转存记录不存在")
        conn.execute(
            "INSERT OR IGNORE INTO transfer_record_hidden(job_id) VALUES(?)",
            (job_id,),
        )
    return {"ok": True, "id": job_id}


@router.post("/direct-link/options")
def direct_link_options(payload: DirectLinkOptionsRequest):
    try:
        request = prepare_direct_link_request(
            payload.link,
            title=payload.title,
            year=payload.year,
            category=payload.category,
            category_options=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "link": request.link,
        "provider": request.provider,
        "root_path": request.root_path,
        "year": request.year,
        "options": [
            {"provider": item.provider, "path": item.path, "label": item.label, "category": item.category}
            for item in request.options
        ],
    }


@router.post("/direct-link")
def create_direct_link_transfer(payload: DirectLinkTransferCreate, background_tasks: BackgroundTasks):
    try:
        request = prepare_direct_link_request(
            payload.link,
            title=payload.title,
            year=payload.year,
            category=payload.category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    save_path = request.root_path if payload.title.strip() else (payload.save_path.strip() or request.root_path)
    background_tasks.add_task(
        _run_direct_link_transfer,
        payload.link,
        save_path,
        request.title,
        request.year,
        request.category,
    )
    return {
        "ok": True,
        "provider": request.provider,
        "save_path": save_path,
        "year": request.year,
        "message": "转存已执行，已开始处理下载链接，可在右上角任务中心查看结果",
    }


def _run_direct_link_transfer(link: str, save_path: str, title: str = "", year: str = "", category: str = "movie") -> None:
    handle_direct_link_transfer(
        link,
        "local-web",
        save_path,
        "web",
        title=title,
        year=year,
        category=category,
    )


@router.post("/stop-active")
def stop_active_transfers():
    with db() as conn:
        rows = conn.execute(
            "SELECT id FROM transfer_jobs WHERE status IN ('running','ready','triggered')"
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"""
                UPDATE transfer_jobs
                SET status='stopped',stage='stopped',message='已由用户停止',finished_at=CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                ids,
            )
    return {"ok": True, "stopped": len(ids)}


@router.post("/{job_id}/stop")
def stop_transfer(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="transfer job not found")
        if row["status"] not in {"running", "ready", "triggered"}:
            return {"ok": True, "stopped": False, "message": "任务当前不可终止"}
        conn.execute(
            """
            UPDATE transfer_jobs
            SET status='stopped',stage='stopped',message='已由用户终止',finished_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (job_id,),
        )
    return {"ok": True, "stopped": True, "message": "任务已终止"}


@router.get("/batches/{batch_id}")
def get_transfer_batch(batch_id: int):
    _refresh_batch_status(batch_id)
    with db() as conn:
        batch = conn.execute("SELECT * FROM transfer_batches WHERE id=?", (batch_id,)).fetchone()
        children = conn.execute(
            """
            SELECT j.* FROM transfer_jobs j
            JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            WHERE bj.batch_id=? ORDER BY j.provider,j.season_number,j.id
            """,
            (batch_id,),
        ).fetchall()
    if not batch:
        raise HTTPException(status_code=404, detail="transfer batch not found")
    return {
        **dict(batch),
        "providers": json.loads(batch["providers_json"] or "[]"),
        "seasons": json.loads(batch["seasons_json"] or "[]"),
        "children": [normalize_provider_record(dict(row)) for row in children],
    }


@router.post("/batches")
def create_transfer_batch(payload: TransferBatchCreate, background_tasks: BackgroundTasks):
    if payload.target != "cloud":
        raise HTTPException(status_code=422, detail="批次接口只用于云盘 Provider")
    unique_items = list(
        {
            (str(item.provider).strip().lower(), item.season_number, tuple(sorted({number for number in item.episode_numbers if number > 0}))): item
            for item in payload.items
        }.values()
    )
    validated: list[TransferBatchItem] = []
    for item in unique_items:
        try:
            provider = resolve_provider_key(payload.target, item.provider)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        validated.append(TransferBatchItem(provider=provider, season_number=item.season_number, episode_numbers=sorted({number for number in item.episode_numbers if number > 0})))
    providers = list(dict.fromkeys(item.provider for item in validated))
    seasons = sorted({item.season_number for item in validated if item.season_number is not None})
    with db() as conn:
        batch_id = int(
            conn.execute(
                """
                INSERT INTO transfer_batches(
                    tmdb_id,media_type,display_title,target,status,message,providers_json,seasons_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    payload.tmdb_id,
                    payload.media_type,
                    payload.title,
                    payload.target,
                    "running",
                    "正在分别验证已启用的网盘资源",
                    json.dumps(providers, ensure_ascii=False),
                    json.dumps(seasons, ensure_ascii=False),
                ),
            ).lastrowid
        )
    jobs: list[tuple[TransferCreate, int, bool]] = []
    for item in validated:
        child = TransferCreate(
            tmdb_id=payload.tmdb_id,
            media_type=payload.media_type,
            category=payload.category,
            title=payload.title,
            year=payload.year,
            poster_url=payload.poster_url,
            overview=payload.overview,
            target=payload.target,
            season_number=item.season_number,
            provider=item.provider,
            episode_numbers=item.episode_numbers,
            preferred_share_urls=[item.preferred_share_url] if item.preferred_share_url else [],
            simple_matching=payload.simple_matching,
        )
        response = enqueue_transfer(child, batch_id=batch_id)
        job_id = int(response["id"])
        with db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)",
                (batch_id, job_id),
            )
        jobs.append((child, job_id, bool(response.get("duplicate"))))
    background_tasks.add_task(_run_transfer_batch, batch_id, jobs)
    return {
        "ok": True,
        "id": batch_id,
        "status": "running",
        "message": "正在分别验证已启用的网盘资源",
        "child_ids": [job_id for _payload, job_id, _duplicate in jobs],
    }


@router.get("/{job_id}")
def get_transfer(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="transfer job not found")
    return normalize_provider_record(dict(row))


@router.post("")
def create_transfer(payload: TransferCreate, background_tasks: BackgroundTasks):
    response = enqueue_transfer(payload)
    if not response.get("duplicate"):
        background_tasks.add_task(_run_transfer_job, payload, int(response["id"]))
    return response


def enqueue_transfer(payload: TransferCreate, *, batch_id: int | None = None) -> dict:
    try:
        provider = resolve_provider_key(payload.target, payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    selected_episodes = ",".join(str(number) for number in sorted({number for number in payload.episode_numbers if number > 0}))
    execution_key = f"{payload.tmdb_id}:{payload.media_type}:{payload.season_number or 0}:{payload.target}:{provider}"
    if payload.skip_tmdb:
        execution_key = (
            f"{execution_key}:direct:{_execution_key_text(payload.title)}:{_execution_key_text(payload.year)}"
        )
    if selected_episodes:
        execution_key = f"{execution_key}:episodes:{selected_episodes}"
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM transfer_jobs WHERE execution_key=? AND status IN ('running','ready','triggered') ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if existing:
            return {"ok": True, **normalize_provider_record(dict(existing)), "duplicate": True}
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs(
                batch_id,tmdb_id,media_type,display_title,season_number,target,provider,status,stage,message,execution_key,request_source,request_user
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                batch_id,
                payload.tmdb_id,
                payload.media_type,
                payload.title,
                payload.season_number,
                payload.target,
                provider,
                "running",
                "pansou_identifying" if payload.skip_tmdb else "tmdb_resolving",
                "正在使用 PanSou 确认标准电影名称" if payload.skip_tmdb else "正在匹配 TMDB 媒体信息",
                execution_key,
                payload.request_source,
                payload.request_user,
            ),
        )
        job_id = cur.lastrowid

    return {
        "ok": True,
        "id": int(job_id),
        "save_path": "",
        "message": "正在使用 PanSou 确认标准电影名称" if payload.skip_tmdb else "正在匹配 TMDB 媒体信息",
        "stage": "pansou_identifying" if payload.skip_tmdb else "tmdb_resolving",
        "status": "running",
        "provider": provider,
    }


def _execution_key_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "").casefold())[:120] or "unknown"


def _run_transfer_batch(batch_id: int, jobs: list[tuple[TransferCreate, int, bool]]) -> None:
    pending = [(payload, job_id) for payload, job_id, duplicate in jobs if not duplicate]
    if pending:
        with ThreadPoolExecutor(max_workers=min(4, len(pending)), thread_name_prefix="provider-transfer") as pool:
            futures = [pool.submit(_run_transfer_job, payload, job_id) for payload, job_id in pending]
            for future in futures:
                future.result()
    _reconcile_batch_wishlist(batch_id)
    _refresh_batch_status(batch_id)
    sync_results = sync_transfer_batch_storage(batch_id)
    if sync_results:
        successful = sum(1 for result in sync_results if result.get("ok"))
        running = sum(1 for result in sync_results if result.get("running"))
        message = (
            f"OpenList 已提交 {successful} 个季度的缺失集同步"
            if successful and not running
            else "OpenList 同步任务已在运行，未重复触发"
        )
        with db() as conn:
            conn.execute(
                "UPDATE transfer_batches SET message=message || ? WHERE id=?",
                (f"；{message}", batch_id),
            )


def _refresh_batch_status(batch_id: int) -> None:
    with db() as conn:
        batch = conn.execute("SELECT * FROM transfer_batches WHERE id=?", (batch_id,)).fetchone()
        rows = conn.execute(
            """
            SELECT j.provider,j.season_number,j.status,j.stage,j.message FROM transfer_jobs j
            JOIN transfer_batch_jobs bj ON bj.job_id=j.id WHERE bj.batch_id=?
            """,
            (batch_id,),
        ).fetchall()
    if not batch:
        return
    running = [row for row in rows if row["status"] in {"running", "ready"}]
    successes = [row for row in rows if row["status"] in {"done", "triggered"}]
    reviews = [row for row in rows if row["status"] == "needs_review"]
    failures = [row for row in rows if row["status"] == "failed" and not _batch_missing_is_covered(row, rows)]
    if running:
        status = "running"
        message = f"{len(running)} 个网盘子任务仍在执行"
    elif successes and (reviews or failures):
        status = "partial"
        message = f"{len(successes)} 个子任务成功，{len(reviews) + len(failures)} 个需要处理"
    elif successes:
        status = "done"
        message = f"{len(successes)} 个网盘子任务全部完成"
    elif reviews:
        status = "needs_review"
        message = f"{len(reviews)} 个网盘子任务需要确认"
    elif rows and all(row["status"] == "stopped" for row in rows):
        status = "stopped"
        message = "全部子任务已停止"
    else:
        status = "failed"
        message = f"{len(failures)} 个网盘子任务均未完成"
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_batches SET status=?,message=?,
                finished_at=CASE WHEN ?!='running' THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id=?
            """,
            (status, message, status, batch_id),
        )
    if status in {"partial", "failed"}:
        details = "；".join(
            f"{row['provider']} S{int(row['season_number'] or 0):02d}: {str(row['message'] or '')[:120]}"
            for row in [*failures, *reviews]
        )
        add_notification(
            f"transfer-batch:{batch_id}:{status}",
            "warning" if status == "partial" else "error",
            f"{batch['display_title'] or '媒体'}多网盘转存{'部分完成' if status == 'partial' else '失败'}",
            details or message,
            action_page="/review" if reviews else "/history",
        )


def _batch_missing_is_covered(row, rows) -> bool:
    if str(row["stage"] or "") != "no_resource":
        return False
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return False
    provider = str(row["provider"] or "")
    season_number = int(row["season_number"] or 0)
    for sibling in rows:
        sibling_provider = str(sibling["provider"] or "")
        if int(sibling["season_number"] or 0) != season_number or sibling["status"] not in {"done", "triggered"}:
            continue
        if automatic_sync_allowed(settings, provider, sibling_provider) or automatic_sync_allowed(settings, sibling_provider, provider):
            return True
    return False


def _reconcile_batch_wishlist(batch_id: int) -> None:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return
    with db() as conn:
        rows = conn.execute(
            """
            SELECT tmdb_id,media_type,season_number,provider,status,stage
            FROM transfer_jobs WHERE batch_id=? AND provider IN ('qas','p115')
            """,
            (batch_id,),
        ).fetchall()
        for row in rows:
            if str(row["stage"] or "") != "no_resource" or not _batch_missing_is_covered(row, rows):
                continue
            conn.execute(
                """
                DELETE FROM wishlist
                WHERE tmdb_id=? AND media_type=? AND provider=? AND COALESCE(season_number,0)=?
                """,
                (row["tmdb_id"], row["media_type"], row["provider"], int(row["season_number"] or 0)),
            )


def _run_transfer_job(payload: TransferCreate, job_id: int) -> None:
    def progress(stage: str, message: str) -> None:
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET stage=?,message=? WHERE id=? AND status='running'",
                (stage, message[:1000], job_id),
            )

    try:
        result = execute_transfer_v2(
            payload.tmdb_id,
            payload.media_type,
            payload.target,
            payload.season_number,
            on_progress=progress,
            provider=payload.provider,
            category=payload.category,
            selected_episode_numbers=payload.episode_numbers,
            preferred_share_urls=payload.preferred_share_urls,
            simple_matching=payload.simple_matching,
            title=payload.title,
            year=payload.year,
            skip_tmdb=payload.skip_tmdb,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "stage": "internal_error",
            "message": f"转存决策失败（{type(exc).__name__}）",
            "save_path": "",
        }

    stage = result.get("stage", "unknown")
    status = transfer_status_for_stage(stage)
    message = result.get("message", "")
    resolution = result.get("resolution") or {}
    pairs = resolution.get("rename_pairs") or []
    first_pair = pairs[0] if pairs else {}
    save_path = result.get("save_path", "")
    with db() as conn:
        current = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if current and current["status"] == "stopped":
        return

    wishlist_schedule = None
    if not result.get("ok") and stage == "no_resource":
        try:
            wishlist_target = resolve_wishlist_target(payload.tmdb_id, payload.media_type, payload.season_number)
            check_hour = get_settings().wishlist_default_check_hour
            next_check_at, tmdb_date = compute_wishlist_next_check(wishlist_target, check_hour)
            wishlist_schedule = (wishlist_target, check_hour, next_check_at, tmdb_date)
        except Exception:
            wishlist_schedule = None
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs
            SET status=?, stage=?, message=?, share_url=?, source_file=?, renamed_file=?, rename_pairs_json=?, save_path=?,
                finished_at=CASE WHEN ? IN ('done','failed','needs_review') THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id=?
            """,
            (
                status,
                stage,
                message,
                resolution.get("share_url", ""),
                first_pair.get("source_name", ""),
                first_pair.get("replacement", ""),
                json.dumps(pairs, ensure_ascii=False),
                save_path,
                status,
                job_id,
            ),
        )
        for candidate in resolution.get("reviewed_candidates") or []:
            conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,source_title,search_query,source,cloud_type,provider,published_at,
                                       file_count,files_json,score,rejected,reasons_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    candidate.get("share_url", ""),
                    candidate.get("title", ""),
                    candidate.get("query", ""),
                    candidate.get("source", ""),
                    candidate.get("cloud_type") or "quark",
                    candidate.get("provider") or "qas",
                    candidate.get("published_at", ""),
                    len(candidate.get("files") or []),
                    json.dumps(candidate.get("files") or [], ensure_ascii=False),
                    candidate.get("score", 0),
                    1 if candidate.get("rejected") else 0,
                    json.dumps(candidate.get("reasons") or [], ensure_ascii=False),
                ),
            )
        if not result.get("ok") and stage == "no_resource":
            target = result.get("target") or {}
            scheduled_target = wishlist_schedule[0] if wishlist_schedule else None
            check_hour = wishlist_schedule[1] if wishlist_schedule else get_settings().wishlist_default_check_hour
            next_check_at = wishlist_schedule[2] if wishlist_schedule else None
            tmdb_date = wishlist_schedule[3] if wishlist_schedule else ""
            conn.execute(
                """
                INSERT INTO wishlist(
                    tmdb_id,media_type,title,year,poster_url,overview,season_number,save_target,provider,
                    check_hour,tmdb_date,next_check_at,status
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'pending')
                    ON CONFLICT(tmdb_id, media_type, provider) DO UPDATE SET
                    season_number=excluded.season_number,
                    save_target=excluded.save_target,
                    provider=excluded.provider,
                    check_hour=excluded.check_hour,
                    tmdb_date=excluded.tmdb_date,
                    next_check_at=excluded.next_check_at,
                    status='pending',last_error='',retry_count=0
                """,
                (
                    payload.tmdb_id,
                    payload.media_type,
                    target.get("title") or payload.title,
                    target.get("series_year") or payload.year,
                    payload.poster_url,
                    payload.overview,
                    scheduled_target.season_number if scheduled_target else payload.season_number,
                    payload.target,
                    resolve_provider_key(payload.target, payload.provider),
                    check_hour,
                    tmdb_date,
                    next_check_at,
                ),
            )
    if status == "triggered":
        from app.services.qas_reconciler import request_qas_reconciliation

        request_qas_reconciliation()
    if status == "needs_review":
        target = result.get("target") or {}
        notification = notify_review_required(target.get("title") or payload.title or "未命名媒体", message, job_id)
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs SET review_state=?,
                    notification_sent_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE notification_sent_at END
                WHERE id=?
                """,
                ("notified" if notification.sent else "notification_failed", 1 if notification.sent else 0, job_id),
            )
    if status == "done":
        sync_message = _sync_openlist_for_transfer(payload, save_path, pairs)
        if sync_message:
            with db() as conn:
                conn.execute(
                    "UPDATE transfer_jobs SET message=? WHERE id=?",
                    (f"{message}；{sync_message}"[:1000], job_id),
                )
    sync_transfer_notifications()


def _sync_openlist_for_transfer(payload: TransferCreate, save_path: str, pairs: list[dict]) -> str:
    if payload.target != "cloud":
        return ""
    provider = resolve_provider_key(payload.target, payload.provider)
    filenames = [_pair_value(pair, "replacement") for pair in pairs]
    try:
        results = sync_transfer_outputs(
            provider,
            save_path,
            filenames,
            tmdb_id=payload.tmdb_id,
            media_type=payload.media_type,
            season_number=payload.season_number,
            display_title=payload.title,
        )
    except Exception as exc:
        return f"OpenList 同步未完成：{type(exc).__name__}"
    if not results:
        return ""
    successful = sum(1 for result in results if result.get("ok"))
    job_ids = [str(result.get("job_id")) for result in results if result.get("job_id")]
    if successful:
        return f"OpenList 已提交后台复制任务 #{'、'.join(job_ids)}" if job_ids else f"OpenList 已同步 {successful} 个文件"
    message = str(results[0].get("message") or "未知错误")
    return f"OpenList 后台任务 #{'、'.join(job_ids) or '?'} 未完成：{message[:80]}"


def _pair_value(pair: dict, key: str) -> str:
    if isinstance(pair, dict):
        return str(pair.get(key) or "").strip()
    return str(getattr(pair, key, "") or "").strip()
