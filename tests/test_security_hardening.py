import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.responses import Response

from app.api.config import ConfigUpdate, redact_url_credentials, update_config
from app.core.security import create_session, verify_session
from app.main import add_security_headers, create_app


class SecurityHardeningTests(unittest.TestCase):
    def settings(self, password: str):
        return SimpleNamespace(
            auth_secret="fixed-test-secret",
            db_path="unused.db",
            media_user="owner",
            media_pass=password,
            session_ttl_seconds=3600,
            static_dir="missing-static-dir",
            tracking_scheduler_enabled=False,
            wishlist_scheduler_enabled=False,
        )

    def test_password_change_invalidates_existing_session(self):
        with patch("app.core.security.get_settings", return_value=self.settings("old-password")):
            token = create_session("owner")
            self.assertIsNotNone(verify_session(token))
        with patch("app.core.security.get_settings", return_value=self.settings("new-password")):
            self.assertIsNone(verify_session(token))

    def test_proxy_credentials_are_redacted(self):
        self.assertEqual(
            "http://proxy-user:***@proxy.local:7890/path",
            redact_url_credentials("http://proxy-user:secret@proxy.local:7890/path"),
        )
        self.assertEqual("http://proxy.local:7890", redact_url_credentials("http://proxy.local:7890"))
        self.assertEqual("http://***", redact_url_credentials("http://proxy-user:secret@proxy.local:not-a-port"))

    def test_config_update_still_persists_scheduler_and_category_values(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            payload = ConfigUpdate(
                wishlist_poll_minutes=15,
                wishlist_default_check_hour=8,
                wishlist_scheduler_enabled=False,
                category_paths={"tv": "/shows"},
            )
            with (
                patch.dict("os.environ", {"MEDIA_CONFIG_PATH": str(env_path)}),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = update_config(payload)
            saved = env_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn("WISHLIST_POLL_MINUTES=15", saved)
        self.assertIn("WISHLIST_DEFAULT_CHECK_HOUR=8", saved)
        self.assertIn('CATEGORY_PATHS_JSON={"tv":"/shows"}', saved)

    def test_security_headers_are_added(self):
        response = add_security_headers(Response())
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_unknown_get_api_path_is_not_frontend_html(self):
        with patch("app.main.get_settings", return_value=self.settings("password")):
            app = create_app()
        route = next(route for route in app.routes if getattr(route, "path", "") == "/{path:path}")
        with self.assertRaises(HTTPException) as raised:
            route.endpoint("api/does-not-exist")
        self.assertEqual(404, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()
