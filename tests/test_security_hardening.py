import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.responses import Response

from app.api.config import ConfigUpdate, redact_url_credentials, status as config_status, update_config
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

    def test_config_status_masks_internal_service_urls(self):
        settings = SimpleNamespace(
            tmdb_api_key="tmdb",
            qas_base_url="https://qas.internal:5005",
            qas_token="token",
            moviepilot_base_url="https://mp.internal:666",
            moviepilot_api_token="token",
            moviepilot_115_plugin_id="P115StrmHelper",
            p115_cookie="",
            p115_root_path="/strm",
            p115_staging_path="/.media-index-staging",
            p115_local_path="/downloads",
            enabled_provider_keys=lambda: ("qas",),
            default_provider_key=lambda: "qas",
            pansou_url="https://pansou.internal",
            proxy_url="http://proxy.internal:7890",
            cloud_save_path="/strm",
            provider_save_root=lambda provider: "/strm",
            local_save_path="/downloads",
            category_paths=lambda: {"tv": "/tv"},
            provider_category_paths=lambda provider: {"tv": "/tv"},
            media_folder_naming_rule="{title} ({year})",
            season_folder_naming_rule="Season {season}",
            movie_naming_rule="{title}.{year}",
            episode_naming_rule="{title}.{year}.S{season:02d}E{episode:02d}",
            season_subdirectory_enabled=False,
            openlist_enabled=True,
            openlist_auto_sync=True,
            openlist_url="https://openlist.internal",
            openlist_token="token",
            openlist_qas_library_path="/quark",
            openlist_p115_library_path="/115",
            wishlist_default_check_hour=9,
            wishlist_scheduler_enabled=True,
            wishlist_poll_minutes=5,
            notification_external_enabled=False,
            public_base_url="",
            telegram_enabled=False,
            telegram_bot_token="",
            telegram_chat_id="",
            telegram_api_host="https://api.telegram.org",
            wecom_enabled=False,
            wecom_key="",
            wecom_origin="https://qyapi.weixin.qq.com",
            wecom_app_enabled=False,
            wecom_corp_id="",
            wecom_app_secret="",
            wecom_app_agent_id=0,
            wecom_app_to_user="@all",
            wecom_app_to_party="",
            wecom_app_to_tag="",
            wecom_callback_enabled=False,
            wecom_callback_token="",
            wecom_callback_aes_key="",
            wecom_callback_allowed_users="",
        )
        with patch("app.api.config.get_settings", return_value=settings):
            result = config_status()
        for key in ("qas_base_url", "moviepilot_base_url", "pansou_url", "proxy_url", "openlist_url"):
            self.assertEqual("已保存", result[key])

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
