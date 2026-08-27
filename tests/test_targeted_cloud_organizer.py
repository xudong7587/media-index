import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.core.config import get_settings
from app.providers.cloud_download_organizer import RemoteEntry
from app.services.cloud_download_organizer import run_targeted_cloud_download_organizer


class TargetedCloudOrganizerTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def environment(self):
        return patch.dict(os.environ, {
            "P115_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "true",
            "P115_ROOT_PATH": "/media",
            "P115_CLOUD_DOWNLOAD_PATH": "/media/download",
            "P115_CLOUD_DOWNLOAD_ORGANIZER_DIRECTORIES_JSON": '["/media/download/Movies"]',
            "TMDB_API_KEY": "test-key",
            "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
        }, clear=False)

    def test_exact_media_folder_lists_only_its_authorized_scope(self):
        adapter = SimpleNamespace(
            provider="p115",
            configured=lambda: True,
            directory_id=Mock(side_effect=lambda path: "scope-id" if path == "/media/download/Movies" else ""),
            list_directory=Mock(return_value=(
                RemoteEntry("film-id", "scope-id", "Film.2026", is_dir=True),
                RemoteEntry("sibling-id", "scope-id", "Other.2025", is_dir=True),
            )),
        )
        with self.environment(), patch("app.services.cloud_download_organizer._provider_adapter", return_value=adapter), patch("app.services.cloud_download_organizer.TmdbClient") as tmdb, patch("app.services.cloud_download_organizer._process_media_folder", return_value="organized") as process:
            get_settings.cache_clear()
            tmdb.return_value.configured.return_value = True
            result = run_targeted_cloud_download_organizer("p115", "/media/download/Movies/Film.2026")
        self.assertTrue(result["accepted"])
        adapter.directory_id.assert_called_once_with("/media/download/Movies")
        adapter.list_directory.assert_called_once_with("scope-id")
        self.assertEqual("film-id", process.call_args.args[3].file_id)
        self.assertTrue(process.call_args.kwargs["trusted_complete"])

    def test_disabled_provider_does_not_touch_provider(self):
        with patch.dict(os.environ, {"P115_CLOUD_DOWNLOAD_ORGANIZER_ENABLED": "false"}, clear=False), patch("app.services.cloud_download_organizer._provider_adapter") as adapter:
            get_settings.cache_clear()
            result = run_targeted_cloud_download_organizer("p115", "/media/download/Movies/Film")
        self.assertEqual("disabled", result["reason"])
        adapter.assert_not_called()

    def test_event_outside_selected_scope_is_rejected_without_listing(self):
        with self.environment(), patch("app.services.cloud_download_organizer._provider_adapter") as adapter:
            get_settings.cache_clear()
            result = run_targeted_cloud_download_organizer("p115", "/media/download/TV/Film")
        self.assertFalse(result["accepted"])
        self.assertEqual("outside_selected_scope", result["reason"])
        adapter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
