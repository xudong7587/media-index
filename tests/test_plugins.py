from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import plugins as api, transcode
from app.core.security import require_user
from app.services import plugins


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins, "get_settings", lambda: SimpleNamespace(db_path=str(tmp_path / "db.sqlite")))
    monkeypatch.delenv("TRANSCODE_WORKER_URL", raising=False)
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(transcode.router)
    return app, TestClient(app)


def test_admin_required(registry):
    _, client = registry
    assert client.get("/api/plugins").status_code in (401, 403)
    assert client.put("/api/plugins/playback-optimizer/state", json={"enabled": True}).status_code in (401, 403)


def test_persistence_and_unknown_plugin_rejection(registry):
    app, client = registry
    app.dependency_overrides[require_user] = lambda: "admin"
    assert not plugins.enabled()
    assert client.put("/api/plugins/arbitrary/state", json={"enabled": True}).status_code == 404
    assert client.put("/api/plugins/playback-optimizer/state", json={"enabled": "true"}).status_code == 422
    assert client.put("/api/plugins/playback-optimizer/state", json={"enabled": True}).status_code == 200
    assert plugins.enabled()
    assert client.put("/api/plugins/playback-optimizer/state", json={"enabled": False}).status_code == 200
    assert not plugins.enabled()


def test_disabled_plugin_never_contacts_worker(registry, monkeypatch):
    _, client = registry
    worker = Mock()
    monkeypatch.setattr(transcode, "call_worker", worker)
    assert client.get("/api/transcode/capabilities").json() == {"available": False, "profiles": []}
    assert client.post("/api/transcode/sessions", json={"assetToken": "token", "profile": "4k"}).status_code == 503
    worker.assert_not_called()


def test_corrupt_state_fails_closed(registry, monkeypatch):
    monkeypatch.setenv("TRANSCODE_WORKER_URL", "http://worker")
    assert plugins.enabled()
    plugins.set_enabled(False)
    plugins.state_path().write_text("invalid json", encoding="utf-8")
    assert not plugins.enabled()
    with pytest.raises(ValueError):
        plugins.set_enabled(True)
