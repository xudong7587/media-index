from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, config, media, review, tracking, transfers, wishlist
from app.core.config import get_settings
from app.db.database import init_db
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.qas_reconciler import recover_interrupted_jobs


def create_app() -> FastAPI:
    app = FastAPI(title="Media Index", docs_url=None, redoc_url=None)

    @app.on_event("startup")
    def startup() -> None:
        init_db()
        recover_interrupted_jobs()
        start_scheduler()

    @app.on_event("shutdown")
    def shutdown() -> None:
        stop_scheduler()

    app.include_router(auth.router)
    app.include_router(config.router)
    app.include_router(media.router)
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
        index = static_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        return {"ok": True, "service": "Media Index API"}

    return app


app = create_app()
