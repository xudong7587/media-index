from fastapi import FastAPI, Request, WebSocket

from app.api.playback import router as playback_router
from app.services.emby_reverse_proxy import proxy_emby_http, proxy_emby_websocket


def create_playback_app() -> FastAPI:
    """Public Emby reverse proxy with MediaIndex-owned STRM playback routes."""
    app = FastAPI(title="Media Index Playback", docs_url=None, redoc_url=None)
    app.include_router(playback_router)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"ok": True, "service": "media-index-playback"}

    @app.websocket("/{path:path}", name="proxy_emby_websocket")
    async def emby_websocket(websocket: WebSocket, path: str):
        await proxy_emby_websocket(websocket, path)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        name="proxy_emby_http",
        include_in_schema=False,
    )
    async def emby_http(request: Request, path: str):
        return await proxy_emby_http(request, path)

    return app


app = create_playback_app()
