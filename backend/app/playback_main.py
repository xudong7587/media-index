from fastapi import FastAPI

from app.api.playback import router as playback_router


def create_playback_app() -> FastAPI:
    """A deliberately small public surface for media-player STRM requests."""
    app = FastAPI(title="Media Index Playback", docs_url=None, redoc_url=None)
    app.include_router(playback_router)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"ok": True, "service": "media-index-playback"}

    return app


app = create_playback_app()
