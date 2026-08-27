import unittest

from app.core.config import Settings


class CloudDownloadOrganizerSettingsTests(unittest.TestCase):
    def test_missing_trigger_field_keeps_v0618_event_default(self):
        settings = Settings()

        self.assertEqual(("event",), settings.cloud_download_organizer_triggers())
        self.assertTrue(settings.cloud_download_organizer_trigger_enabled("event"))
        self.assertFalse(settings.cloud_download_organizer_trigger_enabled("scheduled"))

    def test_trigger_list_accepts_event_and_scheduled_once(self):
        settings = Settings(
            cloud_download_organizer_triggers_json='["event","scheduled","event","unknown"]'
        )

        self.assertEqual(("event", "scheduled"), settings.cloud_download_organizer_triggers())

    def test_invalid_trigger_encoding_fails_back_to_event(self):
        settings = Settings(cloud_download_organizer_triggers_json="invalid")

        self.assertEqual(("event",), settings.cloud_download_organizer_triggers())

    def test_legacy_directory_list_infers_selected_scope(self):
        settings = Settings(
            p115_cloud_download_organizer_scope_mode="",
            p115_cloud_download_organizer_directories_json='["/cloud/01电影"]',
        )

        self.assertEqual("selected", settings.provider_cloud_download_organizer_scope_mode("p115"))

    def test_disabled_provider_without_legacy_selection_defaults_to_all_scope(self):
        settings = Settings(
            cloud_download_organizer_enabled=False,
            p115_cloud_download_organizer_scope_mode="",
            p115_cloud_download_organizer_directories_json="[]",
        )

        self.assertEqual("all", settings.provider_cloud_download_organizer_scope_mode("p115"))

    def test_enabled_legacy_provider_without_scope_remains_fail_closed(self):
        settings = Settings(
            p115_cloud_download_organizer_enabled=True,
            p115_cloud_download_organizer_scope_mode="",
            p115_cloud_download_organizer_directories_json="[]",
        )

        self.assertEqual("selected", settings.provider_cloud_download_organizer_scope_mode("p115"))
        self.assertFalse(settings.provider_cloud_download_organizer_enabled("p115"))

    def test_explicit_all_scope_can_support_legacy_aggregate_switch(self):
        settings = Settings(
            cloud_download_organizer_enabled=True,
            p115_cloud_download_organizer_scope_mode="all",
        )

        self.assertTrue(settings.provider_cloud_download_organizer_enabled("p115"))


if __name__ == "__main__":
    unittest.main()
