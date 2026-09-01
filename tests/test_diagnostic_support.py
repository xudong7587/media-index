import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.config import get_settings
from app.api.config import ConfigUpdate, update_config
from app.db.database import db, init_db
from app.services.diagnostic_support import (
    create_support_token,
    require_support_token,
    revoke_support_tokens,
    support_status,
)


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": ("127.0.0.1", 1234)})


def test_support_token_is_hashed_short_lived_read_only_and_revocable():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        with patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(temporary) / "support.db"),
                "DEVELOPER_REMOTE_DIAGNOSTICS_ENABLED": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            init_db()
            issued = create_support_token(30)
            assert issued["scope"] == "diagnostics:read"
            assert issued["token"].startswith("mi_diag_")
            with db() as conn:
                row = conn.execute("SELECT token_hash,token_prefix FROM diagnostic_support_tokens").fetchone()
            assert issued["token"] not in row["token_hash"]
            assert row["token_prefix"] == issued["token"][:16]
            assert require_support_token(_request(), f"Bearer {issued['token']}") > 0
            assert support_status()["active_token_count"] == 1
            assert revoke_support_tokens() == 1
            with pytest.raises(HTTPException) as error:
                require_support_token(_request(), f"Bearer {issued['token']}")
            assert error.value.status_code == 401
    get_settings.cache_clear()


def test_support_token_creation_is_fail_closed_when_option_is_disabled():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        with patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(temporary) / "support-disabled.db"),
                "DEVELOPER_REMOTE_DIAGNOSTICS_ENABLED": "false",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            init_db()
            with pytest.raises(HTTPException) as error:
                create_support_token(30)
            assert error.value.status_code == 409
    get_settings.cache_clear()


def test_disabling_developer_option_revokes_existing_tokens():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        env_path = Path(temporary) / ".env"
        env_path.write_text("DEVELOPER_REMOTE_DIAGNOSTICS_ENABLED=true\n", encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(temporary) / "support-toggle.db"),
                "MEDIA_CONFIG_PATH": str(env_path),
                "DEVELOPER_REMOTE_DIAGNOSTICS_ENABLED": "true",
            },
            clear=False,
        ), patch("app.api.config.stop_scheduler"), patch("app.api.config.start_scheduler"):
            get_settings.cache_clear()
            init_db()
            issued = create_support_token(30)
            update_config(ConfigUpdate(developer_remote_diagnostics_enabled=False))
            assert support_status()["enabled"] is False
            assert support_status()["active_token_count"] == 0
            with pytest.raises(HTTPException) as error:
                require_support_token(_request(), f"Bearer {issued['token']}")
            assert error.value.status_code == 403
    get_settings.cache_clear()
