from __future__ import annotations

import json
import os
import urllib.parse
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response

from app.api import cloud as cloud_api
from app.api.cloud import P115CookieQrRequest, poll_p115_cookie_qrcode_login, start_p115_cookie_qrcode_login
from app.clients.p115 import P115Error
from app.core.env_file import read_env_file
from app.services.p115_cookie_login import (
    DEFAULT_P115_COOKIE_LOGIN_APP,
    P115CookieLoginService,
)


COOKIE_FIELDS = {"UID": "1_A1_1", "CID": "abc", "SEID": "secret", "KID": "k2"}
COOKIE_STRING = "UID=1_A1_1; CID=abc; SEID=secret; KID=k2"
class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> bool:
        return False


class FakeP115QrTransport:
    """Stand-in for the three 115 QR endpoints plus the device binding POST."""

    def __init__(self, *, status: object = 0, cookie: dict[str, str] | None = None) -> None:
        self.status = status
        self.cookie = COOKIE_FIELDS if cookie is None else cookie
        self.requests: list[str] = []
        self.post_bodies: list[str] = []

    def open(self, request, timeout=None):  # noqa: ANN001
        url = request.full_url
        self.requests.append(url)
        if url.startswith("https://qrcodeapi.115.com/api/1.0/web/1.0/token/"):
            return _FakeResponse(
                json.dumps({"state": 1, "data": {"uid": "qr-uid", "time": 173, "sign": "sig", "qrcode": "https://115.com/scan/dg-qr-uid"}}).encode()
            )
        if url.startswith("https://qrcodeapi.115.com/get/status/"):
            return _FakeResponse(json.dumps({"state": 1, "code": 0, "data": {"status": self.status}}).encode())
        if url.startswith("https://passportapi.115.com/"):
            self.post_bodies.append((request.data or b"").decode("utf-8"))
            return _FakeResponse(json.dumps({"state": 1, "code": 0, "data": {"cookie": self.cookie}}).encode())
        raise AssertionError(f"unexpected URL {url}")


def _service(transport: FakeP115QrTransport) -> P115CookieLoginService:
    return P115CookieLoginService(opener=transport)


def test_scan_login_returns_a_qr_image_and_a_short_lived_session():
    transport = FakeP115QrTransport()
    session = _service(transport).start()

    assert session.qr_image.startswith("data:image/png;base64,")
    assert len(session.session_id) >= 20
    assert session.app == DEFAULT_P115_COOKIE_LOGIN_APP
    assert not any("/mac/1.0/qrcode" in url for url in transport.requests)


def test_scan_login_reports_progress_then_persists_the_bound_cookie(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("P115_COOKIE=\n", encoding="utf-8")
    transport = FakeP115QrTransport(status=0)
    service = _service(transport)

    with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
        session = service.start()
        transport.status = 0
        assert service.poll(session.session_id).status == "waiting"
        transport.status = 1
        assert service.poll(session.session_id).status == "scanned"
        transport.status = 2
        result = service.poll(session.session_id)

        assert result.status == "done"
        assert result.masked_cookie.startswith("UID=…A1_1")
        assert "secret" not in result.masked_cookie
        assert os.environ["P115_COOKIE"] == COOKIE_STRING
        assert service.poll(session.session_id).status == "expired"

    stored = read_env_file(config_path)
    assert stored["P115_COOKIE"] == COOKIE_STRING
    assert stored["P115_AUTH_MODE"] == "cookie"
    assert transport.post_bodies == [urllib.parse.urlencode({"app": "alipaymini", "account": "qr-uid"})]


def test_scan_login_binds_the_requested_app(tmp_path):
    config_path = tmp_path / ".env"
    transport = FakeP115QrTransport(status=2)
    service = _service(transport)

    with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
        session = service.start("web")
        service.poll(session.session_id)

    assert session.app == "web"
    assert any("/app/1.0/web/1.0/login/qrcode/" in url for url in transport.requests)
    assert transport.post_bodies == [urllib.parse.urlencode({"app": "web", "account": "qr-uid"})]


def test_scan_login_rejects_an_unsupported_device():
    with pytest.raises(P115Error):
        _service(FakeP115QrTransport()).start("playstation")


@pytest.mark.parametrize(
    ("status", "expected"),
    [(0, "waiting"), (1, "scanned"), (-1, "expired"), (-2, "canceled")],
)
def test_scan_login_maps_the_upstream_status_codes(status, expected):
    service = _service(FakeP115QrTransport(status=status))
    session = service.start()

    assert service.poll(session.session_id).status == expected


def test_scan_login_unknown_upstream_status_keeps_waiting():
    service = _service(FakeP115QrTransport(status=99))
    session = service.start()

    assert service.poll(session.session_id).status == "waiting"


def test_scan_login_reports_an_incomplete_bound_cookie(tmp_path):
    config_path = tmp_path / ".env"
    service = _service(FakeP115QrTransport(status=2, cookie={"SEID": "only"}))

    with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
        session = service.start()
        with pytest.raises(P115Error):
            service.poll(session.session_id)

    assert not config_path.exists()


def test_scan_login_reports_a_safe_failure_when_the_token_endpoint_rejects():
    class RejectingTransport(FakeP115QrTransport):
        def open(self, request, timeout=None):  # noqa: ANN001
            return _FakeResponse(json.dumps({"state": 0, "message": "ip is limited"}).encode())

    with pytest.raises(P115Error) as caught:
        P115CookieLoginService(opener=RejectingTransport()).start()

    assert "ip is limited" in str(caught.value)


def test_status_read_timeout_keeps_the_scan_waiting_instead_of_failing():
    class SlowStatusTransport(FakeP115QrTransport):
        def open(self, request, timeout=None):  # noqa: ANN001
            if request.full_url.startswith("https://qrcodeapi.115.com/get/status/"):
                raise TimeoutError("read timed out")
            return super().open(request, timeout=timeout)

    transport = SlowStatusTransport()
    service = _service(transport)
    session = service.start()

    first = service.poll(session.session_id)
    second = service.poll(session.session_id)

    assert first.status == "waiting"
    assert "网络较慢" in first.message
    assert second.status == "waiting"


def test_start_timeout_is_reported_to_the_caller():
    class SlowTokenTransport(FakeP115QrTransport):
        def open(self, request, timeout=None):  # noqa: ANN001
            raise TimeoutError("read timed out")

    with pytest.raises(P115Error) as caught:
        P115CookieLoginService(opener=SlowTokenTransport()).start()

    assert "超时" in str(caught.value)


def test_start_endpoint_exposes_the_session_and_the_device_warning():
    class StubService:
        def start(self, app=None):  # noqa: ANN001
            assert app is None
            return type(
                "Session",
                (),
                {
                    "session_id": "s" * 40,
                    "app": "windows",
                    "qr_image": "data:image/png;base64,AAAA",
                    "expires_at": 1e12,
                },
            )()

    with patch.object(cloud_api, "_p115_cookie_login", StubService()):
        payload = start_p115_cookie_qrcode_login(P115CookieQrRequest())

    assert payload["ok"] is True
    assert payload["session_id"] == "s" * 40
    assert payload["app"] == "windows"
    assert payload["default_app"] == "alipaymini"
    assert "踢掉" in payload["device_notice"]


def test_poll_endpoint_returns_masked_status_and_rejects_unknown_sessions(tmp_path):
    config_path = tmp_path / ".env"
    transport = FakeP115QrTransport(status=0)
    service = _service(transport)

    with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
        session = service.start()
        with patch.object(cloud_api, "_p115_cookie_login", service):
            waiting = poll_p115_cookie_qrcode_login(session.session_id, Response())
            transport.status = 2
            done = poll_p115_cookie_qrcode_login(session.session_id, Response())

    assert waiting["status"] == "waiting"
    assert done["status"] == "done"
    assert done["cookie_masked"].startswith("UID=…A1_1")
    assert set(done) == {"ok", "status", "message", "cookie_masked"}
    with pytest.raises(HTTPException) as caught:
        poll_p115_cookie_qrcode_login("bad", Response())
    assert caught.value.status_code == 404
