from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, cloud, config, emby, mdc_webhook, media, notifications, openlist, playback, review, tracking, transfers, wecom_callback, wishlist
from app.core.config import get_settings
from app.db.database import init_db
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.qas_reconciler import recover_interrupted_jobs
from app.services.transfer_recovery import recover_untracked_provider_submissions
from app.services.cross_cloud_transfer import recover_interrupted_cross_cloud_transfers
from app.services.channel_monitor import configure_transfer_starter
from app.services.telegram_callback import start_telegram_poller, stop_telegram_poller
from app.services.notification_channels import sync_interaction_shortcuts


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

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        recover_interrupted_jobs()
        recover_untracked_provider_submissions()
        recover_interrupted_cross_cloud_transfers()
        start_scheduler()
        restore_interaction_shortcuts()
        start_telegram_poller()
        try:
            yield
        finally:
            stop_scheduler()
            stop_telegram_poller()

    app = FastAPI(title="Media Index", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        return add_security_headers(response)

    app.include_router(auth.router)
    app.include_router(config.router)
    app.include_router(cloud.router)
    app.include_router(emby.router)
    app.include_router(mdc_webhook.router)
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
