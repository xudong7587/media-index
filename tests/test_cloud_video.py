import io
import json
import logging
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.cloud_video import router
from app.clients.p115 import P115Error
from app.clients.p115_video import P115VideoClient, media_url, parse_master
from app.core.config import Settings
from app.services import cloud_video as service
from app.services.playback import PlaybackError
from app.services.transcode import TranscodeAccessLogFilter

MASTER = b'''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Chinese",URI="audio.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2",AUDIO="audio"
1080.m3u8?sign=private
#EXT-X-STREAM-INF:BANDWIDTH=15000000,RESOLUTION=3840x2160,CODECS="avc1.640033,mp4a.40.2",AUDIO="audio"
4k.m3u8?sign=private
'''
BASE = 'https://video.115.com/movie/master.m3u8'
UA = 'SunnyTV/1.0'


@pytest.fixture
def gateway(monkeypatch):
    service._SESSIONS.clear()
    monkeypatch.setattr(service, 'verify_asset_token', lambda token: {'provider': 'p115', 'file_id': '123'})
    monkeypatch.setattr(P115VideoClient, 'discover', lambda self, fid, ua: parse_master(MASTER, BASE))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, headers={'User-Agent': UA}) as client:
        yield client
    service._SESSIONS.clear()


def start(gateway, delivery=None):
    result = gateway.post('/api/cloud-video/discover', json={'assetToken': 'valid'})
    assert result.status_code == 200
    variants = result.json()['variants']
    assert variants[0]['width'] == 3840
    payload = {'assetToken': 'valid', 'variantId': variants[0]['id']}
    if delivery is not None:
        payload['delivery'] = delivery
    response = gateway.post('/api/cloud-video/sessions', json=payload)
    assert response.status_code == 200
    return response.json()


def test_discovery_and_selection_do_not_expose_provider_addresses(gateway):
    result = start(gateway)
    assert result['delivery'] == 'direct'
    assert result['protocol'] == service.PROTOCOL
    assert result['seekMode'] == 'hls-vod'
    assert 'private' not in json.dumps(result)
    master = gateway.get(result['playlistUrl'])
    assert master.status_code == 200
    assert master.headers['cache-control'] == 'no-store'
    assert 'RESOLUTION=3840x2160' in master.text
    assert 'RESOLUTION=1920x1080' not in master.text
    assert 'video.115.com' not in master.text and 'private' not in master.text
    assert 'TYPE=AUDIO' in master.text


def test_direct_media_bypasses_gateway_and_preserves_ranges_and_signed_encoding(gateway, monkeypatch):
    result = start(gateway)
    child_url = gateway.get(result['playlistUrl']).text.strip().splitlines()[-1]
    child = b'''#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-KEY:METHOD=AES-128,URI="key.bin?secret=x"
#EXT-X-MAP:URI="init.mp4?sign=abc%2Fdef%2Bghi"
#EXT-X-BYTERANGE:1024@0
#EXTINF:4,
http://video.115.com/media.ts?sign=abc%2Fdef%2Bghi
#EXT-X-ENDLIST
'''
    monkeypatch.setattr(P115VideoClient, 'read_manifest', lambda *args: (child, BASE))
    opened = Mock(side_effect=AssertionError('Direct mode must not fetch video bytes'))
    monkeypatch.setattr(P115VideoClient, 'open_media', opened)
    response = gateway.get(child_url)
    assert response.status_code == 200
    assert 'https://video.115.com/media.ts?sign=abc%2Fdef%2Bghi' in response.text
    assert 'URI="https://video.115.com/movie/init.mp4?sign=abc%2Fdef%2Bghi"' in response.text
    assert '#EXT-X-BYTERANGE:1024@0' in response.text
    assert 'URI="/api/cloud-video/' in response.text  # only the key remains proxied
    assert all(kind != 'media' for _, kind in service._SESSIONS[result['sessionId']].resources.values())
    opened.assert_not_called()


@pytest.mark.parametrize('target', ['https://evil.test/segment.ts', 'http://127.0.0.1/private', 'https://115.com:8443/a'])
def test_direct_mode_still_rejects_untrusted_segment_urls(gateway, monkeypatch, target):
    result = start(gateway)
    child_url = gateway.get(result['playlistUrl']).text.strip().splitlines()[-1]
    child = f'#EXTM3U\n#EXTINF:4,\n{target}\n#EXT-X-ENDLIST\n'.encode()
    monkeypatch.setattr(P115VideoClient, 'read_manifest', lambda *args: (child, BASE))
    response = gateway.get(child_url)
    assert response.status_code == 409 and target not in response.text


def test_proxy_is_explicit_and_unknown_delivery_rejected(gateway):
    result = start(gateway, 'proxy')
    assert result['delivery'] == 'proxy'
    response = gateway.post('/api/cloud-video/sessions', json={
        'assetToken': 'valid', 'variantId': result['variant']['id'], 'delivery': 'auto-proxy'})
    assert response.status_code == 422


def test_invalid_asset_never_calls_provider(gateway, monkeypatch):
    def reject(token):
        raise PlaybackError('secret')
    monkeypatch.setattr(service, 'verify_asset_token', reject)
    call = Mock()
    monkeypatch.setattr(P115VideoClient, 'discover', call)
    response = gateway.post('/api/cloud-video/discover', json={'assetToken': 'invalid'})
    assert response.status_code == 403 and 'secret' not in response.text
    call.assert_not_called()


def test_non115_asset_is_rejected(gateway, monkeypatch):
    monkeypatch.setattr(service, 'verify_asset_token', lambda token: {'provider': 'quark'})
    call = Mock()
    monkeypatch.setattr(P115VideoClient, 'discover', call)
    assert gateway.post('/api/cloud-video/discover', json={'assetToken': 'valid'}).status_code == 409
    call.assert_not_called()


def test_session_checks_token_user_agent_and_revoked_asset(gateway, monkeypatch):
    result = start(gateway)
    url = result['playlistUrl']
    assert gateway.get(url + '&st=another').status_code == 403
    assert gateway.get(url, headers={'User-Agent': 'Other'}).status_code == 403
    assert gateway.get(url.replace(result['sessionToken'], 'wrong')).status_code == 403
    def reject(token):
        raise PlaybackError('revoked')
    monkeypatch.setattr(service, 'verify_asset_token', reject)
    assert gateway.get(url).status_code == 403


def test_session_stop_and_expiry(gateway, monkeypatch):
    result = start(gateway)
    root = f"/api/cloud-video/sessions/{result['sessionId']}?st={result['sessionToken']}"
    assert gateway.delete(root).status_code == 204
    assert gateway.get(result['playlistUrl']).status_code == 403
    result = start(gateway)
    service._SESSIONS[result['sessionId']].touched -= 7201
    assert gateway.get(result['playlistUrl']).status_code == 403


def test_unknown_variant_and_full_registry_fail_without_eviction(gateway, monkeypatch):
    assert gateway.post('/api/cloud-video/sessions', json={'assetToken': 'valid', 'variantId': '0' * 32}).status_code == 409
    assert not service._SESSIONS
    monkeypatch.setattr(service, '_MAX_SESSIONS', 1)
    result = start(gateway)
    response = gateway.post('/api/cloud-video/sessions', json={'assetToken': 'valid', 'variantId': result['variant']['id']})
    assert response.status_code == 429
    assert gateway.get(result['playlistUrl']).status_code == 200


def test_media_playlist_keys_maps_ranges_and_close(gateway, monkeypatch):
    result = start(gateway, 'proxy')
    master = gateway.get(result['playlistUrl']).text
    variant_url = master.strip().splitlines()[-1]
    child = b'''#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-KEY:METHOD=AES-128,URI="key.bin?secret=x"
#EXT-X-MAP:URI="init.mp4"
#EXTINF:4,
segment.ts
#EXT-X-ENDLIST
'''
    monkeypatch.setattr(P115VideoClient, 'read_manifest', lambda self, url, ua: (child, 'https://video.115.com/new/child.m3u8'))
    response = gateway.get(variant_url)
    assert response.status_code == 200
    assert 'secret=x' not in response.text
    sess = service._SESSIONS[result['sessionId']]
    assert ('https://video.115.com/new/segment.ts', 'media') in sess.resources.values()
    stream = io.BytesIO(b'abcd')
    stream.status = 206
    stream.headers = {'Content-Type': 'video/mp2t', 'Content-Range': 'bytes 0-3/10'}
    opened = Mock(return_value=(stream, 'https://video.115.com/new/segment.ts'))
    monkeypatch.setattr(P115VideoClient, 'open_media', opened)
    segment_url = [line for line in response.text.splitlines() if line.startswith('/api/')][0]
    media = gateway.get(segment_url, headers={'Range': 'bytes=0-3'})
    assert media.status_code == 206 and media.content == b'abcd' and stream.closed
    assert media.headers['content-range'] == 'bytes 0-3/10'
    assert opened.call_args.args[1:] == (UA, 'bytes=0-3')


@pytest.mark.parametrize('url', ['http://video.115.com/a', 'https://115.com.evil.test/a', 'https://127.0.0.1/a',
                                     'https://user@115.com/a', 'https://115.com:444/a', 'https://115.com/a#x',
                                     'https://115.com/\\evil', 'https://115.com/a\nCookie:bad'])
def test_url_boundary(url):
    with pytest.raises(P115Error):
        media_url(url)


@pytest.mark.parametrize('target', [
    'https://115.com/api/video/m3u8/other123.m3u8',
    'https://115.com/api/video/m3u8/abc12345.m3u8?unexpected=1',
    'https://video.115.com/api/video/m3u8/abc12345.m3u8',
])
def test_entry_cookie_requires_exact_verified_pickcode_url(monkeypatch, target):
    client = P115VideoClient(Settings(_env_file=None, p115_cookie='UID=fixture'))
    monkeypatch.setattr(client, '_api', Mock(side_effect=[
        {'data': [{'fid': '123', 'pc': 'abc12345'}]}, {'video_url': target}]))
    response = io.BytesIO(MASTER)
    response.status = 200
    opened = Mock(return_value=response)
    monkeypatch.setattr(client._opener, 'open', opened)
    client.discover('123', UA)
    assert opened.call_args.args[0].get_header('Cookie') is None


def test_entry_redirect_drops_cookie_and_referer(monkeypatch):
    client = P115VideoClient(Settings(_env_file=None, p115_cookie='UID=fixture'))
    entry = 'https://115.com/api/video/m3u8/abc12345.m3u8'
    monkeypatch.setattr(client, '_api', Mock(side_effect=[
        {'data': [{'fid': '123', 'pc': 'abc12345'}]}, {'video_url': entry}]))
    response = io.BytesIO(MASTER)
    response.status = 200
    redirect = urllib.error.HTTPError(entry, 302, 'redirect', {'Location': BASE}, io.BytesIO())
    opened = Mock(side_effect=[redirect, response])
    monkeypatch.setattr(client._opener, 'open', opened)
    client.discover('123', UA)
    initial, redirected = [call.args[0] for call in opened.call_args_list]
    assert initial.get_header('Cookie') == 'UID=fixture'
    assert redirected.get_header('Cookie') is None
    assert redirected.get_header('Referer') is None


@pytest.mark.parametrize('body', [b'not a playlist', b'#EXTM3U\n#EXTINF:3,\na.ts\n',
                                  MASTER.replace(b'3840x2160', b'0x0'), MASTER.replace(b'4k.m3u8?sign=private', b'https://evil.test/secret'),
                                  b'#EXTM3U\n#EXT-X-DEFINE:NAME="v",VALUE="x"\n'])
def test_invalid_master_rejected(body):
    with pytest.raises(P115Error):
        parse_master(body, BASE)


def test_resource_failure_is_redacted_and_live_playlist_rejected(gateway, monkeypatch):
    result = start(gateway)
    url = gateway.get(result['playlistUrl']).text.strip().splitlines()[-1]
    monkeypatch.setattr(P115VideoClient, 'read_manifest', lambda *args: (b'#EXTM3U\n#EXTINF:4,\na.ts\n', BASE))
    assert gateway.get(url).status_code == 409
    def fail(*args):
        raise RuntimeError('https://private/?Cookie=secret')
    monkeypatch.setattr(P115VideoClient, 'read_manifest', fail)
    response = gateway.get(url)
    assert response.status_code == 502 and 'secret' not in response.text


@pytest.mark.parametrize('pick_field', ['pick_code', 'pickcode', 'pc'])
@pytest.mark.parametrize('entry', [False, True])
def test_credential_transport_is_fixed_and_media_never_receives_cookie(monkeypatch, pick_field, entry):
    settings = Settings(_env_file=None, p115_cookie='UID=1; CID=2; SEID=secret')
    client = P115VideoClient(settings)
    def response(body, status=200):
        obj = io.BytesIO(body)
        obj.status = status
        return obj
    target = 'http://115.com/api/video/m3u8/abc12345.m3u8' if entry else BASE
    replies = [response(json.dumps({'state': True, 'data': [{'fid': '123', pick_field: 'abc12345'}]}).encode()),
               response(json.dumps({'state': True, 'video_url': target}).encode()), response(MASTER)]
    opener = Mock(side_effect=replies)
    monkeypatch.setattr(client._opener, 'open', opener)
    result = client.discover('123', UA)
    assert len(result.variants) == 2
    requests = [c.args[0] for c in opener.call_args_list]
    assert requests[0].get_header('Cookie') == settings.p115_cookie
    assert requests[1].get_header('Cookie') == settings.p115_cookie
    assert requests[2].get_header('Cookie') == (settings.p115_cookie if entry else None)
    assert all(r.get_header('User-agent') == UA for r in requests)


def test_file_identity_mismatch_prevents_video_query(monkeypatch):
    client = P115VideoClient(Settings(_env_file=None))
    api = Mock(return_value={'state': True, 'data': [{'file_id': 'wrong', 'pick_code': 'abc12345'}]})
    monkeypatch.setattr(client, '_api', api)
    with pytest.raises(P115Error, match='不一致'):
        client.discover('123', UA)
    assert api.call_count == 1


def test_redirect_validated_without_credentials(monkeypatch):
    client = P115VideoClient(Settings(_env_file=None))
    error = urllib.error.HTTPError(BASE, 302, 'redirect', {'Location': 'https://evil.test/steal'}, None)
    opener = Mock(side_effect=error)
    monkeypatch.setattr(client._opener, 'open', opener)
    with pytest.raises(P115Error):
        client.open_media(BASE, UA)
    assert opener.call_count == 1


def test_access_logs_redact_cloud_session_secret():
    record = logging.LogRecord('uvicorn.access', 20, '', 1, '%s %s %s %s %s',
                               ('client', 'GET', '/api/cloud-video/sessions/id/index.m3u8?st=private', '1.1', 200), None)
    TranscodeAccessLogFilter().filter(record)
    assert 'private' not in record.getMessage()


def test_legacy_manifest_http_uris_upgrade_but_redirect_downgrades_do_not():
    manifest = parse_master(MASTER.replace(b'1080.m3u8?sign=private', b'http://video.115.com/1080.m3u8'), BASE)
    assert all(v.url.startswith('https://') for v in manifest.variants)
    with pytest.raises(P115Error):
        media_url('http://video.115.com/redirect', BASE)
    with pytest.raises(P115Error):
        media_url('http://evil.test/redirect', BASE, upgrade_http=True)


def test_expired_provider_login_is_distinct_from_asset_authorization(gateway, monkeypatch):
    from app.clients.p115_video import P115VideoAuthError
    def expired(*args):
        raise P115VideoAuthError('115 登录已过期，请在 MediaIndex 重新扫码登录')
    monkeypatch.setattr(P115VideoClient, 'discover', expired)
    assert gateway.post('/api/cloud-video/discover', json={'assetToken': 'valid'}).status_code == 401


def test_provider_login_errno_has_no_echo_of_sensitive_response(monkeypatch):
    from app.clients.p115_video import P115VideoAuthError
    client = P115VideoClient(Settings(_env_file=None, p115_cookie='UID=1; CID=2; SEID=secret'))
    response = io.BytesIO(b'{"state":false,"errno":990001,"error":"private signed URL"}')
    monkeypatch.setattr(client._opener, 'open', Mock(return_value=response))
    with pytest.raises(P115VideoAuthError) as error:
        client.discover('123', UA)
    assert 'private' not in str(error.value)
