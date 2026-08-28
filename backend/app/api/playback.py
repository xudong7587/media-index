from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from app.services.playback import PlaybackError, PlaybackHeadersRequired, open_playback_stream, resolve_playback_redirect


router = APIRouter(prefix="/api/play", tags=["playback"])


@router.get("/{token}", include_in_schema=False)
def play_asset(token: str, request: Request):
    user_agent = request.headers.get("user-agent", "")
    try:
        target = resolve_playback_redirect(token, user_agent)
        return RedirectResponse(
            target,
            status_code=302,
            headers={
                "Cache-Control": "no-store",
                "X-MediaIndex-Playback-Mode": "redirect",
            },
        )
    except PlaybackHeadersRequired:
        pass
    except PlaybackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        stream = open_playback_stream(token, request.headers.get("range", ""), user_agent)
    except PlaybackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    headers = {
        **stream.headers,
        "X-MediaIndex-Playback-Mode": "proxy",
        "X-MediaIndex-Playback-Reason": "provider-headers-required",
    }
    return StreamingResponse(stream.chunks, status_code=stream.status_code, headers=headers)
