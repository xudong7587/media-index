import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services.media_assets import AssetInput, mark_asset_deleted, register_asset
from app.services.strm_reconciler import list_strm_entries, reconcile_strm


class StrmReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.output = Path(self.tempdir.name) / "strm"
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db")})
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def _asset(self, file_id="file-1", name="Movie.mkv", sha1="A" * 40):
        return register_asset(AssetInput(provider="p115", file_id=file_id, name=name, size=100, sha1=sha1, status="ready"))

    def test_full_reconcile_creates_then_atomically_replaces_owned_strm(self):
        self._asset()
        first = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000")
        target = self.output / "Movie.strm"
        initial_content = target.read_text(encoding="utf-8")

        self._asset(sha1="B" * 40)
        second = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000")

        self.assertEqual((1, 0, 0), (first.created, first.replaced, first.conflicts))
        self.assertEqual((0, 1, 0), (second.created, second.replaced, second.conflicts))
        self.assertIn("/api/play/", initial_content)
        self.assertNotIn("Cookie", initial_content)
        self.assertNotEqual(initial_content, target.read_text(encoding="utf-8"))
        self.assertEqual("ready", list_strm_entries()[0]["status"])

    def test_reconcile_derives_the_dedicated_302_port_from_emby_address(self):
        self._asset()
        with patch.dict(os.environ, {
            "EMBY_BASE_URL": "http://192.168.11.111:8096",
            "EMBY_PROXY_PORT": "8097",
        }, clear=False):
            get_settings.cache_clear()
            reconcile_strm(output_root=str(self.output))

        content = (self.output / "Movie.strm").read_text(encoding="utf-8")
        self.assertIn("http://192.168.11.111:8097/api/play/", content)

    def test_reconcile_uses_saved_public_playback_address_when_job_omits_override(self):
        self._asset()
        with patch.dict(os.environ, {
            "STRM_PLAYBACK_BASE_URL": "https://tvb302.example.com:666",
            "EMBY_BASE_URL": "http://192.168.11.111:8096",
            "EMBY_PROXY_PORT": "8097",
        }, clear=False):
            get_settings.cache_clear()
            reconcile_strm(output_root=str(self.output), playback_base_url=None)

        content = (self.output / "Movie.strm").read_text(encoding="utf-8")
        self.assertIn("https://tvb302.example.com:666/api/play/", content)

    def test_reconcile_filters_non_video_and_removes_only_owned_entry_after_asset_deleted(self):
        video = self._asset()
        self._asset(file_id="sample", name="Movie.sample.mkv")
        generated = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000")
        (self.output / "unmanaged.strm").write_text("do not touch\n", encoding="utf-8")
        mark_asset_deleted(video["id"])

        removed = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000")

        self.assertEqual(1, generated.filtered)
        self.assertEqual(1, removed.removed)
        self.assertFalse((self.output / "Movie.strm").exists())
        self.assertTrue((self.output / "unmanaged.strm").exists())

    def test_same_target_path_for_two_assets_becomes_review_conflict_instead_of_overwrite(self):
        self._asset(file_id="first")
        second = self._asset(file_id="second")

        result = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000")

        self.assertEqual(1, result.created)
        self.assertEqual(1, result.conflicts)
        from app.services.media_assets import get_asset
        self.assertEqual("needs_review", get_asset(second["id"])["status"])

    def test_same_filename_in_different_media_directories_keeps_both_strm_files(self):
        register_asset(AssetInput(provider="p115", file_id="show-a", name="Episode 01.mkv", relative_path="Show A/Season 1/Episode 01.mkv", size=100, status="ready"))
        register_asset(AssetInput(provider="p115", file_id="show-b", name="Episode 01.mkv", relative_path="Show B/Season 1/Episode 01.mkv", size=100, status="ready"))

        result = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000", provider="p115")

        self.assertEqual(2, result.created)
        self.assertEqual(0, result.conflicts)
        self.assertTrue((self.output / "Show A" / "Season 1" / "Episode 01.strm").is_file())
        self.assertTrue((self.output / "Show B" / "Season 1" / "Episode 01.strm").is_file())

    def test_provider_scoped_reconcile_does_not_remove_other_provider_entry(self):
        p115 = self._asset(file_id="p115-file", name="P115 Movie.mkv")
        quark = register_asset(AssetInput(provider="quark", file_id="quark-file", name="Quark Movie.mkv", size=200, sha1="C" * 40, status="ready"))
        reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000")
        mark_asset_deleted(p115["id"])

        result = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000", provider="p115")

        self.assertEqual(1, result.removed)
        self.assertFalse((self.output / "P115 Movie.strm").exists())
        self.assertTrue((self.output / "Quark Movie.strm").exists())
        quark_entry = next(item for item in list_strm_entries() if item["asset_id"] == quark["id"])
        self.assertEqual("ready", quark_entry["status"])

    def test_legacy_scrape_setting_does_not_write_or_delete_sidecar_files(self):
        with db() as conn:
            conn.execute(
                "INSERT INTO media(tmdb_id,media_type,title,year,overview) VALUES(?,?,?,?,?)",
                (42, "movie", "Global Movie", "2026", "A verified plot"),
            )
        asset = register_asset(AssetInput(provider="p115", file_id="scrape", name="Global.Movie.2026.mkv", size=100, status="ready"))
        with patch.dict(os.environ, {"P115_STRM_SCRAPE_ENABLED": "true"}):
            get_settings.cache_clear()
            result = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000", provider="p115")

        nfo = self.output / "Global.Movie.2026.nfo"
        poster = self.output / "Global.Movie.2026-poster.jpg"
        fanart = self.output / "Global.Movie.2026-fanart.jpg"
        self.assertEqual(0, result.scraped)
        self.assertFalse(nfo.exists())

        nfo.write_text("managed by Emby", encoding="utf-8")
        poster.write_bytes(b"emby poster")
        fanart.write_bytes(b"emby fanart")
        mark_asset_deleted(asset["id"])
        reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000", provider="p115")

        self.assertTrue(nfo.exists())
        self.assertTrue(poster.exists())
        self.assertTrue(fanart.exists())

    def test_configured_file_range_controls_extensions_tokens_and_minimum_size(self):
        self._asset(file_id="small", name="Small.mp4", sha1="S" * 40)
        self._asset(file_id="keep", name="Keep.webm", sha1="K" * 40)
        self._asset(file_id="skip", name="Keep.preview.webm", sha1="P" * 40)
        with patch.dict(os.environ, {
            "STRM_VIDEO_EXTENSIONS_JSON": '[".webm"]',
            "STRM_EXCLUDED_NAME_TOKENS_JSON": '["preview"]',
            "STRM_MIN_FILE_SIZE_MB": "0",
        }):
            get_settings.cache_clear()
            result = reconcile_strm(output_root=str(self.output), playback_base_url="http://127.0.0.1:8000", provider="p115")

        self.assertEqual(1, result.created)
        self.assertEqual(2, result.filtered)
        self.assertTrue((self.output / "Keep.strm").exists())


if __name__ == "__main__":
    unittest.main()
