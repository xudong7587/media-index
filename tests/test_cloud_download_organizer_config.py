import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.config import ConfigUpdate, _update_config, status
from app.core.config import get_settings


class CloudDownloadOrganizerConfigTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env_path = Path(self.tempdir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                (
                    "TMDB_API_KEY=test-key",
                    "P115_COOKIE=UID=1_A1_1; CID=abc; SEID=secret",
                    "P115_ROOT_PATH=/媒体库",
                    "P115_CLOUD_DOWNLOAD_PATH=/媒体库/下载文件夹",
                    "P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=[]",
                    "CLOUD_DOWNLOAD_ORGANIZER_ENABLED=false",
                    "UNRELATED_LOCAL_SETTING=keep-me",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        self.environment = patch.dict(
            os.environ,
            {
                "MEDIA_CONFIG_PATH": str(self.env_path),
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "TRACKING_SCHEDULER_ENABLED": "false",
                "WISHLIST_SCHEDULER_ENABLED": "false",
                "NOTIFICATION_EXTERNAL_ENABLED": "false",
            },
            clear=False,
        )
        self.environment.start()
        get_settings.cache_clear()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def save(self, payload):
        with patch("app.api.config.stop_scheduler"), patch("app.api.config.start_scheduler"):
            return _update_config(payload)

    def test_typed_save_persists_scope_and_keeps_unrelated_existing_value(self):
        result = self.save(
            ConfigUpdate(
                cloud_download_organizer_enabled=True,
                cloud_download_organizer_mode="move",
                cloud_download_organizer_interval_minutes=7,
                cloud_download_organizer_stable_minutes=15,
                p115_cloud_download_organizer_directories=["/媒体库/下载文件夹/01电影"],
            )
        )
        saved = self.env_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn("CLOUD_DOWNLOAD_ORGANIZER_ENABLED=true", saved)
        self.assertIn("CLOUD_DOWNLOAD_ORGANIZER_MODE=move", saved)
        self.assertIn('P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=["/媒体库/下载文件夹/01电影"]', saved)
        self.assertIn("UNRELATED_LOCAL_SETTING=keep-me", saved)

    def test_enabling_requires_tmdb_and_at_least_one_scope(self):
        with self.assertRaisesRegex(HTTPException, "至少勾选"):
            self.save(ConfigUpdate(cloud_download_organizer_enabled=True))
        self.env_path.write_text(
            self.env_path.read_text(encoding="utf-8").replace("TMDB_API_KEY=test-key\n", ""),
            encoding="utf-8",
        )
        get_settings.cache_clear()
        with self.assertRaisesRegex(HTTPException, "TMDB"):
            self.save(
                ConfigUpdate(
                    cloud_download_organizer_enabled=True,
                    p115_cloud_download_organizer_directories=["/媒体库/下载文件夹/01电影"],
                )
            )

    def test_root_change_without_new_scope_disables_and_clears_stale_selection(self):
        self.env_path.write_text(
            self.env_path.read_text(encoding="utf-8")
            .replace("CLOUD_DOWNLOAD_ORGANIZER_ENABLED=false", "CLOUD_DOWNLOAD_ORGANIZER_ENABLED=true")
            .replace(
                "P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=[]",
                'P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=["/媒体库/下载文件夹/01电影"]',
            ),
            encoding="utf-8",
        )
        get_settings.cache_clear()
        self.save(ConfigUpdate(p115_cloud_download_path="/媒体库/新下载目录"))
        saved = self.env_path.read_text(encoding="utf-8")
        self.assertIn("CLOUD_DOWNLOAD_ORGANIZER_ENABLED=false", saved)
        self.assertNotIn("P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON", saved)

    def test_same_roots_round_trip_keeps_scope_and_enabled_state(self):
        self.env_path.write_text(
            self.env_path.read_text(encoding="utf-8")
            .replace("CLOUD_DOWNLOAD_ORGANIZER_ENABLED=false", "CLOUD_DOWNLOAD_ORGANIZER_ENABLED=true")
            .replace(
                "P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=[]",
                'P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=["/媒体库/下载文件夹/01电影"]',
            ),
            encoding="utf-8",
        )
        get_settings.cache_clear()
        self.save(
            ConfigUpdate(
                p115_root_path="/媒体库/",
                p115_cloud_download_path="/媒体库/下载文件夹/",
            )
        )
        saved = self.env_path.read_text(encoding="utf-8")
        self.assertIn("CLOUD_DOWNLOAD_ORGANIZER_ENABLED=true", saved)
        self.assertIn(
            'P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=["/媒体库/下载文件夹/01电影"]',
            saved,
        )

    def test_changing_unused_p115_root_does_not_disable_quark_organizer(self):
        self.env_path.write_text(
            self.env_path.read_text(encoding="utf-8")
            .replace("CLOUD_DOWNLOAD_ORGANIZER_ENABLED=false", "CLOUD_DOWNLOAD_ORGANIZER_ENABLED=true")
            + "QUARK_ROOT_PATH=/夸克媒体库\n"
            + "QUARK_CLOUD_DOWNLOAD_PATH=/夸克媒体库/下载\n"
            + 'QUARK_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=["/夸克媒体库/下载/01电影"]\n',
            encoding="utf-8",
        )
        get_settings.cache_clear()
        self.save(ConfigUpdate(p115_root_path="/新的115媒体库"))
        saved = self.env_path.read_text(encoding="utf-8")
        self.assertIn("CLOUD_DOWNLOAD_ORGANIZER_ENABLED=true", saved)
        self.assertIn(
            'QUARK_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=["/夸克媒体库/下载/01电影"]',
            saved,
        )
        self.assertIn("P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON=[]", saved)

    def test_status_normalizes_invalid_legacy_values_without_mutating_file(self):
        self.env_path.write_text(
            self.env_path.read_text(encoding="utf-8")
            + "CLOUD_DOWNLOAD_ORGANIZER_MODE=invalid\n"
            + "CLOUD_DOWNLOAD_ORGANIZER_INTERVAL_MINUTES=999999\n",
            encoding="utf-8",
        )
        get_settings.cache_clear()
        payload = status()
        self.assertEqual("copy", payload["cloud_download_organizer_mode"])
        self.assertEqual(1440, payload["cloud_download_organizer_interval_minutes"])


if __name__ == "__main__":
    unittest.main()
