from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.services.playback import PlaybackError, open_playback_stream


router = APIRouter(prefix="/api/play", tags=["playback"])


@router.get("/{token}", include_in_schema=False)
def play_asset(token: str, request: Request):
    try:
        stream = open_playback_stream(token, request.headers.get("range", ""))
    except PlaybackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StreamingResponse(stream.chunks, status_code=stream.status_code, headers=stream.headers)
