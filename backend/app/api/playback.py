from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from app.services.playback import PlaybackError, PlaybackHeadersRequired, open_playback_stream, resolve_playback_redirect
from app.services.diagnostics import record_diagnostic_event


router = APIRouter(prefix="/api/play", tags=["playback"])


@router.api_route("/{token}", methods=["GET", "HEAD"], include_in_schema=False)
def play_asset(token: str, request: Request):
    user_agent = request.headers.get("user-agent", "")
    try:
        target = resolve_playback_redirect(token, user_agent)
        _record_playback_request(request, 302, "redirect")
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
        _record_playback_request(request, 409, "rejected", str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        if request.method == "HEAD":
            stream = open_playback_stream(token, request.headers.get("range", ""), user_agent, head_only=True)
        else:
            stream = open_playback_stream(token, request.headers.get("range", ""), user_agent)
    except PlaybackError as exc:
        _record_playback_request(request, 409, "proxy", str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _record_playback_request(request, stream.status_code, "proxy")
    headers = {
        **stream.headers,
        "X-MediaIndex-Playback-Mode": "proxy",
        "X-MediaIndex-Playback-Reason": "provider-headers-required",
    }
    if request.method == "HEAD":
        return Response(status_code=stream.status_code, headers=headers)
    return StreamingResponse(stream.chunks, status_code=stream.status_code, headers=headers)


def _record_playback_request(request: Request, status: int, mode: str, message: str = "") -> None:
    # Never log the path: it contains the signed playback credential.
    record_diagnostic_event(
        "playback", "request_ready" if status < 400 else "request_failed",
        level="info" if status < 400 else "warning", status=str(status), message=message,
        context={"method": request.method, "mode": mode, "has_range": bool(request.headers.get("range"))},
    )
