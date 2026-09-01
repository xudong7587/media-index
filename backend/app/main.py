from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, cloud, config, diagnostics, emby, mdc_webhook, media, notifications, openlist, playback, review, tracking, transfers, webhooks, wecom_callback, wishlist
from app.core.config import get_settings
from app.db.database import init_db
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.qas_reconciler import recover_interrupted_jobs
from app.services.transfer_recovery import recover_untracked_provider_submissions
from app.services.direct_link_transfer import (
    handle_direct_link_transfer,
    infer_direct_link_category,
    recover_p115_cloud_download_monitors,
)
from app.services.cross_cloud_transfer import recover_interrupted_cross_cloud_transfers
from app.services.channel_monitor import (
    complete_channel_resource_transfer,
    configure_resource_transfer_starter,
    configure_transfer_starter,
)
from app.services.cloud_download_targets import list_cloud_download_targets
from app.services.telegram_callback import start_telegram_poller, stop_telegram_poller
from app.services.notification_channels import sync_interaction_shortcuts
from app.services.diagnostics import record_diagnostic_event
from app.services.organized_p115_completion import recover_organized_quark_completions
from app.services.generic_webhooks import start_webhook_worker, stop_webhook_worker


def restore_interaction_shortcuts() -> bool:
    """Restore configured bot commands and WeCom menus without blocking startup."""
    settings = get_settings()
    telegram_ready = bool(settings.telegram_enabled and settings.telegram_bot_token.strip())
    wecom_ready = bool(
        settings.wecom_app_enabled
        and settings.wecom_callback_enabled
        and settings.wecom_corp_id.strip()
        and settings.wecom_app_secret.strip()
        and settings.wecom_app_agent_id > 0
    )
    if not telegram_ready and not wecom_ready:
        return False
    Thread(
        target=sync_interaction_shortcuts,
        name="media-index-interaction-menu-sync",
        daemon=True,
    ).start()
    return True


def create_app() -> FastAPI:
    def start_channel_transfer(wishlist: dict, share_url: str, channel_id: str, provider: str) -> int:
        """HTTP composition root for channel events and the shared transfer workflow."""
        payload = transfers.TransferCreate(
            tmdb_id=int(wishlist["tmdb_id"]), media_type=str(wishlist["media_type"]), category=str(wishlist.get("category") or ""),
            title=str(wishlist.get("title") or ""), year=str(wishlist.get("year") or ""), poster_url=str(wishlist.get("poster_url") or ""),
            overview=str(wishlist.get("overview") or ""), target=str(wishlist.get("save_target") or "cloud"), season_number=wishlist.get("season_number"),
            provider=provider, preferred_share_urls=[share_url], preferred_share_only=True, simple_matching=str(wishlist.get("media_type")) == "tv",
            request_source="telegram", request_user=channel_id,
        )
        response = transfers.enqueue_transfer(payload)
        if not response.get("duplicate"):
            transfers._run_transfer_job(payload, int(response["id"]))
        return int(response["id"])

    configure_transfer_starter(start_channel_transfer)

    def start_channel_resource_transfer(
        resource_id: int,
        share_url: str,
        channel_id: str,
        provider: str,
        category: str,
        requested_child: str,
    ) -> None:
        """Select one authorized staging child, then transfer outside the callback thread."""
        def run() -> None:
            try:
                targets = list_cloud_download_targets(provider)
                if requested_child:
                    matched = [item for item in targets if item.child_name == requested_child]
                    missing_message = f"{provider} 云下载根下不存在指定的直属子目录“{requested_child}”"
                else:
                    matched = [
                        item for item in targets
                        if infer_direct_link_category(provider, item.child_name, fallback="") == category
                    ]
                    missing_message = f"{provider} 云下载根下没有唯一对应“{category}”分类的直属子目录"
                if len(matched) != 1:
                    complete_channel_resource_transfer(
                        resource_id, ok=False, job_id=None,
                        message=missing_message if not matched else f"{provider} 的“{category}”分类对应多个子目录，请改为指定子目录",
                    )
                    return
                result = handle_direct_link_transfer(
                    share_url,
                    channel_id,
                    matched[0].path,
                    "telegram_channel",
                    category=category,
                    preserve_save_path=True,
                    match_rename=True,
                    destination_mode="cloud_download",
                )
                complete_channel_resource_transfer(
                    resource_id,
                    ok=result.ok,
                    job_id=result.job_id,
                    message=result.message,
                )
            except Exception as exc:
                complete_channel_resource_transfer(
                    resource_id, ok=False, job_id=None,
                    message=f"TG 频道资源提交失败（{type(exc).__name__}）",
                )

        Thread(
            target=run,
            name=f"media-index-tg-resource-{int(resource_id)}",
            daemon=True,
        ).start()

    configure_resource_transfer_starter(start_channel_resource_transfer)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        recover_interrupted_jobs()
        recover_untracked_provider_submissions()
        recover_p115_cloud_download_monitors()
        recover_organized_quark_completions()
        recover_interrupted_cross_cloud_transfers()
        start_webhook_worker()
        start_scheduler()
        restore_interaction_shortcuts()
        start_telegram_poller()
        try:
            yield
        finally:
            stop_scheduler()
            stop_telegram_poller()
            stop_webhook_worker()

    app = FastAPI(title="Media Index", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            if request.url.path.startswith("/api/"):
                record_diagnostic_event(
                    "http",
                    "request_exception",
                    level="error",
                    status="500",
                    message=type(exc).__name__,
                    context={"method": request.method, "path": request.url.path, "duration_ms": round((perf_counter() - started_at) * 1000)},
                )
            raise
        if request.url.path.startswith("/api/") and (request.method not in {"GET", "HEAD", "OPTIONS"} or response.status_code >= 400):
            record_diagnostic_event(
                "http",
                "request_completed" if response.status_code < 400 else "request_failed",
                level="info" if response.status_code < 400 else "warning",
                status=str(response.status_code),
                context={"method": request.method, "path": request.url.path, "duration_ms": round((perf_counter() - started_at) * 1000)},
            )
        return add_security_headers(response)

    app.include_router(auth.router)
    app.include_router(config.router)
    app.include_router(cloud.router)
    app.include_router(diagnostics.router)
    app.include_router(emby.router)
    app.include_router(mdc_webhook.router)
    app.include_router(webhooks.router)
    app.include_router(webhooks.ingress_router)
    app.include_router(media.router)
    app.include_router(notifications.router)
    app.include_router(openlist.router)
    app.include_router(playback.router)
    app.include_router(wecom_callback.router)
    app.include_router(review.router)
    app.include_router(tracking.router)
    app.include_router(transfers.router)
    app.include_router(wishlist.router)
    static_dir = Path(get_settings().static_dir)
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        index = static_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        return {"ok": True, "service": "Media Index API"}

    return app


def add_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https://image.tmdb.org; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    )
    return response


app = create_app()
