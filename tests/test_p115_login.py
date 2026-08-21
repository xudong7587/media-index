from __future__ import annotations

from app.services.p115_login import P115OpenLoginService


class FakeP115Sdk:
    status = 0

    @staticmethod
    def login_qrcode_token_open(app_id: int):
        assert app_id == 100195125
        return {"state": True, "data": {"uid": "device-uid", "time": 1, "sign": "safe", "qrcode": "https://115.com/scan/device-uid"}}

    @classmethod
    def login_qrcode_scan_status(cls, payload):
        assert payload["uid"] == "device-uid"
        return {"state": True, "data": {"status": cls.status}}

    @staticmethod
    def login_qrcode_access_token_open(uid: str):
        assert uid == "device-uid"
        return {"state": True, "data": {"access_token": "access-secret", "refresh_token": "refresh-secret"}}


def test_p115_open_qr_flow_keeps_tokens_inside_service(monkeypatch):
    service = P115OpenLoginService()
    monkeypatch.setattr(service, "_sdk", lambda: FakeP115Sdk)

    session = service.start()
    assert session.qr_url == "https://115.com/scan/device-uid"

    FakeP115Sdk.status = 0
    assert service.poll(session.session_id).status == "waiting"
    FakeP115Sdk.status = 1
    assert service.poll(session.session_id).status == "scanned"
    FakeP115Sdk.status = 2
    result = service.poll(session.session_id)
    assert result.status == "success"
    assert result.access_token == "access-secret"
    assert result.refresh_token == "refresh-secret"
    assert service.poll(session.session_id).status == "expired"
