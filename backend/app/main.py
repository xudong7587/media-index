from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, config, media, notifications, openlist, review, tracking, transfers, wecom_callback, wishlist
from app.core.config import get_settings
from app.db.database import init_db
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.qas_reconciler import recover_interrupted_jobs, request_qas_reconciliation
from app.services.telegram_callback import start_telegram_poller, stop_telegram_poller


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        recover_interrupted_jobs()
        request_qas_reconciliation()
        start_scheduler()
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
    app.include_router(media.router)
    app.include_router(notifications.router)
    app.include_router(openlist.router)
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
