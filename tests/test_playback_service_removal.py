from app.playback_main import create_playback_app
from app import playback_main
from app.api import playback
from fastapi.testclient import TestClient
from starlette.responses import Response
from app.services.playback_logging import configure_access_log_redaction, PlaybackAccessLogFilter
import logging


def test_public_playback_keeps_original_and_cloud_routes_without_nas_transcoding(monkeypatch):
    async def upstream(request, path):
        return Response(status_code=404)
    monkeypatch.setattr(playback_main, 'proxy_emby_http', upstream)
    monkeypatch.setattr(playback, 'resolve_playback_redirect', lambda *args: 'https://cdn.example/video')
    monkeypatch.setattr(playback, '_record_playback_request', lambda *args: None)
    client = TestClient(create_playback_app())
    response = client.get('/api/play/token', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'] == 'https://cdn.example/video'
    assert client.post('/api/cloud-video/discover', json={}).status_code == 422
    assert client.get('/api/transcode/capabilities').status_code == 404
    assert client.get('/api/plugins').status_code == 404


def test_cloud_access_redaction_registration_is_idempotent():
    logger = logging.getLogger('uvicorn.access')
    configure_access_log_redaction()
    configure_access_log_redaction()
    assert sum(isinstance(f, PlaybackAccessLogFilter) for f in logger.filters) == 1
