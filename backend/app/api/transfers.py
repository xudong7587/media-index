import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import require_user
from app.db.database import db
from app.services.transfer_service_v2 import execute_transfer_v2
from app.services.transfer_batches import (
    batch_missing_is_covered as _batch_missing_is_covered,
    refresh_transfer_batch_status as _refresh_batch_status,
)
from app.services.review_notification import notify_review_required
from app.services.wishlist_schedule import compute_wishlist_next_check, resolve_wishlist_target
from app.core.config import get_settings
from app.providers.registry import resolve_provider_key
from app.providers.status import normalize_provider_record, transfer_status_for_stage
from app.services.notifications import sync_transfer_notifications
from app.services.openlist_sync import automatic_sync_allowed, sync_transfer_outputs
from app.services.p115_completion import complete_quark_to_p115
from app.services.direct_link_transfer import (
    handle_direct_link_transfer,
    prepare_direct_library_request,
    prepare_direct_link_request,
    preview_direct_link_rename,
)
from app.services.media_workflow import (
    complete_transfer_workflow_step,
    initialize_media_workflow,
    list_media_workflow,
    update_media_workflow_progress,
    update_media_workflow_step,
)
from app.services.post_transfer_pipeline import run_post_transfer_pipeline, try_targeted_cloud_download_organization
from app.services.interaction_transfer_context import (
    interaction_cloud_download_execution_marker,
    resolve_interaction_cloud_download_child,
)
from app.services.media_planning import (
    MEDIA_PLAN_VERSION,
    build_episode_coverage,
    build_media_plan,
    positive_episode_numbers,
)

router = APIRouter(prefix="/api/transfers", tags=["transfers"], dependencies=[Depends(require_user)])
DIRECT_LINK_CONTRACT_VERSION = 2


class MediaPlanIdentityInput(BaseModel):
    tmdb_id: int = 0
    media_type: str = "movie"
    category: str = ""
    title: str = ""
    year: str = ""
    season_number: int | None = None


class MediaPlanInput(BaseModel):
    version: Literal["media-plan/v1"] = MEDIA_PLAN_VERSION
    entrypoint: str = "unknown"
    provider: str = ""
    identity: MediaPlanIdentityInput = Field(default_factory=MediaPlanIdentityInput)
    episode_numbers: list[int] = Field(default_factory=list, max_length=1000)
    preferred_share_urls: list[str] = Field(default_factory=list, max_length=100)
    coverage: dict = Field(default_factory=dict)
    generated_at: str = ""
    expires_at: str = ""


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
    preferred_share_only: bool = False
    simple_matching: bool = False
    skip_tmdb: bool = False
    request_source: str = ""
    request_user: str = ""
    openlist_fallback_to_p115: bool = False
    tracking_task_id: int | None = Field(default=None, ge=1)
    media_plan: MediaPlanInput | None = None


class TransferBatchItem(BaseModel):
    provider: str
    season_number: int | None = None
    episode_numbers: list[int] = Field(default_factory=list, max_length=1000)
    preferred_share_url: str = ""
    preferred_share_urls: list[str] = Field(default_factory=list, max_length=100)
    preferred_share_only: bool = False
    openlist_fallback_to_p115: bool = False
    tracking_task_id: int | None = Field(default=None, ge=1)
    media_plan: MediaPlanInput | None = None


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
    match_rename: bool = True
    destination_mode: Literal["cloud_download", "library"] = "cloud_download"
    apply_rename_plan: bool = False


class DirectLinkRenamePreviewRequest(BaseModel):
    link: str = Field(min_length=1, max_length=20000)
    title: str = Field(min_length=1, max_length=200)
    year: str = Field(default="", max_length=10)
    category: str = Field(default="movie", max_length=30)


class CloudDownloadOrganizerRunRequest(BaseModel):
    provider: Literal["p115", "quark"] | None = None


def _coverage_from_plan(plan: MediaPlanInput):
    coverage = plan.coverage or {}
    return build_episode_coverage(
        total=coverage.get("total_episode_numbers") or (),
        aired=coverage.get("aired_episode_numbers") or (),
        available=coverage.get("available_episode_numbers") or plan.episode_numbers,
        transferred=coverage.get("transferred_episode_numbers") or (),
    )


def _normalized_media_plan(plan: MediaPlanInput) -> dict:
    if plan.version != MEDIA_PLAN_VERSION:
        raise ValueError(f"不支持的媒体计划版本：{plan.version}")
    return build_media_plan(
        entrypoint=plan.entrypoint,
        provider=plan.provider,
        identity=plan.identity.model_dump(),
        episode_numbers=plan.episode_numbers,
        preferred_share_urls=plan.preferred_share_urls,
        coverage=_coverage_from_plan(plan),
    )


def _transfer_with_media_plan(payload: TransferCreate) -> TransferCreate:
    plan = payload.media_plan
    if plan is None:
        return payload
    normalized = _normalized_media_plan(plan)
    identity = normalized["identity"]
    return payload.model_copy(
        update={
            "tmdb_id": int(identity["tmdb_id"] or payload.tmdb_id),
            "media_type": str(identity["media_type"] or payload.media_type),
            "category": str(identity["category"] or payload.category),
            "title": str(identity["title"] or payload.title),
            "year": str(identity["year"] or payload.year),
            "season_number": identity["season_number"] if identity["season_number"] is not None else payload.season_number,
            "provider": str(normalized["provider"] or payload.provider or ""),
            "episode_numbers": list(positive_episode_numbers(normalized["episode_numbers"] or payload.episode_numbers)),
            "preferred_share_urls": list(normalized["preferred_share_urls"] or payload.preferred_share_urls),
            "request_source": str(normalized["entrypoint"] or payload.request_source),
        }
    )


def _batch_item_key(item: TransferBatchItem) -> tuple[str, int | None, tuple[int, ...]]:
    if item.media_plan:
        normalized = _normalized_media_plan(item.media_plan)
        identity = normalized["identity"]
        return (
            str(normalized["provider"] or item.provider).strip().lower(),
            identity["season_number"] if identity["season_number"] is not None else item.season_number,
            positive_episode_numbers(normalized["episode_numbers"] or item.episode_numbers),
        )
    return (
        str(item.provider).strip().lower(),
        item.season_number,
        positive_episode_numbers(item.episode_numbers),
    )


@router.post("/plans/normalize")
def normalize_media_plan(payload: MediaPlanInput):
    """Canonical protocol adapter for discovery, extensions and interactions."""
    try:
        return _normalized_media_plan(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_transfers():
    with db() as conn:
        rows = conn.execute("SELECT * FROM transfer_jobs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [normalize_provider_record(dict(row)) for row in rows]


@router.get("/logs")
def list_transfer_logs(limit: int = Query(default=10000, ge=1, le=50000)):
    with db() as conn:
        rows = conn.execute(
            """SELECT * FROM transfer_jobs WHERE NOT EXISTS (
                 SELECT 1 FROM transfer_record_hidden hidden WHERE hidden.job_id=transfer_jobs.id
               ) ORDER BY created_at DESC,id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [normalize_provider_record(dict(row)) for row in rows]


@router.delete("/logs")
def clear_finished_transfer_logs():
    """Hide every non-active record; actionable review remains on its owning page."""
    with db() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO transfer_record_hidden(job_id)
               SELECT id FROM transfer_jobs
               WHERE status NOT IN ('queued','running','ready','triggered','retry_wait')"""
        )
    return {"ok": True, "cleared": max(0, int(cursor.rowcount or 0))}


@router.delete("/logs/{job_id}")
def clear_transfer_log(job_id: int):
    """Hide one terminal log entry without stopping or deleting its workflow data."""
    with db() as conn:
        row = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="transfer job not found")
        if row["status"] in {"queued", "running", "ready", "triggered", "retry_wait"}:
            raise HTTPException(status_code=409, detail="运行中的任务请先使用停止按钮")
        conn.execute("INSERT OR IGNORE INTO transfer_record_hidden(job_id) VALUES(?)", (job_id,))
    return {"ok": True, "id": job_id}


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
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    settings = get_settings()
    organizer_enabled = getattr(settings, "provider_cloud_download_organizer_enabled", None)
    return {
        "direct_link_contract_version": DIRECT_LINK_CONTRACT_VERSION,
        "link": request.link,
        "provider": request.provider,
        "root_path": request.root_path,
        "year": request.year,
        "cloud_download_enabled": bool(organizer_enabled(request.provider)) if callable(organizer_enabled) else False,
        "options": [
            {"provider": item.provider, "path": item.path, "label": item.label, "category": item.category}
            for item in request.options
        ],
    }


@router.post("/direct-link/rename-preview")
def direct_link_rename_preview(payload: DirectLinkRenamePreviewRequest):
    try:
        preview = preview_direct_link_rename(
            payload.link,
            title=payload.title,
            year=payload.year,
            category=payload.category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "direct_link_contract_version": DIRECT_LINK_CONTRACT_VERSION,
        "link": preview.link,
        "provider": preview.provider,
        "save_path": preview.save_path,
        "title": preview.title,
        "year": preview.year,
        "category": preview.category,
        "files": [
            {
                "source_name": pair.source_name,
                "target_name": pair.replacement,
                "confidence": pair.confidence,
            }
            for pair in preview.pairs
        ],
    }


@router.post("/direct-link")
def create_direct_link_transfer(payload: DirectLinkTransferCreate, background_tasks: BackgroundTasks):
    try:
        request = (
            prepare_direct_library_request(
                payload.link,
                title=payload.title,
                year=payload.year,
                category=payload.category,
            )
            if payload.destination_mode == "library"
            else prepare_direct_link_request(
                payload.link,
                title=payload.title,
                year=payload.year,
                category=payload.category,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.destination_mode == "library":
        save_path = request.root_path
        category = request.category
        preserve_save_path = False
    else:
        selected_path = payload.save_path.strip()
        selected = next(
            (item for item in request.options if item.provider == request.provider and item.path == selected_path),
            None,
        )
        if selected is None:
            detail = (
                f"云下载路径 {request.root_path} 下暂无可用的直属子文件夹"
                if not request.options
                else "请选择当前云下载路径下的直属子文件夹"
            )
            raise HTTPException(status_code=422, detail=detail)
        save_path = selected.path
        category = selected.category or request.category
        preserve_save_path = True
    background_tasks.add_task(
        _run_direct_link_transfer,
        payload.link,
        save_path,
        request.title,
        request.year,
        category,
        preserve_save_path,
        payload.match_rename,
        payload.apply_rename_plan or payload.destination_mode == "library",
        payload.destination_mode,
    )
    return {
        "ok": True,
        "direct_link_contract_version": DIRECT_LINK_CONTRACT_VERSION,
        "provider": request.provider,
        "save_path": save_path,
        "year": request.year,
        "destination_mode": payload.destination_mode,
        "message": (
            "已开始按 MediaIndex 规则转存到正式媒体库，可在右上角任务中心查看结果"
            if payload.destination_mode == "library"
            else "已开始转存到云下载子文件夹，可在右上角任务中心查看结果；标准化命名由后续云下载整理完成"
        ),
    }


def _run_direct_link_transfer(
    link: str,
    save_path: str,
    title: str = "",
    year: str = "",
    category: str = "movie",
    preserve_save_path: bool = True,
    match_rename: bool = True,
    apply_rename_plan: bool = False,
    destination_mode: str = "cloud_download",
) -> None:
    handle_direct_link_transfer(
        link,
        "local-web",
        save_path,
        "web",
        title=title,
        year=year,
        category=category,
        preserve_save_path=preserve_save_path,
        match_rename=match_rename,
        apply_rename_plan=apply_rename_plan,
        destination_mode=destination_mode,
    )


@router.post("/cloud-download-organizer/run")
def run_cloud_download_organizer_now(
    payload: CloudDownloadOrganizerRunRequest,
    background_tasks: BackgroundTasks,
):
    del payload, background_tasks
    raise HTTPException(
        status_code=409,
        detail="云下载整理由已配置的前序动作事件或定时任务自动执行，不提供手动全量扫描入口",
    )


@router.post("/stop-active")
def stop_active_transfers():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id FROM transfer_jobs
            WHERE status IN ('queued','running','ready','triggered','retry_wait')
              AND COALESCE(provider, '') NOT IN ('emby', 'scheduler')
            """
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
        row = conn.execute("SELECT status, provider FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="transfer job not found")
        if row["provider"] in {"emby", "scheduler"}:
            return {"ok": True, "stopped": False, "message": "此类任务不支持中途终止"}
        if row["status"] not in {"queued", "running", "ready", "triggered", "retry_wait"}:
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
            _batch_item_key(item): item
            for item in payload.items
        }.values()
    )
    validated: list[TransferBatchItem] = []
    for item in unique_items:
        normalized_plan = _normalized_media_plan(item.media_plan) if item.media_plan else None
        plan_provider = str(normalized_plan.get("provider") or "") if normalized_plan else ""
        plan_identity = normalized_plan.get("identity") or {} if normalized_plan else {}
        item_provider = plan_provider or item.provider
        item_season_number = plan_identity.get("season_number") if plan_identity.get("season_number") is not None else item.season_number
        item_episode_numbers = normalized_plan.get("episode_numbers") if normalized_plan else item.episode_numbers
        try:
            provider = resolve_provider_key(payload.target, item_provider)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        tracking_task_id = _validate_tracking_task_link(
            item.tracking_task_id,
            tmdb_id=payload.tmdb_id,
            media_type=payload.media_type,
            season_number=item_season_number,
            target=payload.target,
            provider=provider,
        )
        preferred_share_urls = list(
            dict.fromkeys(
                value.strip()
                for value in [
                    item.preferred_share_url,
                    *(normalized_plan.get("preferred_share_urls") if normalized_plan else item.preferred_share_urls),
                ]
                if value.strip()
            )
        )[:100]
        validated.append(
            TransferBatchItem(
                provider=provider,
                season_number=item_season_number,
                episode_numbers=list(positive_episode_numbers(item_episode_numbers)),
                preferred_share_url=preferred_share_urls[0] if preferred_share_urls else "",
                preferred_share_urls=preferred_share_urls,
                preferred_share_only=item.preferred_share_only,
                openlist_fallback_to_p115=item.openlist_fallback_to_p115,
                tracking_task_id=tracking_task_id,
                media_plan=item.media_plan,
            )
        )
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
            preferred_share_urls=item.preferred_share_urls,
            preferred_share_only=item.preferred_share_only,
            openlist_fallback_to_p115=item.openlist_fallback_to_p115,
            tracking_task_id=item.tracking_task_id,
            simple_matching=payload.simple_matching,
            media_plan=item.media_plan,
        )
        child = _transfer_with_media_plan(child)
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


@router.get("/workflow/{media_type}/{tmdb_id}")
def get_media_workflow(media_type: str, tmdb_id: int):
    if media_type not in {"movie", "tv", "variety"} or tmdb_id <= 0:
        raise HTTPException(status_code=422, detail="媒体标识无效")
    return list_media_workflow(tmdb_id, media_type)


@router.get("/{job_id}")
def get_transfer(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="transfer job not found")
    return normalize_provider_record(dict(row))


@router.post("")
def create_transfer(payload: TransferCreate, background_tasks: BackgroundTasks):
    try:
        payload = _transfer_with_media_plan(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = enqueue_transfer(payload)
    if not response.get("duplicate"):
        background_tasks.add_task(_run_transfer_job, payload, int(response["id"]))
    return response


def enqueue_transfer(
    payload: TransferCreate,
    *,
    batch_id: int | None = None,
    interaction_cloud_download_child: str = "",
) -> dict:
    try:
        provider = resolve_provider_key(payload.target, payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tracking_task_id = _validate_tracking_task_link(
        payload.tracking_task_id,
        tmdb_id=payload.tmdb_id,
        media_type=payload.media_type,
        season_number=payload.season_number,
        target=payload.target,
        provider=provider,
    )
    selected_episodes = ",".join(str(number) for number in sorted({number for number in payload.episode_numbers if number > 0}))
    execution_key = f"{payload.tmdb_id}:{payload.media_type}:{payload.season_number or 0}:{payload.target}:{provider}"
    if payload.skip_tmdb:
        execution_key = (
            f"{execution_key}:direct:{_execution_key_text(payload.title)}:{_execution_key_text(payload.year)}"
        )
    if selected_episodes:
        execution_key = f"{execution_key}:episodes:{selected_episodes}"
    cloud_download_child = str(interaction_cloud_download_child or "").strip()
    if cloud_download_child:
        candidate_key = f"{execution_key}:{interaction_cloud_download_execution_marker(cloud_download_child)}"
        if resolve_interaction_cloud_download_child(
            execution_key=candidate_key,
            request_source=payload.request_source,
            provider=provider,
        ) != cloud_download_child:
            raise HTTPException(status_code=422, detail="互动云下载子目录已失效，请重新选择")
        execution_key = candidate_key
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM transfer_jobs WHERE execution_key=? AND status IN ('running','ready','triggered') ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if existing:
            existing_task_id = int(existing["task_id"] or 0)
            if tracking_task_id and existing_task_id not in {0, tracking_task_id}:
                raise HTTPException(status_code=409, detail="相同转存任务已关联其他智能追更任务")
            if tracking_task_id and existing_task_id == 0:
                conn.execute(
                    "UPDATE transfer_jobs SET task_id=? WHERE id=? AND task_id IS NULL",
                    (tracking_task_id, int(existing["id"])),
                )
                existing = conn.execute(
                    "SELECT * FROM transfer_jobs WHERE id=?",
                    (int(existing["id"]),),
                ).fetchone()
            return {"ok": True, **normalize_provider_record(dict(existing)), "duplicate": True}
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs(
                batch_id,task_id,tmdb_id,media_type,display_title,season_number,target,provider,status,stage,message,execution_key,request_source,request_user,openlist_fallback_to_p115
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                batch_id,
                tracking_task_id,
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
                1 if payload.openlist_fallback_to_p115 else 0,
            ),
        )
        job_id = cur.lastrowid

    initialize_media_workflow(
        int(job_id),
        openlist_fallback_to_p115=_openlist_sync_requested(payload, provider),
    )

    return {
        "ok": True,
        "id": int(job_id),
        "save_path": "",
        "message": "正在使用 PanSou 确认标准电影名称" if payload.skip_tmdb else "正在匹配 TMDB 媒体信息",
        "stage": "pansou_identifying" if payload.skip_tmdb else "tmdb_resolving",
        "status": "running",
        "provider": provider,
    }


def _validate_tracking_task_link(
    tracking_task_id: int | None,
    *,
    tmdb_id: int,
    media_type: str,
    season_number: int | None,
    target: str,
    provider: str,
) -> int | None:
    """Bind an initial transfer only to its exact active tracking lane."""
    if tracking_task_id is None:
        return None
    with db() as conn:
        row = conn.execute(
            """
            SELECT id,tmdb_id,media_type,season_number,save_target,provider,status
            FROM tracking_tasks WHERE id=?
            """,
            (int(tracking_task_id),),
        ).fetchone()
    matches = bool(
        row
        and int(row["tmdb_id"] or 0) == int(tmdb_id)
        and str(row["media_type"] or "") == str(media_type or "")
        and int(row["season_number"] or 0) == int(season_number or 0)
        and str(row["save_target"] or "") == str(target or "")
        and str(row["provider"] or "") == str(provider or "")
        and str(row["status"] or "") == "active"
    )
    if not matches:
        raise HTTPException(status_code=422, detail="首次转存与智能追更任务不匹配，请重新发起")
    with db() as conn:
        active = conn.execute(
            """
            SELECT id FROM transfer_jobs
            WHERE task_id=? AND status IN ('running','ready','triggered')
            ORDER BY id DESC LIMIT 1
            """,
            (int(tracking_task_id),),
        ).fetchone()
    if active:
        raise HTTPException(status_code=409, detail="该智能追更链路已有任务正在执行，请勿重复发起")
    return int(tracking_task_id)


def _execution_key_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "").casefold())[:120] or "unknown"


def _run_transfer_batch(batch_id: int, jobs: list[tuple[TransferCreate, int, bool]]) -> None:
    pending = [(payload, job_id) for payload, job_id, duplicate in jobs if not duplicate]
    defer_library_notification = _predictable_multi_episode_batch(pending)
    if pending:
        with ThreadPoolExecutor(max_workers=min(4, len(pending)), thread_name_prefix="provider-transfer") as pool:
            futures = [
                pool.submit(
                    _run_transfer_job,
                    payload,
                    job_id,
                    defer_openlist_sync=True,
                    defer_notification_sync=True,
                    defer_library_notification=defer_library_notification,
                )
                for payload, job_id in pending
            ]
            for future in futures:
                future.result()
    _sync_openlist_for_batch(batch_id)
    _reconcile_batch_wishlist(batch_id)
    _refresh_batch_status(batch_id)
    # A multi-provider action is one user operation.  Child workers must not
    # race each other to publish separate terminal notifications.
    sync_transfer_notifications()


def _predictable_multi_episode_batch(jobs: list[tuple[TransferCreate, int]]) -> bool:
    """Delay only a contiguous multi-episode plan backed by a frozen source snapshot."""
    episodes: set[int] = set()
    has_frozen_share_snapshot = False
    serial_media = False
    for payload, _job_id in jobs:
        serial_media = serial_media or str(payload.media_type or "").strip().lower() in {"tv", "show", "series"}
        episodes.update(int(number) for number in payload.episode_numbers if int(number) > 0)
        plan = payload.media_plan
        if plan is not None:
            episodes.update(int(number) for number in plan.episode_numbers if int(number) > 0)
            has_frozen_share_snapshot = has_frozen_share_snapshot or bool(plan.preferred_share_urls)
        has_frozen_share_snapshot = has_frozen_share_snapshot or bool(payload.preferred_share_urls)
    ordered = sorted(episodes)
    contiguous = len(ordered) >= 2 and all(current == previous + 1 for previous, current in zip(ordered, ordered[1:]))
    return serial_media and contiguous and has_frozen_share_snapshot


def _reconcile_batch_wishlist(batch_id: int) -> None:
    settings = get_settings()
    if not settings.openlist_enabled or not settings.openlist_auto_sync:
        return
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.id,j.tmdb_id,j.media_type,j.season_number,j.provider,j.status,j.stage,j.openlist_fallback_to_p115,
                   COALESCE(w.status,'') AS openlist_status
            FROM transfer_jobs j
            JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            LEFT JOIN media_workflow_steps w ON w.job_id=j.id AND w.step_key='openlist_sync'
            WHERE bj.batch_id=? AND j.provider IN ('qas','quark','p115')
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


def _run_transfer_job(
    payload: TransferCreate,
    job_id: int,
    *,
    interaction_cloud_download_child: str = "",
    defer_openlist_sync: bool = False,
    defer_notification_sync: bool = False,
    defer_library_notification: bool = False,
) -> None:
    def progress(stage: str, message: str) -> None:
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET stage=?,message=? WHERE id=? AND status='running'",
                (stage, message[:1000], job_id),
            )
        update_media_workflow_progress(job_id, stage, message)

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
            preferred_share_only=payload.preferred_share_only,
            simple_matching=payload.simple_matching,
            title=payload.title,
            year=payload.year,
            skip_tmdb=payload.skip_tmdb,
            interaction_cloud_download_child=interaction_cloud_download_child,
            request_source=payload.request_source,
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
    stored_status = "running" if status == "done" else status
    message = result.get("message", "")
    resolution = result.get("resolution") or {}
    pairs = resolution.get("rename_pairs") or []
    first_pair = pairs[0] if pairs else {}
    save_path = result.get("save_path", "")
    target_files = tuple(
        dict(item)
        for item in ((result.get("execution") or {}).get("outputs") or ())
        if isinstance(item, dict)
    )
    resolved_provider = resolve_provider_key(payload.target, payload.provider)
    post_processing_required = bool(
        target_files
        and resolved_provider in {"p115", "quark"}
        and status in {"done", "failed"}
    )
    persisted_pairs = list(pairs)
    if post_processing_required:
        persisted_pairs.append(
            {
                "_post_processing": {
                    "outputs": list(target_files),
                    "terminal_status": status,
                    "terminal_stage": stage,
                    "terminal_message": message,
                }
            }
        )
        stored_status = "running"
    post_processing_state = "post_processing_pending" if post_processing_required else ""
    with db() as conn:
        current = conn.execute("SELECT status,task_id FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if current and current["status"] == "stopped":
        return
    linked_tracking_task_id = int(current["task_id"] or 0) if current else 0

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
                external_provider_status=?,
                finished_at=CASE WHEN ? IN ('done','failed','needs_review') THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id=?
            """,
            (
                stored_status,
                stage,
                message,
                resolution.get("share_url", ""),
                first_pair.get("source_name", ""),
                first_pair.get("replacement", ""),
                json.dumps(persisted_pairs, ensure_ascii=False),
                save_path,
                post_processing_state,
                stored_status,
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
    complete_transfer_workflow_step(job_id, status, stage, message)
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
    post_processing_ok: bool | None = None
    post_processing_waiting = False
    if status == "done" and stage == "already_saved":
        for step_key in ("openlist_sync", "strm_generate", "emby_refresh", "library_notification"):
            update_media_workflow_step(job_id, step_key, "skipped", "目标网盘已包含所选内容，无需重复处理")
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET notification_sent_at=COALESCE(notification_sent_at,CURRENT_TIMESTAMP) WHERE id=?",
                (int(job_id),),
            )
        post_processing_ok = True
    elif status == "done":
        provider = resolved_provider
        sync_requested = _openlist_sync_requested(payload, provider)
        organizer_handled, organizer_message = try_targeted_cloud_download_organization(
            provider=provider,
            target_path=save_path,
            target_files=target_files,
            media_title=payload.title,
            media_year=payload.year,
        )
        # A cloud-download location is only staging. Its organizer performs
        # standard naming/folder landing and owns the later 115 completion.
        if organizer_handled and sync_requested:
            if "失败" in organizer_message or "复核" in organizer_message:
                sync_message = "云下载整理未完成，未从暂存目录启动 115/OpenList 补齐"
                update_media_workflow_step(job_id, "openlist_sync", "skipped", sync_message)
            else:
                sync_message = "等待云下载整理完成标准命名、建目录和目标核验后，再启动 115 补齐"
                update_media_workflow_step(job_id, "openlist_sync", "pending", sync_message)
        elif interaction_cloud_download_child and sync_requested:
            sync_message = "云下载整理未接管，已禁止从原始暂存目录启动 115/OpenList 补齐"
            update_media_workflow_step(job_id, "openlist_sync", "skipped", sync_message)
        else:
            sync_message = (
                "等待同批正式媒体库转存全部结束后核对 115 缺失文件"
                if defer_openlist_sync and sync_requested
                else _sync_openlist_for_transfer(job_id, payload, save_path, pairs)
            )
            if sync_message and not defer_openlist_sync:
                update_media_workflow_step(
                    job_id,
                    "openlist_sync",
                    _openlist_workflow_status(sync_message),
                    sync_message,
                )
                with db() as conn:
                    conn.execute(
                        "UPDATE transfer_jobs SET message=? WHERE id=?",
                        (f"{message}；{sync_message}"[:1000], job_id),
                    )
        if organizer_handled:
            delegated_message = organizer_message or "已由云下载整理流程接管"
            update_media_workflow_step(job_id, "strm_generate", "skipped", delegated_message)
            update_media_workflow_step(job_id, "emby_refresh", "skipped", "由云下载整理流程负责后续入库")
            update_media_workflow_step(job_id, "library_notification", "skipped", "由云下载整理流程统一通知")
            with db() as conn:
                conn.execute(
                    "UPDATE transfer_jobs SET message=? WHERE id=?",
                    (f"{message}；{sync_message}；{organizer_message}".replace("；；", "；").strip("；")[:1000], job_id),
                )
                conn.execute(
                    "UPDATE transfer_jobs SET external_provider_status='organized_completion_delegated' WHERE id=?",
                    (int(job_id),),
                )
            post_processing_ok = True
        elif interaction_cloud_download_child:
            waiting_message = (
                "云下载已完成；自动整理当前未接管，请检查该网盘的整理开关、事件触发和目录范围。"
                "云下载原始文件未生成 STRM"
            )
            update_media_workflow_step(job_id, "strm_generate", "skipped", "云下载原始文件等待整理，不生成 STRM")
            update_media_workflow_step(job_id, "emby_refresh", "skipped", "等待云下载整理完成后再通知媒体库")
            update_media_workflow_step(job_id, "library_notification", "skipped", "等待云下载整理链路统一通知")
            with db() as conn:
                conn.execute(
                    "UPDATE transfer_jobs SET message=? WHERE id=?",
                    (f"{message}；{sync_message}；{waiting_message}".replace("；；", "；").strip("；")[:1000], job_id),
                )
                conn.execute(
                    "UPDATE transfer_jobs SET external_provider_status='post_processing_skipped' WHERE id=?",
                    (int(job_id),),
                )
            post_processing_ok = True
        else:
            if post_processing_required:
                from app.services.tracking_engine_v2 import run_pending_tracking_post_processing

                post_processing_ok = run_pending_tracking_post_processing(
                    int(job_id),
                    outputs=target_files,
                    title=payload.title,
                    poster_url=payload.poster_url,
                    media_year=payload.year,
                    defer_library_notification=defer_library_notification,
                )
            else:
                post_processing_ok = run_post_transfer_pipeline(
                    job_id,
                    provider=provider,
                    title=payload.title,
                    poster_url=payload.poster_url,
                    openlist_message=sync_message,
                    target_path=save_path,
                    target_files=target_files,
                    defer_library_notification=defer_library_notification,
                )
            if not post_processing_ok and not post_processing_required:
                post_message = "转存已完成，但 STRM 或 Emby 后处理失败，请查看自动入库进度"
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE transfer_jobs
                        SET status='failed',stage='post_processing_failed',message=?,finished_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (f"{message}；{post_message}"[:1000], int(job_id)),
                    )
    elif target_files:
        # A multi-link season can save some episodes before a later provider
        # operation fails. Generate STRM for the exact confirmed outputs once,
        # while keeping the overall job failed so the missing episodes retry.
        from app.services.tracking_engine_v2 import run_pending_tracking_post_processing

        post_processing_ok = run_pending_tracking_post_processing(
            int(job_id),
            outputs=target_files,
            title=payload.title,
            poster_url=payload.poster_url,
            media_year=payload.year,
            defer_library_notification=defer_library_notification,
        )
    if post_processing_required and post_processing_ok is False:
        from app.services.tracking_engine_v2 import post_processing_retryable

        post_processing_waiting = post_processing_retryable(int(job_id))
        if post_processing_waiting:
            retry_message = "STRM 或 Emby 后处理暂未完成，将在后台使用已确认文件重试"
            with db() as conn:
                conn.execute(
                    """
                    UPDATE transfer_jobs
                    SET status='running',stage='post_processing_retry_wait',message=?,finished_at=NULL
                    WHERE id=?
                    """,
                    (f"{message}；{retry_message}"[:1000], int(job_id)),
                )
        elif status == "done":
            post_message = "转存已完成，但 STRM 或 Emby 后处理失败，请查看自动入库进度"
            with db() as conn:
                conn.execute(
                    """
                    UPDATE transfer_jobs
                    SET status='failed',stage='post_processing_failed',message=?,finished_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (f"{message}；{post_message}"[:1000], int(job_id)),
                )
    if linked_tracking_task_id:
        try:
            if target_files:
                from app.services.saved_episode_scanner import record_confirmed_tracking_outputs

                record_confirmed_tracking_outputs(linked_tracking_task_id, target_files)
            elif stage == "already_saved":
                from app.services.saved_episode_scanner import refresh_saved_episodes

                refresh_saved_episodes(linked_tracking_task_id)
        except Exception:
            pass
    if (status == "done" or post_processing_required) and not post_processing_waiting:
        terminal_status = status if post_processing_ok is not False else "failed"
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs
                SET status=?,finished_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='running'
                """,
                (terminal_status, int(job_id)),
            )
    _refresh_associated_batches(job_id)
    if not defer_notification_sync:
        sync_transfer_notifications()


def _refresh_associated_batches(job_id: int) -> None:
    """Settle every parent, including a duplicate request reusing this job."""
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT batch_id FROM transfer_batch_jobs WHERE job_id=?",
            (int(job_id),),
        ).fetchall()
    for row in rows:
        _refresh_batch_status(int(row["batch_id"]))


def _sync_openlist_for_batch(batch_id: int) -> bool:
    settings = get_settings()
    with db() as conn:
        all_rows = conn.execute(
            """
            SELECT j.status FROM transfer_jobs j
            JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            WHERE bj.batch_id=?
            """,
            (batch_id,),
        ).fetchall()
        if any(str(row["status"] or "") in {"running", "ready"} for row in all_rows):
            return False
        rows = conn.execute(
            """
            SELECT j.* FROM transfer_jobs j
            JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            WHERE bj.batch_id=? AND j.provider IN ('qas','quark')
            ORDER BY j.season_number,j.id
            """,
            (batch_id,),
        ).fetchall()
    for raw in rows:
        row = dict(raw)
        provider = str(row.get("provider") or "").strip().lower()
        sync_requested = bool(row.get("openlist_fallback_to_p115")) or bool(
            provider == "quark"
            and settings.openlist_enabled
            and settings.openlist_auto_sync
            and automatic_sync_allowed(settings, provider, "p115")
        )
        if not sync_requested:
            continue
        job_id = int(row["id"])
        if str(row.get("external_provider_status") or "") == "organized_completion_delegated":
            update_media_workflow_step(
                job_id,
                "openlist_sync",
                "pending",
                "由云下载整理任务在标准落盘核验后独立执行 115 补齐",
            )
            continue
        if str(row.get("status") or "") != "done":
            update_media_workflow_step(job_id, "openlist_sync", "failed", "夸克原生转存未完成，未发起 115 补齐")
            continue
        try:
            pairs = json.loads(row.get("rename_pairs_json") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            pairs = []
        filenames = [_pair_value(pair, "replacement") for pair in pairs]
        try:
            if provider == "quark":
                completion = complete_quark_to_p115(
                    job_id=job_id,
                    save_path=str(row.get("save_path") or ""),
                    filenames=filenames,
                    tmdb_id=row.get("tmdb_id"),
                    media_type=str(row.get("media_type") or ""),
                    season_number=row.get("season_number"),
                    title=str(row.get("display_title") or ""),
                )
                sync_message = completion.message
                workflow_status = completion.workflow_status
            else:
                results = sync_transfer_outputs(
                    provider,
                    str(row.get("save_path") or ""),
                    filenames,
                    tmdb_id=row.get("tmdb_id"),
                    media_type=str(row.get("media_type") or ""),
                    season_number=row.get("season_number"),
                    display_title=str(row.get("display_title") or ""),
                    target_providers=("p115",),
                )
                sync_message = _openlist_results_message(results)
                workflow_status = _openlist_workflow_status(sync_message)
        except Exception as exc:
            sync_message = f"115 补齐未完成：{type(exc).__name__}"
            workflow_status = "failed"
        update_media_workflow_step(job_id, "openlist_sync", workflow_status, sync_message)
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET message=? WHERE id=?",
                (f"{row.get('message') or ''}；{sync_message}"[:1000], job_id),
            )
    return True


def _sync_openlist_for_transfer(job_id: int, payload: TransferCreate, save_path: str, pairs: list[dict]) -> str:
    provider = resolve_provider_key(payload.target, payload.provider)
    if not _openlist_sync_requested(payload, provider):
        return ""
    filenames = [_pair_value(pair, "replacement") for pair in pairs]
    if provider == "quark":
        completion = complete_quark_to_p115(
            job_id=job_id,
            save_path=save_path,
            filenames=filenames,
            tmdb_id=payload.tmdb_id,
            media_type=payload.media_type,
            season_number=payload.season_number,
            title=payload.title,
            year=payload.year,
            category=payload.category,
            poster_url=payload.poster_url,
        )
        return completion.message
    try:
        results = sync_transfer_outputs(
            provider,
            save_path,
            filenames,
            tmdb_id=payload.tmdb_id,
            media_type=payload.media_type,
            season_number=payload.season_number,
            display_title=payload.title,
            target_providers=("p115",),
        )
    except Exception as exc:
        return f"OpenList 同步未完成：{type(exc).__name__}"
    return _openlist_results_message(results)


def _openlist_sync_requested(payload: TransferCreate, provider: str) -> bool:
    if payload.target != "cloud":
        return False
    provider = str(provider or "").strip().lower()
    if provider not in {"qas", "quark"}:
        return False
    if payload.openlist_fallback_to_p115:
        return True
    settings = get_settings()
    return bool(
        provider == "quark"
        and settings.openlist_enabled
        and settings.openlist_auto_sync
        and automatic_sync_allowed(settings, provider, "p115")
    )


def _openlist_results_message(results: list[dict]) -> str:
    if not results:
        return "OpenList 同步未完成：未产生可核验的补齐结果"
    successful = sum(1 for result in results if result.get("ok"))
    job_ids = [str(result.get("job_id")) for result in results if result.get("job_id")]
    if successful:
        return f"OpenList 已提交后台复制任务 #{'、'.join(job_ids)}" if job_ids else f"OpenList 已同步 {successful} 个文件"
    message = str(results[0].get("message") or "未知错误")
    return f"OpenList 后台任务 #{'、'.join(job_ids) or '?'} 未完成：{message[:80]}"


def _openlist_workflow_status(message: str) -> str:
    if "未完成" in message or "失败" in message:
        return "failed"
    if "提交" in message or "后台复制任务" in message:
        return "running"
    return "done"


def _pair_value(pair: dict, key: str) -> str:
    if isinstance(pair, dict):
        return str(pair.get(key) or "").strip()
    return str(getattr(pair, key, "") or "").strip()
