import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.providers.cloud_download_organizer import RemoteEntry
from app.services.strm_reconciler import StrmReconcileResult
from app.services.targeted_strm import (
    TargetedStrmError,
    index_and_reconcile_targeted_path,
    index_and_reconcile_targeted_strm,
    map_external_media_path,
)


class TargetedStrmTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {
            "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
            "AUTH_SECRET": "test-secret",
            "P115_STRM_ENABLED": "true",
            "P115_STRM_SOURCE_ROOT": "/media",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/media/Movies"]',
            "STRM_OUTPUT_ROOT": str(Path(self.tempdir.name) / "strm"),
        }, clear=False)
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_known_provider_ids_are_registered_without_remote_directory_read(self):
        with patch("app.services.targeted_strm.organizer_provider") as adapter_factory, patch(
            "app.services.targeted_strm.reconcile_strm", return_value=StrmReconcileResult(created=1)
        ) as reconcile:
            result = index_and_reconcile_targeted_strm(
                provider="p115",
                target_path="/media/Movies/Film (2026)",
                target_files=({"file_id": "115-7", "parent_id": "folder-3", "file_name": "Film.2026.mkv", "size": 42},),
                source_transfer_id=9,
            )
        adapter_factory.assert_not_called()
        self.assertEqual(1, result.indexed)
        with db() as conn:
            row = conn.execute("SELECT file_id,relative_path,source_transfer_id FROM media_assets").fetchone()
        self.assertEqual(("115-7", "Movies/Film (2026)/Film.2026.mkv", 9), tuple(row))
        self.assertEqual(result.asset_ids, tuple(reconcile.call_args.kwargs["asset_ids"]))

    def test_path_only_event_lists_one_exact_parent_and_matches_one_name(self):
        adapter = SimpleNamespace(
            configured=lambda: True,
            directory_id=lambda path: "parent-1" if path == "/media/Movies/Film (2026)" else "",
            list_directory=lambda parent_id: (RemoteEntry("file-1", parent_id, "Film.2026.mkv", 99, False),),
        )
        with patch("app.services.targeted_strm.organizer_provider", return_value=adapter), patch(
            "app.services.targeted_strm.reconcile_strm", return_value=StrmReconcileResult(unchanged=1)
        ):
            result = index_and_reconcile_targeted_strm(
                provider="p115",
                target_path="/media/Movies/Film (2026)/Film.2026.mkv",
                target_files=({"file_name": "Film.2026.mkv", "path": "/media/Movies/Film (2026)/Film.2026.mkv"},),
            )
        self.assertEqual(1, result.indexed)

    def test_directory_event_recurses_only_the_requested_subtree(self):
        directories = {
            "season": (
                RemoteEntry("episode-1", "season", "Show.S01E01.mkv", 99, False),
                RemoteEntry("extras", "season", "Extras", 0, True),
            ),
            "extras": (RemoteEntry("feature", "extras", "featurette.mp4", 12, False),),
        }
        adapter = SimpleNamespace(
            configured=lambda: True,
            directory_id=lambda path: "season" if path == "/media/Movies/Show/Season 1" else "",
            list_directory=lambda directory_id: directories[directory_id],
        )
        with patch("app.services.targeted_strm.organizer_provider", return_value=adapter), patch(
            "app.services.targeted_strm.reconcile_strm", return_value=StrmReconcileResult(created=2)
        ) as reconcile:
            result = index_and_reconcile_targeted_path(
                provider="p115",
                target_path="/media/Movies/Show/Season 1",
            )
        self.assertEqual(2, result.indexed)
        self.assertEqual(2, len(reconcile.call_args.kwargs["asset_ids"]))
        with db() as conn:
            paths = {
                str(row["relative_path"])
                for row in conn.execute("SELECT relative_path FROM media_assets").fetchall()
            }
        self.assertEqual(
            {"Movies/Show/Season 1/Show.S01E01.mkv", "Movies/Show/Season 1/Extras/featurette.mp4"},
            paths,
        )

    def test_selected_direct_child_can_be_used_as_a_targeted_directory(self):
        adapter = SimpleNamespace(
            configured=lambda: True,
            directory_id=lambda path: "movies" if path == "/media/Movies" else "",
            list_directory=lambda directory_id: (RemoteEntry("film", directory_id, "Film.mkv", 99, False),),
        )
        with patch("app.services.targeted_strm.organizer_provider", return_value=adapter), patch(
            "app.services.targeted_strm.reconcile_strm", return_value=StrmReconcileResult(created=1)
        ):
            result = index_and_reconcile_targeted_path(provider="p115", target_path="/media/Movies")
        self.assertEqual(1, result.indexed)

    def test_outside_or_unselected_paths_fail_closed(self):
        for path in ("/media/TV/a.mkv", "/other/Movies/a.mkv", "/media/a.mkv"):
            with self.subTest(path=path), self.assertRaises(TargetedStrmError):
                index_and_reconcile_targeted_strm(
                    provider="p115",
                    target_path=path,
                    target_files=({"file_id": "x", "file_name": "a.mkv", "path": path},),
                )

    def test_mdc_external_root_mapping_preserves_relative_file_path(self):
        with patch.dict(os.environ, {"MDC_WEBHOOK_ROOT_PATH": "/mdc"}, clear=False):
            get_settings.cache_clear()
            self.assertEqual(
                "/media/Movies/Film/a.mkv",
                map_external_media_path("/mdc/Movies/Film/a.mkv", provider="p115"),
            )
            with self.assertRaises(TargetedStrmError):
                map_external_media_path("/attacker/Movies/a.mkv", provider="p115")

    def test_provider_root_source_remains_valid_for_targeted_file(self):
        adapter = SimpleNamespace(
            configured=lambda: True,
            directory_id=lambda path: "parent-1" if path == "/Movies/Film" else "",
            list_directory=lambda parent_id: (RemoteEntry("file-1", parent_id, "Film.mkv", 99, False),),
        )
        with patch.dict(os.environ, {
            "P115_STRM_SOURCE_ROOT": "/",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/Movies"]',
            "MDC_WEBHOOK_ROOT_PATH": "/mdc",
        }, clear=False), patch("app.services.targeted_strm.organizer_provider", return_value=adapter), patch(
            "app.services.targeted_strm.reconcile_strm", return_value=StrmReconcileResult(created=1)
        ):
            get_settings.cache_clear()
            self.assertEqual(
                "/Movies/Film/Film.mkv",
                map_external_media_path("/mdc/Movies/Film/Film.mkv", provider="p115"),
            )
            result = index_and_reconcile_targeted_strm(
                provider="p115",
                target_path="/Movies/Film/Film.mkv",
                target_files=({"file_name": "Film.mkv", "path": "/Movies/Film/Film.mkv"},),
            )
        self.assertEqual(1, result.indexed)


if __name__ == "__main__":
    unittest.main()
