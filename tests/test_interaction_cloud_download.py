import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import get_settings
from app.clients.quark import QuarkError
from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget, ProviderExecutionResult, RenamePair
from app.services.cloud_download_targets import list_cloud_download_targets
from app.services.paths import (
    build_cloud_download_staging_path,
    cloud_download_scope_from_child,
    is_cloud_download_staging_path,
)
from app.services.transfer_service_v2 import execute_transfer_v2


class InteractionCloudDownloadTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def test_server_rebuilds_only_a_configured_direct_child_path(self):
        with patch.dict(
            os.environ,
            {
                "P115_CLOUD_DOWNLOAD_PATH": "/独立云下载",
                "SEASON_SUBDIRECTORY_ENABLED": "true",
            },
        ):
            get_settings.cache_clear()
            self.assertEqual(
                "/独立云下载/03电视剧",
                cloud_download_scope_from_child("p115", "03电视剧"),
            )
            self.assertEqual(
                "/独立云下载/03电视剧/测试剧 (2026)/Season 2",
                build_cloud_download_staging_path("p115", "03电视剧", "tv", "测试剧", "2026", 2),
            )
            for child in ("", "..", "../03电视剧", "03电视剧/剧名", "03电影\\剧名"):
                with self.subTest(child=child):
                    self.assertEqual("", cloud_download_scope_from_child("p115", child))
            self.assertFalse(
                is_cloud_download_staging_path(
                    "p115",
                    "/独立云下载/其他/测试剧",
                    "03电视剧",
                )
            )

    def test_directory_choices_come_from_real_provider_direct_children(self):
        client = SimpleNamespace(
            directory_id=lambda path: "root-id" if path == "/独立云下载" else "",
            list_directory_complete=lambda directory_id: (
                SimpleNamespace(name="03电视剧", is_dir=True),
                SimpleNamespace(name="01电影", is_dir=True),
                SimpleNamespace(name="readme.txt", is_dir=False),
                SimpleNamespace(name="../越界", is_dir=True),
            ),
        )
        with (
            patch.dict(os.environ, {"QUARK_CLOUD_DOWNLOAD_PATH": "/独立云下载"}),
            patch("app.services.cloud_download_targets.QuarkClient", return_value=client),
        ):
            get_settings.cache_clear()
            targets = list_cloud_download_targets("quark")

        self.assertEqual(["01电影", "03电视剧"], [item.child_name for item in targets])
        self.assertEqual(
            ["/独立云下载/01电影", "/独立云下载/03电视剧"],
            [item.path for item in targets],
        )

    def test_quark_directory_read_retries_once_instead_of_returning_false_empty(self):
        client = SimpleNamespace(
            directory_id=unittest.mock.Mock(side_effect=[QuarkError("夸克连接失败（URLError）"), "root-id"]),
            list_directory_complete=unittest.mock.Mock(
                return_value=(SimpleNamespace(name="03电视剧", is_dir=True),)
            ),
        )
        with (
            patch.dict(os.environ, {"QUARK_CLOUD_DOWNLOAD_PATH": "/独立云下载"}),
            patch("app.services.cloud_download_targets.QuarkClient", return_value=client),
            patch("app.services.cloud_download_targets.time.sleep") as sleep,
        ):
            get_settings.cache_clear()
            targets = list_cloud_download_targets("quark")

        self.assertEqual(["03电视剧"], [item.child_name for item in targets])
        self.assertEqual(2, client.directory_id.call_count)
        sleep.assert_called_once_with(0.75)

    def test_quark_directory_read_reports_persistent_connection_failure(self):
        client = SimpleNamespace(
            directory_id=unittest.mock.Mock(side_effect=QuarkError("夸克连接失败（URLError）")),
        )
        with (
            patch.dict(os.environ, {"QUARK_CLOUD_DOWNLOAD_PATH": "/独立云下载"}),
            patch("app.services.cloud_download_targets.QuarkClient", return_value=client),
            patch("app.services.cloud_download_targets.time.sleep"),
        ):
            get_settings.cache_clear()
            with self.assertRaisesRegex(RuntimeError, "已重试 1 次"):
                list_cloud_download_targets("quark")

    def test_directory_choices_filter_library_overlap_but_allow_independent_root(self):
        client = SimpleNamespace(
            directory_id=lambda _path: "root-id",
            list_directory_complete=lambda _directory_id: (
                SimpleNamespace(name="Media", is_dir=True),
                SimpleNamespace(name="Movies", is_dir=True),
            ),
        )
        root_settings = SimpleNamespace(
            provider_cloud_download_path=lambda _provider: "/",
            provider_save_root=lambda _provider: "/Media",
        )
        independent_settings = SimpleNamespace(
            provider_cloud_download_path=lambda _provider: "/Downloads",
            provider_save_root=lambda _provider: "/Media",
        )
        with (
            patch("app.services.cloud_download_targets.QuarkClient", return_value=client),
            patch("app.services.cloud_download_targets.get_settings", return_value=root_settings),
        ):
            root_targets = list_cloud_download_targets("quark")
        with (
            patch("app.services.cloud_download_targets.QuarkClient", return_value=client),
            patch("app.services.cloud_download_targets.get_settings", return_value=independent_settings),
        ):
            independent_targets = list_cloud_download_targets("quark")

        self.assertEqual(["Movies"], [item.child_name for item in root_targets])
        self.assertEqual(["Media", "Movies"], [item.child_name for item in independent_targets])

    def test_standard_tmdb_transfer_marks_a_server_derived_staging_plan(self):
        target = MediaTarget(7, "movie", "测试电影", series_year="2026", category="movie")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/test",
            rename_pairs=(RenamePair("火星文.mkv", "", "测试电影.2026.mkv"),),
        )

        class Provider:
            def __init__(self):
                self.plan = None

            def execute(self, plan):
                self.plan = plan
                return ProviderExecutionResult(
                    True,
                    "provider_completed",
                    "done",
                    executed_items=1,
                    confirmed=True,
                )

        provider = Provider()
        with (
            patch.dict(os.environ, {"QUARK_CLOUD_DOWNLOAD_PATH": "/独立云下载"}),
            patch("app.services.transfer_service_v2.resolve_provider_key", return_value="quark"),
            patch("app.services.transfer_service_v2.get_transfer_provider", return_value=provider),
            patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
            patch("app.services.transfer_service_v2.resolve_movie_source", return_value=resolution),
        ):
            get_settings.cache_clear()
            result = execute_transfer_v2(
                7,
                "movie",
                "cloud",
                provider="quark",
                interaction_cloud_download_child="01电影",
                request_source="telegram",
            )

        self.assertTrue(result["ok"])
        self.assertEqual("/独立云下载/01电影/测试电影 (2026)", provider.plan.save_path)
        self.assertEqual("cloud_download", provider.plan.destination_scope)
        self.assertEqual("01电影", provider.plan.cloud_download_child)

    def test_tv_progress_reads_only_its_derived_media_folder(self):
        target = MediaTarget(
            8,
            "tv",
            "测试剧",
            series_year="2026",
            season_number=1,
            category="tv",
            episodes=(EpisodeTarget(1, 1, "2026-01-01"),),
        )
        seen: list[str] = []

        def progress(path, _season, **_kwargs):
            seen.append(path)
            return path, 0

        with (
            patch.dict(
                os.environ,
                {
                    "P115_CLOUD_DOWNLOAD_PATH": "/独立云下载",
                    "SEASON_SUBDIRECTORY_ENABLED": "true",
                },
            ),
            patch("app.services.transfer_service_v2.resolve_provider_key", return_value="p115"),
            patch("app.services.transfer_service_v2.get_transfer_provider", return_value=object()),
            patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
            patch("app.services.transfer_service_v2.resolve_save_path_progress", side_effect=progress),
            patch(
                "app.services.transfer_service_v2.resolve_episode_source",
                return_value=LinkResolution(False, "no_resource", "none"),
            ),
        ):
            get_settings.cache_clear()
            result = execute_transfer_v2(
                8,
                "tv",
                "cloud",
                1,
                provider="p115",
                interaction_cloud_download_child="03电视剧",
                request_source="wecom",
            )

        self.assertEqual(["/独立云下载/03电视剧/测试剧 (2026)/Season 1"], seen)
        self.assertEqual("no_resource", result["stage"])

    def test_non_interaction_cannot_request_internal_staging_override(self):
        target = MediaTarget(9, "movie", "测试", series_year="2026", category="movie")
        with (
            patch.dict(os.environ, {"QUARK_CLOUD_DOWNLOAD_PATH": "/独立云下载"}),
            patch("app.services.transfer_service_v2.resolve_provider_key", return_value="quark"),
            patch("app.services.transfer_service_v2.get_transfer_provider", return_value=object()),
            patch("app.services.transfer_service_v2.resolve_media_target", return_value=target),
        ):
            get_settings.cache_clear()
            with self.assertRaisesRegex(ValueError, "企业微信或 Telegram"):
                execute_transfer_v2(
                    9,
                    "movie",
                    "cloud",
                    provider="quark",
                    interaction_cloud_download_child="01电影",
                    request_source="web",
                )


if __name__ == "__main__":
    unittest.main()
