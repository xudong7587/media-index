import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.responses import Response

from app.api.config import (
    CONFIG_EXPORT_FORMAT,
    ConfigImport,
    ConfigUpdate,
    LocalBrowseRequest,
    ProviderBrowseRequest,
    browse_provider_path,
    browse_local_path,
    clear_p115_open,
    export_config,
    import_config,
    redact_url_credentials,
    reveal_secret,
    status as config_status,
    test_p115 as run_p115_connection_test,
    update_config,
)
from app.core.security import create_session, verify_session
from app.core.config import get_settings
from app.clients.p115 import P115Error
from app.db.database import db, init_db
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

    def test_config_status_returns_non_secret_service_urls(self):
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
            emby_base_url="http://emby.internal:8096",
            emby_api_key="emby-secret",
            emby_proxy_port=8097,
            wishlist_default_check_hour=9,
            wishlist_scheduler_enabled=True,
            wishlist_poll_minutes=5,
            notification_external_enabled=False,
            public_base_url="",
            wecom_callback_url="",
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
        self.assertEqual("https://qas.internal:5005", result["qas_base_url"])
        self.assertEqual("https://mp.internal:666", result["moviepilot_base_url"])
        self.assertEqual("https://pansou.internal", result["pansou_url"])
        self.assertEqual("http://proxy.internal:7890", result["proxy_url"])
        self.assertEqual("https://openlist.internal", result["openlist_url"])
        self.assertEqual("http://emby.internal:8096", result["emby_base_url"])
        self.assertTrue(result["has_emby_api_key"])
        self.assertNotIn("emby_api_key", result)

    def test_saved_secret_is_only_revealed_for_explicit_whitelisted_field(self):
        with patch("app.api.config.get_settings", return_value=SimpleNamespace(emby_api_key="emby-secret")):
            self.assertEqual({"name": "emby_api_key", "value": "emby-secret"}, reveal_secret("emby_api_key"))
            with self.assertRaises(HTTPException) as raised:
                reveal_secret("auth_secret")
        self.assertEqual(404, raised.exception.status_code)

    def test_config_update_still_persists_scheduler_and_category_values(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            payload = ConfigUpdate(
                wishlist_poll_minutes=15,
                wishlist_default_check_hour=8,
                wishlist_scheduler_enabled=False,
                tracking_poll_minutes=10,
                tracking_scheduler_enabled=True,
                wecom_callback_url="https://media.example/wecom/callback",
                category_paths={"tv": "/shows"},
                quality_priority_keywords=["1080P", "4K 原盘"],
                emby_base_url="http://emby.internal:8096",
                emby_api_key="emby-secret",
                emby_proxy_port=18097,
                emby_strm_library_root="D:\\媒体库\\STRM\\",
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
        self.assertIn("TRACKING_POLL_MINUTES=10", saved)
        self.assertIn("TRACKING_SCHEDULER_ENABLED=true", saved)
        self.assertIn("WECOM_CALLBACK_URL=https://media.example/wecom/callback", saved)
        self.assertIn('CATEGORY_PATHS_JSON={"tv":"/shows"}', saved)
        self.assertIn('QUALITY_PRIORITY_KEYWORDS_JSON=["1080P","4K 原盘"]', saved)
        self.assertIn("EMBY_BASE_URL=http://emby.internal:8096", saved)
        self.assertIn("EMBY_API_KEY=emby-secret", saved)
        self.assertIn("EMBY_PROXY_PORT=18097", saved)
        self.assertIn("EMBY_STRM_LIBRARY_ROOT=D:/媒体库/STRM", saved)

    def test_strm_source_roots_save_independently_from_transfer_roots_and_validate_cron(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("P115_ROOT_PATH=/转存/115\nQUARK_ROOT_PATH=/转存/夸克\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = update_config(ConfigUpdate(
                    p115_strm_source_root="/媒体库/115",
                    quark_strm_source_root="/媒体库/夸克",
                    p115_strm_included_directories=["/媒体库/115/电影", "/媒体库/115/电视剧"],
                    p115_strm_incremental_cron="0 */6 * * *",
                ))
            saved = env_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn("P115_ROOT_PATH=/转存/115", saved)
        self.assertIn("QUARK_ROOT_PATH=/转存/夸克", saved)
        self.assertIn("P115_STRM_SOURCE_ROOT=/媒体库/115", saved)
        self.assertIn("QUARK_STRM_SOURCE_ROOT=/媒体库/夸克", saved)
        self.assertIn('P115_STRM_INCLUDED_DIRECTORIES_JSON=["/媒体库/115/电影","/媒体库/115/电视剧"]', saved)
        self.assertIn("P115_STRM_INCREMENTAL_CRON=0 */6 * * *", saved)

    def test_strm_selected_directory_must_be_a_direct_child_of_the_source_root(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                with self.assertRaisesRegex(HTTPException, "直接子目录"):
                    update_config(ConfigUpdate(
                        p115_strm_source_root="/媒体库",
                        p115_strm_included_directories=["/媒体库/电视剧/Season 1"],
                    ))

    def test_webhook_cannot_be_enabled_without_saved_strm_subdirectory_scope(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "STRM_OUTPUT_ROOT=/strm\nP115_STRM_SOURCE_ROOT=/媒体库\nP115_STRM_INCLUDED_DIRECTORIES_JSON=[]\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "MEDIA_CONFIG_PATH": str(env_path),
                "STRM_OUTPUT_ROOT": "/strm",
                "P115_STRM_SOURCE_ROOT": "/媒体库",
                "P115_STRM_INCLUDED_DIRECTORIES_JSON": "[]",
            }, clear=False):
                with self.assertRaisesRegex(HTTPException, "扫描子目录"):
                    update_config(ConfigUpdate(
                        mdc_webhook_enabled=True,
                        mdc_webhook_token="w" * 32,
                        mdc_webhook_provider="p115",
                    ))

    def test_local_strm_picker_is_confined_to_mounted_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "strm"
            child = root / "剧集"
            child.mkdir(parents=True)
            with patch.dict(os.environ, {"STRM_BROWSE_ROOT": str(root)}, clear=False):
                result = browse_local_path(LocalBrowseRequest(path=str(root)))
                self.assertEqual(str(root.resolve()), result["root"])
                self.assertTrue(result["exists"])
                self.assertEqual([{"name": "剧集", "is_dir": True}], result["directories"])
                pending = browse_local_path(LocalBrowseRequest(path=str(root / "尚未创建")))
                self.assertFalse(pending["exists"])
                self.assertEqual(str((root / "尚未创建").resolve()), pending["path"])
                self.assertEqual([], pending["directories"])
                with self.assertRaises(HTTPException):
                    browse_local_path(LocalBrowseRequest(path=str(Path(directory).parent)))

    def test_emby_strm_library_root_can_be_cleared(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("EMBY_STRM_LIBRARY_ROOT=/media/strm\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path), "EMBY_STRM_LIBRARY_ROOT": "/media/strm"}, clear=False),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = update_config(ConfigUpdate(emby_strm_library_root=""))

            self.assertTrue(result["ok"])
            self.assertNotIn("EMBY_STRM_LIBRARY_ROOT", env_path.read_text(encoding="utf-8"))

    def test_partial_common_category_update_preserves_other_saved_paths(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text('CATEGORY_PATHS_JSON={"movie":"/旧电影","tv":"/自定义剧集"}\n', encoding="utf-8")
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = update_config(ConfigUpdate(category_paths={"movie": "/新电影"}))

            saved = env_path.read_text(encoding="utf-8")

        self.assertTrue(result["ok"])
        self.assertIn('CATEGORY_PATHS_JSON={"movie":"/新电影","tv":"/自定义剧集"}', saved)

    def test_emby_strm_library_root_rejects_control_characters(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                for invalid in ("/media/strm\n", "/media/strm\r", "/media/strm\x00suffix"):
                    with self.subTest(invalid=repr(invalid)), self.assertRaises(HTTPException) as raised:
                        update_config(ConfigUpdate(emby_strm_library_root=invalid))
                    self.assertEqual(422, raised.exception.status_code)

    def test_config_backup_includes_emby_visible_strm_root(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("EMBY_STRM_LIBRARY_ROOT=/media/strm\n", encoding="utf-8")
            with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False):
                backup = export_config()

        self.assertEqual("/media/strm", backup["settings"]["EMBY_STRM_LIBRARY_ROOT"])

    def test_compose_locked_playback_port_cannot_be_changed_from_api(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with patch.dict("os.environ", {"MEDIA_CONFIG_PATH": str(env_path), "EMBY_PROXY_PORT_LOCKED": "true"}, clear=False):
                with self.assertRaises(HTTPException) as context:
                    update_config(ConfigUpdate(emby_proxy_port=18097))
        self.assertEqual(409, context.exception.status_code)
        self.assertIn("Compose", str(context.exception.detail))

    def test_config_update_restores_runtime_environment_when_atomic_write_fails(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENLIST_AUTO_SYNC_DIRECTION=bidirectional\n", encoding="utf-8")
            with (
                patch.dict(
                    "os.environ",
                    {
                        "MEDIA_CONFIG_PATH": str(env_path),
                        "OPENLIST_AUTO_SYNC_DIRECTION": "bidirectional",
                    },
                ),
                patch("app.api.config.atomic_write_env", side_effect=OSError("disk full")),
            ):
                with self.assertRaises(OSError):
                    update_config(ConfigUpdate(openlist_auto_sync_direction="qas_to_p115"))
                self.assertEqual("bidirectional", os.environ["OPENLIST_AUTO_SYNC_DIRECTION"])

    def test_config_rejects_enabling_strm_without_output_and_playback_addresses(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("P115_STRM_ENABLED=false\n", encoding="utf-8")
            with patch.dict("os.environ", {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False):
                with self.assertRaises(HTTPException) as raised:
                    update_config(ConfigUpdate(p115_strm_enabled=True))

        self.assertEqual(422, raised.exception.status_code)
        self.assertIn("输出目录", raised.exception.detail)

    def test_config_allows_clearing_an_unused_strm_playback_address(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("STRM_PLAYBACK_BASE_URL=http://media-index:8000\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = update_config(ConfigUpdate(strm_playback_base_url=""))

            self.assertTrue(result["ok"])
            self.assertNotIn("STRM_PLAYBACK_BASE_URL", env_path.read_text(encoding="utf-8"))

    def test_config_saves_explicit_external_strm_playback_address(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("", encoding="utf-8")
            with (
                patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(env_path)}, clear=False),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = update_config(ConfigUpdate(strm_playback_base_url="https://tvb302.example.com:666"))

            self.assertTrue(result["ok"])
            self.assertIn("STRM_PLAYBACK_BASE_URL=https://tvb302.example.com:666", env_path.read_text(encoding="utf-8"))

    def test_config_backup_includes_safe_compose_settings(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {
                "MEDIA_CONFIG_PATH": str(env_path),
                "PANSOU_URL": "http://pansou:8888",
                "STRM_OUTPUT_ROOT": "/strm",
                "MEDIA_PASS": "deployment-secret",
            }, clear=False):
                backup = export_config()

        self.assertEqual("http://pansou:8888", backup["settings"]["PANSOU_URL"])
        self.assertEqual("/strm", backup["settings"]["STRM_OUTPUT_ROOT"])
        self.assertNotIn("MEDIA_PASS", backup["settings"])

    def test_config_backup_keeps_target_login_and_runtime_settings(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "MEDIA_USER=nas-user\nMEDIA_PASS=nas-password\nAUTH_SECRET=nas-secret\nDB_PATH=/data/media.db\nTMDB_API_KEY=old\n",
                encoding="utf-8",
            )
            payload = ConfigImport(
                format=CONFIG_EXPORT_FORMAT,
                settings={
                    "MEDIA_USER": "local",
                    "MEDIA_PASS": "local055",
                    "AUTH_SECRET": "local-secret",
                    "DB_PATH": "/local/media.db",
                    "TMDB_API_KEY": "new",
                },
            )
            with (
                patch.dict("os.environ", {"MEDIA_CONFIG_PATH": str(env_path)}),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                result = import_config(payload)
                exported = export_config()
            saved = env_path.read_text(encoding="utf-8")

        self.assertTrue(result["ok"])
        self.assertIn("MEDIA_USER=nas-user", saved)
        self.assertIn("MEDIA_PASS=nas-password", saved)
        self.assertIn("AUTH_SECRET=nas-secret", saved)
        self.assertIn("DB_PATH=/data/media.db", saved)
        self.assertIn("TMDB_API_KEY=new", saved)
        self.assertNotIn("MEDIA_USER", exported["settings"])
        self.assertNotIn("MEDIA_PASS", exported["settings"])
        self.assertNotIn("AUTH_SECRET", exported["settings"])

    def test_config_import_rejects_unknown_environment_keys(self):
        with self.assertRaises(HTTPException) as raised:
            import_config(
                ConfigImport(
                    format=CONFIG_EXPORT_FORMAT,
                    settings={"HOME": "/attacker-controlled"},
                )
            )
        self.assertEqual(422, raised.exception.status_code)

    def test_config_import_keeps_current_session_valid(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            db_path = Path(directory) / "media.db"
            payload = ConfigImport(
                format=CONFIG_EXPORT_FORMAT,
                settings={
                    "MEDIA_USER": "local",
                    "MEDIA_PASS": "local055",
                    "AUTH_SECRET": "local-secret",
                    "DB_PATH": "/local/media.db",
                    "TMDB_API_KEY": "new",
                },
            )
            with (
                patch.dict(
                    "os.environ",
                    {
                        "MEDIA_CONFIG_PATH": str(env_path),
                        "MEDIA_USER": "nas-user",
                        "MEDIA_PASS": "nas-password",
                        "DB_PATH": str(db_path),
                    },
                    clear=False,
                ),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                from app.core.config import get_settings

                get_settings.cache_clear()
                token = create_session("nas-user")
                import_config(payload)
                self.assertIsNotNone(verify_session(token))
                get_settings.cache_clear()

    def test_config_backup_restores_wishlist_and_tracking_tasks(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            db_path = Path(directory) / "media.db"
            with (
                patch.dict(
                    os.environ,
                    {"MEDIA_CONFIG_PATH": str(env_path), "DB_PATH": str(db_path)},
                    clear=False,
                ),
                patch("app.api.config.stop_scheduler"),
                patch("app.api.config.start_scheduler"),
            ):
                get_settings.cache_clear()

                init_db()
                with db() as conn:
                    conn.execute(
                        "INSERT INTO wishlist(tmdb_id,media_type,title,provider,status) VALUES (?,?,?,?,?)",
                        (101, "tv", "愿望单剧集", "p115", "pending"),
                    )
                    task_id = conn.execute(
                        "INSERT INTO tracking_tasks(tmdb_id,media_type,title,season_number,provider,status) VALUES (?,?,?,?,?,?)",
                        (202, "tv", "追更剧集", 1, "p115", "active"),
                    ).lastrowid
                    conn.execute(
                        "INSERT INTO tracking_episodes(task_id,season_number,episode_number,title,status) VALUES (?,?,?,?,?)",
                        (task_id, 1, 3, "第 3 集", "saved"),
                    )
                backup = export_config()
                with db() as conn:
                    conn.execute("DELETE FROM tracking_episodes")
                    conn.execute("DELETE FROM tracking_tasks")
                    conn.execute("DELETE FROM wishlist")

                import_config(
                    ConfigImport(
                        format=CONFIG_EXPORT_FORMAT,
                        settings={"TMDB_API_KEY": "backup-key"},
                        task_data=backup["task_data"],
                    )
                )

                with db() as conn:
                    self.assertEqual("愿望单剧集", conn.execute("SELECT title FROM wishlist").fetchone()["title"])
                    task = conn.execute("SELECT id,title FROM tracking_tasks").fetchone()
                    self.assertEqual("追更剧集", task["title"])
                    episode = conn.execute(
                        "SELECT task_id,episode_number,status FROM tracking_episodes"
                    ).fetchone()
                    self.assertEqual(task["id"], episode["task_id"])
                    self.assertEqual((3, "saved"), (episode["episode_number"], episode["status"]))
                get_settings.cache_clear()

    def test_p115_directory_browse_does_not_fall_back_to_legacy_openlist_path(self):
        settings = SimpleNamespace(
            p115_auth_mode="open",
            openlist_url="https://openlist.internal",
            openlist_token="token",
            p115_root_path="/媒体库",
            openlist_p115_library_path="/115/媒体库",
        )
        with (
            patch("app.api.config.get_settings", return_value=settings),
            patch("app.api.config.P115Client") as p115_client,
            patch("app.api.config.OpenListClient") as openlist_client,
        ):
            p115_client.return_value.directory_id.side_effect = P115Error("TLS EOF")
            openlist_client.return_value.list_directories.return_value = [{"name": "剧集", "is_dir": True}]

            with self.assertRaises(HTTPException) as caught:
                browse_provider_path(ProviderBrowseRequest(provider="p115", path="/媒体库/下载文件夹"))

        self.assertEqual(502, caught.exception.status_code)
        self.assertIn("TLS EOF", str(caught.exception.detail))
        openlist_client.assert_not_called()

    def test_native_quark_directory_can_be_selected_for_strm(self):
        directory = SimpleNamespace(name="电视剧", is_dir=True)
        with patch("app.api.config.QuarkClient") as client:
            client.return_value.directory_id.return_value = "root-id"
            client.return_value.list_directory.return_value = (directory,)
            result = browse_provider_path(ProviderBrowseRequest(provider="quark", path="/媒体库"))
        self.assertEqual("/媒体库", result["path"])
        self.assertEqual([{"name": "电视剧", "is_dir": True}], result["directories"])

    def test_native_p115_connection_test_rejects_open_only_credentials(self):
        settings = SimpleNamespace(
            p115_cookie="cookie-present",
            p115_auth_mode="open",
            p115_open_access_token="access",
            p115_open_refresh_token="refresh",
        )
        with patch("app.api.config.get_settings", return_value=settings):
            with self.assertRaises(HTTPException) as caught:
                run_p115_connection_test()

        self.assertEqual(422, caught.exception.status_code)
        self.assertIn("Cookie", str(caught.exception.detail))

    def test_p115_connection_test_reports_cookie_when_legacy_open_mode_remains(self):
        settings = SimpleNamespace(
            p115_cookie="UID=1_A1_1; CID=abc; SEID=secret",
            p115_auth_mode="open",
            p115_open_access_token="legacy-access",
            p115_open_refresh_token="legacy-refresh",
        )
        with (
            patch("app.api.config.get_settings", return_value=settings),
            patch("app.api.config.P115Client") as p115_client,
        ):
            p115_client.return_value.list_directory.return_value = ()
            p115_client.return_value.test_cloud_download_capability.return_value = {"state": True}
            result = run_p115_connection_test()

        self.assertTrue(result["ok"])
        self.assertEqual("115 Cookie、目录读取与离线下载权限正常", result["message"])

    def test_clear_p115_open_keeps_cookie_and_switches_back_to_cookie_mode(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / ".env"
            config_path.write_text(
                "P115_COOKIE=UID=1_A1_1; CID=abc; SEID=secret\n"
                "P115_AUTH_MODE=open\n"
                "P115_OPEN_ACCESS_TOKEN=expired-access\n"
                "P115_OPEN_REFRESH_TOKEN=expired-refresh\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"MEDIA_CONFIG_PATH": str(config_path)}, clear=False):
                result = clear_p115_open()

            self.assertTrue(result["ok"])
            self.assertTrue(result["has_p115_cookie"])
            saved = config_path.read_text(encoding="utf-8")
            self.assertIn("P115_COOKIE=UID=1_A1_1; CID=abc; SEID=secret", saved)
            self.assertIn("P115_AUTH_MODE=cookie", saved)
            self.assertNotIn("P115_OPEN_ACCESS_TOKEN", saved)
            self.assertNotIn("P115_OPEN_REFRESH_TOKEN", saved)

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
