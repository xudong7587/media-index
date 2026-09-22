from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.api.config import ConfigUpdate, update_config
from app.clients.p115 import P115Error, normalize_p115_cookie
from app.core.config import get_settings
from app.core.env_file import read_env_file
from app.services.p115_credentials import (
    mask_p115_cookie,
    reconcile_p115_cookie_from_environment,
    save_p115_cookie,
)


PASTED_COOKIE = " UID=1_A1_1\r\nCID=abc ;SEID=secret;KID=k2 "
CANONICAL_COOKIE = "UID=1_A1_1; CID=abc; SEID=secret; KID=k2"


def test_normalize_p115_cookie_orders_the_known_credential_fields():
    assert normalize_p115_cookie(PASTED_COOKIE) == CANONICAL_COOKIE
    assert normalize_p115_cookie("SEID=secret; CID=abc; UID=1") == "UID=1; CID=abc; SEID=secret"


def test_normalize_p115_cookie_keeps_extra_pairs_the_sdk_still_reads():
    assert normalize_p115_cookie("UID=1; CID=abc; SEID=secret; OOFL=g2gcp") == (
        "UID=1; CID=abc; SEID=secret; OOFL=g2gcp"
    )


def test_save_p115_cookie_writes_the_runtime_file_and_process_environment(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("P115_COOKIE=\nP115_AUTH_MODE=\nMEDIA_USER=admin\n", encoding="utf-8")

    with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
        saved = save_p115_cookie(PASTED_COOKIE)

        assert saved == CANONICAL_COOKIE
        assert os.environ["P115_COOKIE"] == CANONICAL_COOKIE
        assert os.environ["P115_AUTH_MODE"] == "cookie"
        assert get_settings().p115_cookie == CANONICAL_COOKIE

    stored = read_env_file(config_path)
    assert stored["P115_COOKIE"] == CANONICAL_COOKIE
    assert stored["P115_AUTH_MODE"] == "cookie"
    assert stored["MEDIA_USER"] == "admin"


def test_save_p115_cookie_persists_the_scan_login_app(tmp_path):
    config_path = tmp_path / ".env"

    with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
        save_p115_cookie(PASTED_COOKIE, app="alipaymini")

        assert os.environ["P115_COOKIE_APP"] == "alipaymini"
        assert get_settings().p115_cookie_app == "alipaymini"

    assert read_env_file(config_path)["P115_COOKIE_APP"] == "alipaymini"


def test_save_p115_cookie_refuses_an_incomplete_cookie_without_touching_the_file(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("P115_COOKIE=UID=1; CID=2\n", encoding="utf-8")

    with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
        with pytest.raises(P115Error):
            save_p115_cookie("UID=1; CID=2")

    assert read_env_file(config_path) == {"P115_COOKIE": "UID=1; CID=2"}


def test_save_p115_cookie_writes_a_quoted_value_that_still_reads_back_canonical(tmp_path):
    config_path = tmp_path / ".env"

    with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
        save_p115_cookie("UID=1_A1_1; CID=abc; SEID=se#cret")

    assert "P115_COOKIE=\"UID=1_A1_1; CID=abc; SEID=se#cret\"\n" in config_path.read_text(encoding="utf-8")
    assert read_env_file(config_path)["P115_COOKIE"] == "UID=1_A1_1; CID=abc; SEID=se#cret"


def test_mask_p115_cookie_never_repeats_the_stored_value():
    masked = mask_p115_cookie(CANONICAL_COOKIE)

    assert masked.startswith("UID=…A1_1")
    assert "secret" not in masked
    assert "abc" not in masked


def test_config_update_persists_the_cookie_through_the_same_writer(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("MEDIA_USER=admin\n", encoding="utf-8")

    with (
        patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False),
        patch("app.api.config.stop_scheduler"),
        patch("app.api.config.start_scheduler"),
    ):
        result = update_config(ConfigUpdate(p115_cookie=PASTED_COOKIE))

    assert result["ok"] is True
    stored = read_env_file(config_path)
    assert stored["P115_COOKIE"] == CANONICAL_COOKIE
    assert stored["P115_AUTH_MODE"] == "cookie"
    assert stored["MEDIA_USER"] == "admin"


def test_config_update_rejects_an_incomplete_cookie_without_writing_the_file(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("MEDIA_USER=admin\n", encoding="utf-8")

    with (
        patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False),
        patch("app.api.config.stop_scheduler"),
        patch("app.api.config.start_scheduler"),
    ):
        with pytest.raises(Exception) as caught:
            update_config(ConfigUpdate(p115_cookie="UID=1; CID=2"))

    assert getattr(caught.value, "status_code", None) == 422
    assert read_env_file(config_path) == {"MEDIA_USER": "admin"}


def test_reconcile_writes_a_cookie_that_only_exists_in_the_environment(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("P115_COOKIE=\nMEDIA_USER=admin\n", encoding="utf-8")

    with patch.dict(
        os.environ,
        {"MEDIA_CONFIG_PATH": str(config_path), "P115_COOKIE": PASTED_COOKIE},
        clear=False,
    ):
        assert reconcile_p115_cookie_from_environment() is True
        assert reconcile_p115_cookie_from_environment() is False

    stored = read_env_file(config_path)
    assert stored["P115_COOKIE"] == CANONICAL_COOKIE
    assert stored["P115_AUTH_MODE"] == "cookie"
    assert stored["MEDIA_USER"] == "admin"


def test_reconcile_keeps_the_file_cookie_when_the_environment_also_has_one(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("P115_COOKIE=UID=file; CID=file; SEID=file\n", encoding="utf-8")

    with patch.dict(
        os.environ,
        {"MEDIA_CONFIG_PATH": str(config_path), "P115_COOKIE": PASTED_COOKIE},
        clear=False,
    ):
        assert reconcile_p115_cookie_from_environment() is False

    assert read_env_file(config_path)["P115_COOKIE"] == "UID=file; CID=file; SEID=file"


def test_reconcile_ignores_an_invalid_environment_value(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("P115_COOKIE=\n", encoding="utf-8")

    with patch.dict(
        os.environ,
        {"MEDIA_CONFIG_PATH": str(config_path), "P115_COOKIE": "not-a-cookie"},
        clear=False,
    ):
        assert reconcile_p115_cookie_from_environment() is False

    assert read_env_file(config_path) == {"P115_COOKIE": ""}
