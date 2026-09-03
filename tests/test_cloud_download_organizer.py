import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.config import _safe_cloud_download_organizer_directories
from app.core.config import Settings, get_settings
from app.db.database import db, init_db
from app.domain.media import EpisodeTarget, MediaTarget, SourceFile
from app.clients.quark import QuarkError
from app.providers.cloud_download_organizer import QuarkOrganizerProvider
from app.services import cloud_download_organizer as organizer
from app.services.cloud_download_organizer import (
    OrganizePlan,
    OrganizerReview,
    OrganizerStopped,
    PlannedFile,
    RemoteEntry,
    _build_plan,
    _execute_copy,
    _execute_move,
    _folder_query,
    _match_tmdb,
    _preflight_destinations,
    _stable_job,
    _trash_empty_source_folder,
)


def organizer_settings(**overrides):
    values = {
        "tmdb_api_key": "test",
        "p115_root_path": "/媒体库",
        "p115_cloud_download_path": "/媒体库/下载文件夹",
        "p115_cloud_download_organizer_directories_json": '["/媒体库/下载文件夹/01电影"]',
        "p115_staging_path": "/.media-index-staging",
        "cloud_download_organizer_mode": "copy",
        "media_folder_naming_rule": "{title} ({year})",
        "season_folder_naming_rule": "Season {season}",
        "movie_naming_rule": "{title}.{year}",
        "episode_naming_rule": "{title}.{year}.S{season:02d}E{episode:02d}",
        "db_path": "unused.db",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_quark_organizer_retries_transient_reads_once():
    client = unittest.mock.Mock()
    client.settings.quark_request_timeout_seconds = 30
    client.directory_id_complete.side_effect = [QuarkError("夸克连接失败（URLError）"), "folder-id"]
    provider = QuarkOrganizerProvider(client)

    with patch("app.providers.cloud_download_organizer.time.sleep") as sleep:
        assert provider.directory_id("/strm/download/03电视剧") == "folder-id"

    assert client.directory_id_complete.call_count == 2
    sleep.assert_called_once_with(0.75)


def test_quark_organizer_does_not_retry_mutations():
    client = unittest.mock.Mock()
    client.settings.quark_request_timeout_seconds = 30
    client.rename_file.side_effect = QuarkError("夸克连接失败（URLError）")
    provider = QuarkOrganizerProvider(client)

    with pytest.raises(QuarkError, match="URLError"):
        provider.rename([("file-id", "花开锦绣.2026.S01E03.mkv")])

    client.rename_file.assert_called_once_with("file-id", "花开锦绣.2026.S01E03.mkv")


def test_quark_organizer_reconciles_directory_created_before_timeout():
    client = unittest.mock.Mock()
    client.settings.quark_request_timeout_seconds = 30
    client.ensure_directory.side_effect = QuarkError("夸克连接失败（连接超时）")
    client.directory_id_complete.return_value = "season-folder-id"
    provider = QuarkOrganizerProvider(client)

    with patch("app.providers.cloud_download_organizer.time.sleep"):
        assert provider.ensure_directory("/strm/03电视剧/铁拳教育 (2026)/Season 1") == "season-folder-id"

    client.ensure_directory.assert_called_once()
    client.directory_id_complete.assert_called_once()


def test_quark_organizer_retries_directory_only_after_exact_absence_is_proven():
    client = unittest.mock.Mock()
    client.settings.quark_request_timeout_seconds = 30
    client.ensure_directory.side_effect = [
        QuarkError("夸克连接失败（连接超时）"),
        "season-folder-id",
    ]
    client.directory_id_complete.return_value = ""
    provider = QuarkOrganizerProvider(client)

    with patch("app.providers.cloud_download_organizer.time.sleep"):
        assert provider.ensure_directory("/strm/03电视剧/铁拳教育 (2026)/Season 1") == "season-folder-id"

    assert client.ensure_directory.call_count == 2
    client.directory_id_complete.assert_called_once()


def test_quark_organizer_reconciles_directory_after_retry_response_is_lost():
    client = unittest.mock.Mock()
    client.settings.quark_request_timeout_seconds = 30
    client.ensure_directory.side_effect = [
        QuarkError("夸克连接失败（连接超时）"),
        QuarkError("夸克连接失败（连接超时）"),
    ]
    client.directory_id_complete.side_effect = ["", "season-folder-id"]
    provider = QuarkOrganizerProvider(client)

    with patch("app.providers.cloud_download_organizer.time.sleep"):
        assert provider.ensure_directory("/strm/03电视剧/铁拳教育 (2026)/Season 1") == "season-folder-id"

    assert client.ensure_directory.call_count == 2
    assert client.directory_id_complete.call_count == 2


def test_quark_organizer_does_not_replay_directory_when_result_cannot_be_read():
    client = unittest.mock.Mock()
    client.settings.quark_request_timeout_seconds = 30
    client.ensure_directory.side_effect = QuarkError("夸克连接失败（连接超时）")
    client.directory_id_complete.side_effect = QuarkError("夸克连接失败（连接超时）")
    provider = QuarkOrganizerProvider(client)

    with patch("app.providers.cloud_download_organizer.time.sleep"):
        with pytest.raises(QuarkError, match="未重复提交"):
            provider.ensure_directory("/strm/03电视剧/铁拳教育 (2026)/Season 1")

    client.ensure_directory.assert_called_once()
    assert client.directory_id_complete.call_count == 2


class FakeTmdb:
    def __init__(self, results=None):
        self.results = results or [{"tmdb_id": 101, "media_type": "movie", "title": "流浪地球2", "year": "2023"}]

    def configured(self):
        return True

    def search(self, _query, _media_type="all", _page=1):
        return {"results": list(self.results)}

    def details(self, media_type, _tmdb_id):
        return {
            "title": "流浪地球2" if media_type == "movie" else "测试剧",
            "original_title": "The Wandering Earth II" if media_type == "movie" else "Test Show",
            "aliases": [],
            "year": "2023" if media_type == "movie" else "2024",
            "poster_url": "poster",
            "overview": "",
            "release_date": "2023-01-22" if media_type == "movie" else "2024-01-01",
            "status": "Released",
        }

    def season(self, _tmdb_id, season_number):
        return {
            "air_date": "2024-01-01",
            "episodes": [
                {
                    "episode_number": episode,
                    "name": f"第 {episode} 集",
                    "air_date": f"2024-01-{episode:02d}",
                }
                for episode in (1, 2)
            ],
        }


class RecordingAdapter:
    provider = "p115"
    request_timeout_seconds = 1

    def __init__(self):
        self.calls = []
        self.directories = {
            "scope": [RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True)],
        }
        self.path_ids = {
            "/媒体库/下载文件夹/01电影": "scope",
        }
        self.source_tree = ()

    def configured(self):
        return True

    def directory_id(self, path):
        self.calls.append(("directory_id", path))
        return self.path_ids.get(path, "")

    def ensure_directory(self, path):
        self.calls.append(("ensure", path))
        value = self.path_ids.setdefault(path, f"dir-{len(self.path_ids) + 1}")
        self.directories.setdefault(value, [])
        return value

    def list_directory(self, directory_id):
        self.calls.append(("list", directory_id))
        if directory_id == "source-folder":
            return tuple(self.source_tree)
        return tuple(self.directories.get(directory_id, ()))

    def rename(self, pairs):
        self.calls.append(("rename", tuple(pairs)))
        replacements = dict(pairs)
        self.source_tree = tuple(
            RemoteEntry(
                entry.file_id,
                entry.parent_id,
                replacements.get(entry.file_id, entry.name),
                entry.size,
                entry.is_dir,
                entry.relative_path,
            )
            for entry in self.source_tree
        )
        for directory in self.directories.values():
            for index, entry in enumerate(directory):
                replacement = next((name for file_id, name in pairs if file_id == entry.file_id), "")
                if replacement:
                    directory[index] = RemoteEntry(
                        entry.file_id,
                        entry.parent_id,
                        replacement,
                        entry.size,
                        entry.is_dir,
                        entry.relative_path,
                    )

    def move(self, file_ids, destination_id):
        self.calls.append(("move", tuple(file_ids), destination_id))
        destination = self.directories.setdefault(destination_id, [])
        known = {
            "source-video": RemoteEntry("source-video", "source-folder", "流浪地球2.2023.mkv", 8_000_000_000),
            "copy-video": RemoteEntry("copy-video", "stage", "流浪地球2.2023.mkv", 8_000_000_000),
        }
        for file_id in file_ids:
            matched_source = next((item for item in self.source_tree if item.file_id == file_id), None)
            if matched_source:
                known[file_id] = matched_source
            for directory in self.directories.values():
                matched = next((item for item in directory if item.file_id == file_id), None)
                if matched:
                    known[file_id] = matched
                    directory[:] = [item for item in directory if item.file_id != file_id]
            source = known.get(file_id)
            if source:
                destination.append(
                    RemoteEntry(source.file_id, destination_id, source.name, source.size, source.is_dir, source.relative_path)
                )
        self.source_tree = tuple(item for item in self.source_tree if item.file_id not in set(file_ids))

    def copy(self, file_ids, destination_id):
        self.calls.append(("copy", tuple(file_ids), destination_id))
        self.directories.setdefault(destination_id, []).append(
            RemoteEntry("copy-video", destination_id, "流浪地球2.2023.2160p.mkv", 8_000_000_000)
        )

    def trash(self, file_id):
        self.calls.append(("trash", file_id))
        self.source_tree = tuple(item for item in self.source_tree if item.file_id != file_id)
        for directory in self.directories.values():
            directory[:] = [item for item in directory if item.file_id != file_id]


class CloudDownloadOrganizerTests(unittest.TestCase):
    def test_defaults_are_upgrade_safe_and_disabled(self):
        settings = Settings(_env_file=None)
        self.assertFalse(settings.cloud_download_organizer_enabled)
        self.assertEqual("copy", settings.cloud_download_organizer_mode)
        self.assertEqual((), settings.provider_cloud_download_organizer_directories("p115"))

    def test_scope_validation_allows_only_direct_children_with_safe_target(self):
        self.assertEqual(
            ["/媒体库/下载文件夹/01电影"],
            _safe_cloud_download_organizer_directories(
                ["/媒体库/下载文件夹/01电影"],
                "/媒体库/下载文件夹",
                "/媒体库",
            ),
        )
        for invalid in (
            ["/媒体库/下载文件夹/01电影/子目录"],
            ["/别处/01电影"],
            ["/媒体库/下载文件夹/../01电影"],
            ["相对路径/01电影"],
        ):
            with self.assertRaises(HTTPException):
                _safe_cloud_download_organizer_directories(invalid, "/媒体库/下载文件夹", "/媒体库")
        with self.assertRaises(HTTPException):
            _safe_cloud_download_organizer_directories(
                ["/媒体库/下载文件夹/下载文件夹"],
                "/媒体库/下载文件夹",
                "/媒体库",
            )

    def test_scope_validation_allows_provider_root_without_scanning_library_branch(self):
        self.assertEqual(
            ["/Downloads"],
            _safe_cloud_download_organizer_directories(["/Downloads"], "/", "/Media"),
        )
        with self.assertRaisesRegex(HTTPException, "不能重叠"):
            _safe_cloud_download_organizer_directories(["/Media"], "/", "/Media")

        settings = organizer_settings(
            p115_root_path="/Media",
            p115_cloud_download_path="/",
            p115_cloud_download_organizer_scope_mode="all",
            p115_cloud_download_organizer_directories_json="[]",
        )
        adapter = SimpleNamespace(
            directory_id=lambda path: "root" if path == "/" else "",
            list_directory=lambda _directory_id: (
                RemoteEntry("library", "root", "Media", is_dir=True),
                RemoteEntry("downloads", "root", "Downloads", is_dir=True),
                RemoteEntry("tv", "root", "TV", is_dir=True),
                RemoteEntry("file", "root", "readme.txt"),
            ),
        )
        self.assertEqual(
            ("/Downloads", "/TV"),
            organizer._scheduled_scopes(settings, adapter, "p115", ()),
        )

    def test_folder_query_removes_release_noise_but_preserves_title(self):
        self.assertEqual(("流浪地球2", "2023"), _folder_query("流浪地球2.2023.2160p.WEB-DL.HDR"))
        self.assertEqual(("测试电影", "2026"), _folder_query("测试电影 (2026)"))
        self.assertEqual(("Spider-Man", "2002"), _folder_query("Spider-Man.2002.1080p"))
        self.assertEqual(("Spider-Man", "2002"), _folder_query("Spider-Man.2002.1080p-GROUP"))

    def test_direct_files_are_grouped_by_safe_movie_or_episode_identity(self):
        movie_entries = (
            RemoteEntry("movie", "scope", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
            RemoteEntry("subtitle", "scope", "流浪地球2.2023.2160p.zh-CN.ass", 100_000),
        )
        movie_groups = organizer._loose_media_groups(movie_entries, "movie")
        self.assertEqual(1, len(movie_groups))
        self.assertEqual({"movie", "subtitle"}, {item.file_id for item in movie_groups[0][2]})

        episode_entries = tuple(
            RemoteEntry(f"e{episode}", "scope", f"测试剧.2024.S01E{episode:02d}.mkv", 2_000_000_000)
            for episode in (1, 2)
        )
        episode_groups = organizer._loose_media_groups(episode_entries, "tv")
        self.assertEqual(1, len(episode_groups))
        self.assertEqual({"e1", "e2"}, {item.file_id for item in episode_groups[0][2]})

    def test_direct_episode_group_is_stable_across_provider_order_and_ignores_air_date_year(self):
        entries = (
            RemoteEntry("s2", "scope", "测试剧.S02E01.mkv", 2_000_000_000),
            RemoteEntry("s1", "scope", "测试剧.S01E01.mkv", 2_000_000_000),
        )
        forward = organizer._loose_media_groups(entries, "tv")[0]
        reverse = organizer._loose_media_groups(tuple(reversed(entries)), "tv")[0]
        self.assertEqual(forward[:2], reverse[:2])
        self.assertEqual("测试剧.S01", forward[1])
        self.assertEqual(
            organizer._inventory_fingerprint(RemoteEntry("scope", "", forward[1], is_dir=True), forward[2]),
            organizer._inventory_fingerprint(RemoteEntry("scope", "", reverse[1], is_dir=True), reverse[2]),
        )

        dated = RemoteEntry("dated", "scope", "奔跑吧.2026-05-01.S14E01.mkv", 2_000_000_000)
        dated_group = organizer._loose_media_groups((dated,), "variety")[0]
        self.assertEqual("奔跑吧.S14", dated_group[1])
        self.assertEqual("episodic:奔跑吧:", dated_group[0])

    def test_standard_anime_release_group_and_dash_episode_are_supported(self):
        class AnimeTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{
                    "tmdb_id": 209867,
                    "media_type": "tv",
                    "title": "葬送的芙莉莲",
                    "year": "2023",
                }])

            def details(self, _media_type, _tmdb_id):
                return {
                    "title": "葬送的芙莉莲",
                    "original_title": "Frieren: Beyond Journey's End",
                    "aliases": [],
                    "year": "2023",
                    "release_date": "2023-09-29",
                    "genres": ["动画"],
                    "seasons": [{"season_number": 1}],
                }

            def season(self, _tmdb_id, _season_number):
                return {
                    "air_date": "2023-09-29",
                    "episodes": [
                        {"episode_number": number, "name": f"第 {number} 集", "air_date": ""}
                        for number in (1, 2)
                    ],
                }

        entries = tuple(
            RemoteEntry(
                f"episode-{number}",
                "source-folder",
                f"[ANi] 葬送的芙莉莲 - {number:02d} [1080p].mkv",
                2_000_000_000,
                False,
                f"[ANi] 葬送的芙莉莲 - {number:02d} [1080p].mkv",
            )
            for number in (1, 2)
        )
        groups = organizer._loose_media_groups(entries, "anime")
        self.assertEqual(1, len(groups))
        self.assertEqual("葬送的芙莉莲", groups[0][1])

        plan = _build_plan(
            organizer_settings(),
            "p115",
            RemoteEntry("source-folder", "scope", "葬送的芙莉莲", is_dir=True),
            "/媒体库/下载文件夹/02动漫/葬送的芙莉莲",
            "/媒体库/02动漫",
            "anime",
            entries,
            AnimeTmdb(),
        )
        self.assertEqual(2, len(plan.files))
        self.assertTrue(all(item.destination_path.endswith("/Season 1") for item in plan.files))

    def test_anime_scope_rejects_same_name_live_action_tmdb_result(self):
        class LiveActionTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{
                    "tmdb_id": 77,
                    "media_type": "tv",
                    "title": "同名作品",
                    "year": "2024",
                }])

            def details(self, _media_type, _tmdb_id):
                return {
                    "title": "同名作品",
                    "year": "2024",
                    "genres": ["剧情"],
                    "seasons": [{"season_number": 1}],
                }

        with self.assertRaisesRegex(OrganizerReview, "TMDB 未找到高置信度"):
            _build_plan(
                organizer_settings(),
                "p115",
                RemoteEntry("source-folder", "scope", "同名作品.2024", is_dir=True),
                "/媒体库/下载文件夹/02动漫/同名作品.2024",
                "/媒体库/02动漫",
                "anime",
                (
                    RemoteEntry(
                        "episode-1",
                        "source-folder",
                        "同名作品 - 01.mkv",
                        2_000_000_000,
                        False,
                        "同名作品 - 01.mkv",
                    ),
                ),
                LiveActionTmdb(),
            )

    def test_unknown_direct_cd_marker_never_queries_tmdb(self):
        class NoSearchTmdb(FakeTmdb):
            def search(self, *_args, **_kwargs):
                raise AssertionError("TMDB search must not run for a marker-only direct file")

        entry = RemoteEntry("cd1", "scope", "CD1.mkv", 8_000_000_000, False, "CD1.mkv")
        group_key, display_name, _entries = organizer._loose_media_groups((entry,), "movie")[0]
        self.assertTrue(group_key.startswith("unknown:"))
        with self.assertRaisesRegex(OrganizerReview, "缺少.*文本标题"):
            _build_plan(
                organizer_settings(),
                "p115",
                RemoteEntry("scope", "", display_name, is_dir=True),
                f"/媒体库/下载文件夹/01电影/{display_name}",
                "/媒体库/01电影",
                "movie",
                (entry,),
                NoSearchTmdb(),
                source_scope_path="/媒体库/下载文件夹/01电影",
                loose_group_key=group_key,
            )

    def test_tmdb_requires_unique_high_confidence_result(self):
        tmdb_id, media_type = _match_tmdb(FakeTmdb(), "流浪地球2", "2023", "movie", None)
        self.assertEqual((101, "movie"), (tmdb_id, media_type))
        ambiguous = FakeTmdb([
            {"tmdb_id": 1, "media_type": "movie", "title": "同名电影", "year": "2024"},
            {"tmdb_id": 2, "media_type": "movie", "title": "同名电影", "year": "2024"},
        ])
        with self.assertRaisesRegex(OrganizerReview, "多个接近结果"):
            _match_tmdb(ambiguous, "同名电影", "2024", "movie", None)

    def test_confirmed_regular_series_uses_explicit_episode_numbers_when_tmdb_has_no_match(self):
        class NoMatchTmdb(FakeTmdb):
            def search(self, *_args, **_kwargs):
                return {"results": []}

            def details(self, *_args, **_kwargs):
                raise AssertionError("confirmed regular series must not require TMDB details")

            def season(self, *_args, **_kwargs):
                raise AssertionError("confirmed regular series must not require TMDB season")

        entries = (
            RemoteEntry("episode-1", "source", "完全不规范.S02E01.高码率.mkv", 2_000_000_000, False, "完全不规范.S02E01.高码率.mkv"),
            RemoteEntry("episode-2", "source", "02-4K.另一个发布组.mkv", 2_000_000_000, False, "02-4K.另一个发布组.mkv"),
        )
        plan = _build_plan(
            organizer_settings(),
            "quark",
            RemoteEntry("source", "scope", "网盘原始标题.S02", is_dir=True),
            "/strm/download/03电视剧/网盘原始标题.S02",
            "/strm/03电视剧",
            "tv",
            entries,
            NoMatchTmdb(),
            media_title="秘令",
            media_year="2020",
        )

        self.assertEqual("/strm/03电视剧/秘令 (2020)", plan.media_path)
        self.assertEqual(
            ["秘令.2020.S02E01.mkv", "秘令.2020.S02E02.mkv"],
            [item.replacement for item in plan.files],
        )
        self.assertTrue(all(item.destination_path.endswith("/Season 2") for item in plan.files))

    def test_confirmed_regular_series_rejects_only_real_episode_number_conflicts(self):
        class NoMatchTmdb(FakeTmdb):
            def search(self, *_args, **_kwargs):
                return {"results": []}

        entries = (
            RemoteEntry("first", "source", "A.S01E03.mkv", 2_000_000_000, False, "A.S01E03.mkv"),
            RemoteEntry("second", "source", "B.E03.mkv", 2_000_000_000, False, "B.E03.mkv"),
        )
        with self.assertRaisesRegex(OrganizerReview, "E03 重复"):
            _build_plan(
                organizer_settings(),
                "quark",
                RemoteEntry("source", "scope", "任意目录.S01", is_dir=True),
                "/strm/download/03电视剧/任意目录.S01",
                "/strm/03电视剧",
                "tv",
                entries,
                NoMatchTmdb(),
                media_title="秘令",
                media_year="2020",
            )

    def test_confirmed_variety_keeps_strict_tmdb_matching(self):
        class NoMatchTmdb(FakeTmdb):
            def search(self, *_args, **_kwargs):
                return {"results": []}

        with self.assertRaisesRegex(OrganizerReview, "TMDB 未找到高置信度"):
            _build_plan(
                organizer_settings(),
                "quark",
                RemoteEntry("source", "scope", "真人秀.S01", is_dir=True),
                "/strm/download/04综艺/真人秀.S01",
                "/strm/04综艺",
                "variety",
                (RemoteEntry("episode", "source", "第1期.mkv", 2_000_000_000, False, "第1期.mkv"),),
                NoMatchTmdb(),
                media_title="真人秀",
                media_year="2026",
            )

    def test_tmdb_unknown_category_balances_movie_and_tv_candidates(self):
        results = [
            {"tmdb_id": index, "media_type": "movie", "title": f"无关电影 {index}", "year": "2024"}
            for index in range(1, 9)
        ]
        results.append({"tmdb_id": 202, "media_type": "tv", "title": "测试剧", "year": "2024"})
        tmdb_id, media_type = _match_tmdb(FakeTmdb(results), "测试剧", "2024", "", None)
        self.assertEqual((202, "tv"), (tmdb_id, media_type))

    def test_movie_plan_uses_canonical_folder_and_filename(self):
        settings = organizer_settings()
        entries = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000, False, "流浪地球2.2023.2160p.mkv"),
        )
        with patch("app.services.paths.get_settings", return_value=settings), patch(
            "app.services.movie_matcher.get_settings", return_value=settings
        ):
            plan = _build_plan(
                settings,
                "p115",
                RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
                "/媒体库/下载文件夹/01电影/流浪地球2.2023",
                "/媒体库/01电影",
                "movie",
                entries,
                FakeTmdb(),
            )
        self.assertEqual("/媒体库/01电影/流浪地球2 (2023)", plan.media_path)
        self.assertEqual("流浪地球2.2023.mkv", plan.files[0].replacement)

    def test_movie_plan_refuses_unmatched_extra_video(self):
        settings = organizer_settings()
        entries = (
            RemoteEntry("main", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000, False, "main.mkv"),
            RemoteEntry("trailer", "source-folder", "流浪地球2.2023.trailer.mp4", 900_000_000, False, "trailer.mp4"),
        )
        with patch("app.services.paths.get_settings", return_value=settings), patch(
            "app.services.movie_matcher.get_settings", return_value=settings
        ):
            with self.assertRaisesRegex(OrganizerReview, "未纳入计划"):
                _build_plan(
                    settings,
                    "p115",
                    RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
                    "/媒体库/下载文件夹/01电影/流浪地球2.2023",
                    "/媒体库/01电影",
                    "movie",
                    entries,
                    FakeTmdb(),
                )

    def test_movie_plan_refuses_second_unrelated_large_video(self):
        settings = organizer_settings()
        entries = (
            RemoteEntry(
                "main",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
                False,
                "流浪地球2.2023.2160p.mkv",
            ),
            RemoteEntry(
                "unrelated",
                "source-folder",
                "阿凡达2.2022.2160p.mkv",
                8_100_000_000,
                False,
                "阿凡达2.2022.2160p.mkv",
            ),
        )
        with patch("app.services.paths.get_settings", return_value=settings), patch(
            "app.services.movie_matcher.get_settings", return_value=settings
        ):
            with self.assertRaises(OrganizerReview):
                _build_plan(
                    settings,
                    "p115",
                    RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
                    "/媒体库/下载文件夹/01电影/流浪地球2.2023",
                    "/媒体库/01电影",
                    "movie",
                    entries,
                    FakeTmdb(),
                )

    def test_movie_plan_refuses_title_that_only_contains_target_alias(self):
        class BatmanTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{"tmdb_id": 268, "media_type": "movie", "title": "Batman", "year": "1989"}])

            def details(self, _media_type, _tmdb_id):
                return {
                    "title": "Batman",
                    "original_title": "Batman",
                    "aliases": [],
                    "year": "1989",
                    "release_date": "1989-06-23",
                }

        entries = (
            RemoteEntry("batman", "source-folder", "Batman.1989.mkv", 8_000_000_000, False, "Batman.1989.mkv"),
            RemoteEntry("returns", "source-folder", "Batman.Returns.1992.mkv", 8_100_000_000, False, "Batman.Returns.1992.mkv"),
        )
        with self.assertRaises(OrganizerReview):
            _build_plan(
                organizer_settings(),
                "p115",
                RemoteEntry("source-folder", "scope", "Batman.1989", is_dir=True),
                "/媒体库/下载文件夹/01电影/Batman.1989",
                "/媒体库/01电影",
                "movie",
                entries,
                BatmanTmdb(),
            )

    def test_movie_plan_refuses_unmarked_multiple_quality_versions(self):
        entries = (
            RemoteEntry("1080", "source-folder", "流浪地球2.2023.1080p.WEB-DL.mkv", 6_000_000_000, False, "1080.mkv"),
            RemoteEntry("2160", "source-folder", "流浪地球2.2023.2160p.REMUX.mkv", 20_000_000_000, False, "2160.mkv"),
        )
        with self.assertRaises(OrganizerReview):
            _build_plan(
                organizer_settings(),
                "p115",
                RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
                "/媒体库/下载文件夹/01电影/流浪地球2.2023",
                "/媒体库/01电影",
                "movie",
                entries,
                FakeTmdb(),
            )

    def test_movie_plan_requires_unique_contiguous_part_numbers(self):
        entries = tuple(
            RemoteEntry(
                f"cd{number}",
                "source-folder",
                f"流浪地球2.2023.CD{number}.mkv",
                6_000_000_000,
                False,
                f"CD{number}.mkv",
            )
            for number in (2, 3)
        )
        with self.assertRaisesRegex(OrganizerReview, r"1\.\.N"):
            _build_plan(
                organizer_settings(),
                "p115",
                RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
                "/媒体库/下载文件夹/01电影/流浪地球2.2023",
                "/媒体库/01电影",
                "movie",
                entries,
                FakeTmdb(),
            )

    def test_movie_plan_carries_same_stem_subtitle_with_canonical_name(self):
        settings = organizer_settings()
        entries = (
            RemoteEntry("main", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000, False, "main.mkv"),
            RemoteEntry("subtitle", "source-folder", "流浪地球2.2023.2160p.zh-CN.ass", 120_000, False, "subtitle.ass"),
        )
        with patch("app.services.paths.get_settings", return_value=settings), patch(
            "app.services.movie_matcher.get_settings", return_value=settings
        ):
            plan = _build_plan(
                settings,
                "p115",
                RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
                "/媒体库/下载文件夹/01电影/流浪地球2.2023",
                "/媒体库/01电影",
                "movie",
                entries,
                FakeTmdb(),
            )
        self.assertEqual(
            ["流浪地球2.2023.mkv", "流浪地球2.2023.zh-CN.ass"],
            [item.replacement for item in plan.files],
        )

    def test_tv_plan_always_builds_season_folder(self):
        settings = organizer_settings()
        tmdb = FakeTmdb([{"tmdb_id": 202, "media_type": "tv", "title": "测试剧", "year": "2024"}])
        entries = tuple(
            RemoteEntry(
                f"episode-{episode}",
                "source-folder",
                f"测试剧.S01E{episode:02d}.mkv",
                2_000_000_000,
                False,
                f"测试剧.S01E{episode:02d}.mkv",
            )
            for episode in (1, 2)
        )
        with patch("app.services.paths.get_settings", return_value=settings), patch(
            "app.services.episode_matcher.get_settings", return_value=settings
        ):
            plan = _build_plan(
                settings,
                "p115",
                RemoteEntry("source-folder", "scope", "测试剧.2024.S01", is_dir=True),
                "/媒体库/下载文件夹/03电视剧/测试剧.2024.S01",
                "/媒体库/03电视剧",
                "tv",
                entries,
                tmdb,
            )
        self.assertEqual({"/媒体库/03电视剧/测试剧 (2024)/Season 1"}, {item.destination_path for item in plan.files})
        self.assertEqual(["测试剧.2024.S01E01.mkv", "测试剧.2024.S01E02.mkv"], [item.replacement for item in plan.files])

    def test_tv_plan_uses_explicit_file_episodes_when_tmdb_season_is_404(self):
        class MissingSeasonTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{"tmdb_id": 202, "media_type": "tv", "title": "测试剧", "year": "2024"}])

            def season(self, _tmdb_id, _season_number):
                return {"error": "HTTP Error 404: Not Found"}

        settings = organizer_settings()
        entries = tuple(
            RemoteEntry(
                f"episode-{episode}",
                "source-folder",
                f"测试剧.S01E{episode:02d}.mkv",
                2_000_000_000,
                False,
                f"测试剧.S01E{episode:02d}.mkv",
            )
            for episode in (1, 2)
        )
        with patch("app.services.paths.get_settings", return_value=settings), patch(
            "app.services.episode_matcher.get_settings", return_value=settings
        ):
            plan = _build_plan(
                settings,
                "quark",
                RemoteEntry("source-folder", "scope", "测试剧.S01", is_dir=True),
                "/strm/download/03电视剧/测试剧.S01",
                "/strm/03电视剧",
                "tv",
                entries,
                MissingSeasonTmdb(),
                media_title="测试剧",
            )

        self.assertEqual({"/strm/03电视剧/测试剧 (2024)/Season 1"}, {item.destination_path for item in plan.files})
        self.assertEqual(["测试剧.2024.S01E01.mkv", "测试剧.2024.S01E02.mkv"], [item.replacement for item in plan.files])

    def test_tv_plan_reviews_tmdb_season_404_without_explicit_episode_names(self):
        class MissingSeasonTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{"tmdb_id": 202, "media_type": "tv", "title": "测试剧", "year": "2024"}])

            def season(self, _tmdb_id, _season_number):
                return {"error": "HTTP Error 404: Not Found"}

        with self.assertRaisesRegex(OrganizerReview, "源文件名无法完整提取明确集号"):
            _build_plan(
                organizer_settings(),
                "quark",
                RemoteEntry("source-folder", "scope", "测试剧.S01", is_dir=True),
                "/strm/download/03电视剧/测试剧.S01",
                "/strm/03电视剧",
                "tv",
                (
                    RemoteEntry(
                        "unknown",
                        "source-folder",
                        "测试剧.1080p.mkv",
                        2_000_000_000,
                        False,
                        "测试剧.1080p.mkv",
                    ),
                ),
                MissingSeasonTmdb(),
                media_title="测试剧",
            )

    def test_tv_plan_refuses_unmarked_video_when_multiple_seasons_are_present(self):
        settings = organizer_settings()
        tmdb = FakeTmdb([{"tmdb_id": 202, "media_type": "tv", "title": "测试剧", "year": "2024"}])
        entries = (
            RemoteEntry("s1", "source-folder", "测试剧.S01E01.mkv", 2_000_000_000, False, "S01/测试剧.S01E01.mkv"),
            RemoteEntry("s2", "source-folder", "测试剧.S02E01.mkv", 2_000_000_000, False, "S02/测试剧.S02E01.mkv"),
            RemoteEntry("unknown", "source-folder", "测试剧.E02.mkv", 2_000_000_000, False, "测试剧.E02.mkv"),
        )
        with self.assertRaisesRegex(OrganizerReview, "未标明季度"):
            _build_plan(
                settings,
                "p115",
                RemoteEntry("source-folder", "scope", "测试剧.2024", is_dir=True),
                "/媒体库/下载文件夹/03电视剧/测试剧.2024",
                "/媒体库/03电视剧",
                "tv",
                entries,
                tmdb,
            )

    def test_tv_plan_refuses_explicit_episode_from_another_show(self):
        settings = organizer_settings()
        tmdb = FakeTmdb([{"tmdb_id": 202, "media_type": "tv", "title": "测试剧", "year": "2024"}])
        entries = (
            RemoteEntry("own", "source-folder", "测试剧.S01E01.mkv", 2_000_000_000, False, "测试剧.S01E01.mkv"),
            RemoteEntry("other", "source-folder", "别的剧.S01E02.mkv", 2_000_000_000, False, "别的剧.S01E02.mkv"),
        )
        with self.assertRaisesRegex(OrganizerReview, "同一剧集"):
            _build_plan(
                settings,
                "p115",
                RemoteEntry("source-folder", "scope", "测试剧.2024.S01", is_dir=True),
                "/媒体库/下载文件夹/03电视剧/测试剧.2024.S01",
                "/媒体库/03电视剧",
                "tv",
                entries,
                tmdb,
            )

    def test_tv_plan_accepts_episode_titles_and_release_metadata_after_marker(self):
        class TheOrderTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{"tmdb_id": 417, "media_type": "tv", "title": "秘令", "year": "2020"}])

            def details(self, _media_type, _tmdb_id):
                return {
                    "title": "秘令",
                    "original_title": "The Order",
                    "aliases": ["秘令"],
                    "year": "2020",
                    "poster_url": "poster",
                    "overview": "",
                    "release_date": "2020-06-18",
                    "status": "Ended",
                }

            def season(self, _tmdb_id, season_number):
                return {
                    "air_date": "2020-06-18",
                    "episodes": [
                        {
                            "episode_number": episode,
                            "name": f"Episode {episode}",
                            "air_date": f"2020-06-{17 + episode:02d}",
                        }
                        for episode in range(1, 11)
                    ],
                }

        entries = tuple(
            RemoteEntry(
                f"episode-{episode}",
                "source-folder",
                f"The.Order.S02E{episode:02d}.Episode.Title.1080p.NF.WEB-DL.DDP5.1.x264-NTb.mkv",
                2_000_000_000,
                False,
                f"The.Order.S02E{episode:02d}.Episode.Title.1080p.NF.WEB-DL.DDP5.1.x264-NTb.mkv",
            )
            for episode in range(1, 11)
        )

        plan = _build_plan(
            organizer_settings(),
            "quark",
            RemoteEntry("source-folder", "scope", "秘令 (2020)", is_dir=True),
            "/strm/download/03电视剧/秘令 (2020)",
            "/strm/03电视剧",
            "tv",
            entries,
            TheOrderTmdb(),
            media_title="秘令",
            media_year="2020",
        )

        self.assertEqual(10, len(plan.files))
        self.assertEqual(
            {"/strm/03电视剧/秘令 (2020)/Season 2"},
            {item.destination_path for item in plan.files},
        )
        self.assertEqual("秘令.2020.S02E01.mkv", plan.files[0].replacement)

    def test_tv_plan_accepts_explicit_title_after_high_confidence_tmdb_match(self):
        class LocalizedTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{"tmdb_id": 417, "media_type": "tv", "title": "秘令", "year": "2020"}])

            def details(self, _media_type, _tmdb_id):
                return {
                    "title": "The Order",
                    "original_title": "The Order",
                    "aliases": ["秘令"],
                    "year": "2019",
                    "poster_url": "poster",
                    "overview": "",
                    "release_date": "2019-03-07",
                    "status": "Ended",
                }

            def season(self, _tmdb_id, _season_number):
                return {
                    "air_date": "2020-06-18",
                    "episodes": [
                        {"episode_number": episode, "name": "", "air_date": "2020-06-18"}
                        for episode in range(1, 11)
                    ],
                }

        entries = tuple(
            RemoteEntry(
                f"episode-{episode}",
                "source-folder",
                f"秘令.2020.S02E{episode:02d}.mkv",
                2_000_000_000,
                False,
                f"秘令.2020.S02E{episode:02d}.mkv",
            )
            for episode in range(1, 11)
        )

        plan = _build_plan(
            organizer_settings(),
            "quark",
            RemoteEntry("source-folder", "scope", "秘令 (2020)", is_dir=True),
            "/strm/download/03电视剧/秘令 (2020)",
            "/strm/03电视剧",
            "tv",
            entries,
            LocalizedTmdb(),
            media_title="秘令",
            media_year="2020",
        )

        self.assertEqual(10, len(plan.files))
        self.assertEqual("秘令.2020.S02E01.mkv", plan.files[0].replacement)
        self.assertEqual(
            {"/strm/03电视剧/秘令 (2020)/Season 2"},
            {item.destination_path for item in plan.files},
        )

    def test_confirmed_tv_plan_accepts_leading_episode_number_and_release_metadata(self):
        class ConfirmedTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{"tmdb_id": 92026, "media_type": "tv", "title": "花开锦绣", "year": "2026"}])

            def details(self, _media_type, _tmdb_id):
                return {
                    "title": "花开锦绣",
                    "original_title": "花开锦绣",
                    "aliases": [],
                    "year": "2026",
                    "poster_url": "poster",
                    "overview": "",
                    "release_date": "2026-08-01",
                    "status": "Returning Series",
                    "seasons": [{"season_number": 1, "air_date": "2026-08-01"}],
                }

            def season(self, _tmdb_id, _season_number):
                return {
                    "air_date": "2026-08-01",
                    "episodes": [
                        {"episode_number": episode, "name": "", "air_date": "2026-08-01"}
                        for episode in range(1, 32)
                    ],
                }

        entries = tuple(
            RemoteEntry(
                f"episode-{episode}",
                "source-folder",
                f"{episode:02d}-4K.高码率.mp4",
                2_000_000_000,
                False,
                f"{episode:02d}-4K.高码率.mp4",
            )
            for episode in range(1, 32)
        )

        plan = _build_plan(
            organizer_settings(),
            "quark",
            RemoteEntry("source-folder", "scope", "花开锦绣 (2026)", is_dir=True),
            "/strm/download/03电视剧/花开锦绣 (2026)",
            "/strm/03电视剧",
            "tv",
            entries,
            ConfirmedTmdb(),
            media_title="花开锦绣",
            media_year="2026",
        )

        self.assertEqual(31, len(plan.files))
        self.assertEqual("花开锦绣.2026.S01E01.mp4", plan.files[0].replacement)
        self.assertEqual("花开锦绣.2026.S01E31.mp4", plan.files[-1].replacement)
        self.assertEqual(
            {"/strm/03电视剧/花开锦绣 (2026)/Season 1"},
            {item.destination_path for item in plan.files},
        )

    def test_confirmed_tv_identity_does_not_require_cloud_filenames_to_repeat_the_title(self):
        class ConfirmedTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([{"tmdb_id": 92026, "media_type": "tv", "title": "花开锦绣", "year": "2026"}])

            def details(self, _media_type, _tmdb_id):
                return {
                    "title": "花开锦绣",
                    "original_title": "花开锦绣",
                    "aliases": [],
                    "year": "2026",
                    "status": "Ended",
                    "seasons": [{"season_number": 1}],
                }

            def season(self, _tmdb_id, _season_number):
                return {
                    "episodes": [
                        {"episode_number": episode, "name": "", "air_date": "2026-08-01"}
                        for episode in (1, 2)
                    ],
                }

        entries = (
            RemoteEntry("episode-1", "source-folder", "01.mp4", 2_000_000_000, False, "01.mp4"),
            RemoteEntry("episode-2", "source-folder", "完全不规范的发布名.E02.1080p.mkv", 2_000_000_000, False, "完全不规范的发布名.E02.1080p.mkv"),
        )

        plan = _build_plan(
            organizer_settings(),
            "quark",
            RemoteEntry("source-folder", "scope", "任意分享目录", is_dir=True),
            "/strm/download/03电视剧/花开锦绣 (2026)",
            "/strm/03电视剧",
            "tv",
            entries,
            ConfirmedTmdb(),
            media_title="花开锦绣",
            media_year="2026",
        )

        self.assertEqual(
            ["花开锦绣.2026.S01E01.mp4", "花开锦绣.2026.S01E02.mkv"],
            [item.replacement for item in plan.files],
        )

    def test_confirmed_title_and_season_evidence_beat_misleading_quark_candidate(self):
        class AmbiguousTitleTmdb(FakeTmdb):
            def __init__(self):
                super().__init__([
                    {"tmdb_id": 900, "media_type": "tv", "title": "天机库", "year": "2020"},
                    {"tmdb_id": 417, "media_type": "tv", "title": "The Order", "year": "2019"},
                ])

            def details(self, _media_type, tmdb_id):
                if tmdb_id == 900:
                    return {"title": "天机库", "original_title": "Mystery Vault", "aliases": ["秘令"], "year": "2020"}
                return {"title": "The Order", "original_title": "The Order", "aliases": ["秘令"], "year": "2019"}

            def season(self, tmdb_id, season_number):
                if tmdb_id == 900:
                    raise RuntimeError("HTTP Error 404: Not Found")
                return {
                    "air_date": "2020-06-18",
                    "episodes": [
                        {"episode_number": episode, "name": "", "air_date": "2020-06-18"}
                        for episode in range(1, 11)
                    ],
                }

        entries = tuple(
            RemoteEntry(
                f"episode-{episode}",
                "source-folder",
                f"秘令.2020.S02E{episode:02d}.mkv",
                2_000_000_000,
                False,
                f"秘令.2020.S02E{episode:02d}.mkv",
            )
            for episode in range(1, 11)
        )
        plan = _build_plan(
            organizer_settings(),
            "quark",
            RemoteEntry("source-folder", "scope", "天机库", is_dir=True),
            "/strm/download/03电视剧/秘令 (2020)",
            "/strm/03电视剧",
            "tv",
            entries,
            AmbiguousTitleTmdb(),
            media_title="秘令",
            media_year="2020",
        )
        self.assertEqual(417, plan.target.tmdb_id)
        self.assertEqual("/strm/03电视剧/秘令 (2020)", plan.media_path)
        self.assertEqual("秘令.2020.S02E01.mkv", plan.files[0].replacement)

    def test_tv_plan_still_refuses_other_show_with_release_metadata(self):
        settings = organizer_settings()
        tmdb = FakeTmdb([{"tmdb_id": 202, "media_type": "tv", "title": "测试剧", "year": "2024"}])
        entries = (
            RemoteEntry(
                "other",
                "source-folder",
                "Another.Show.S02E01.Pilot.1080p.WEB-DL.DDP5.1.x264-NTb.mkv",
                2_000_000_000,
                False,
                "Another.Show.S02E01.Pilot.1080p.WEB-DL.DDP5.1.x264-NTb.mkv",
            ),
        )
        with self.assertRaisesRegex(OrganizerReview, "Another.Show.S02E01"):
            _build_plan(
                settings,
                "quark",
                RemoteEntry("source-folder", "scope", "测试剧.2024.S02", is_dir=True),
                "/媒体库/下载文件夹/03电视剧/测试剧.2024.S02",
                "/媒体库/03电视剧",
                "tv",
                entries,
                tmdb,
            )

    def test_destination_conflict_fails_before_any_mutation(self):
        adapter = RecordingAdapter()
        adapter.path_ids["/媒体库/01电影/流浪地球2 (2023)"] = "target"
        adapter.directories["target"] = [RemoteEntry("existing", "target", "流浪地球2.2023.mkv", 8_000_000_000)]
        plan = self._movie_plan()
        with self.assertRaisesRegex(OrganizerReview, "未覆盖"):
            _preflight_destinations(adapter, plan)
        self.assertFalse(any(call[0] in {"ensure", "copy", "move", "rename", "trash"} for call in adapter.calls))

    def test_copy_preserves_source_and_verifies_before_staging_cleanup(self):
        adapter = RecordingAdapter()
        adapter.source_tree = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
        )
        settings = organizer_settings()
        _execute_copy(settings, adapter, self._movie_plan(), "fingerprint")
        operations = [call[0] for call in adapter.calls]
        self.assertIn("copy", operations)
        self.assertIn("move", operations)
        self.assertNotIn(("trash", "source-folder"), adapter.calls)
        staging_trash_index = next(
            index
            for index, call in enumerate(adapter.calls)
            if call[0] == "trash" and call[1] != "source-folder"
        )
        target_id = next(call[2] for call in adapter.calls if call[0] == "move")
        target_verify_index = next(
            index
            for index, call in enumerate(adapter.calls)
            if call == ("list", target_id)
        )
        self.assertLess(target_verify_index, staging_trash_index)

    def test_copy_does_not_accept_external_same_name_target_after_preflight(self):
        class CollisionAdapter(RecordingAdapter):
            def move(inner_self, file_ids, destination_id):
                inner_self.calls.append(("move", tuple(file_ids), destination_id))
                for directory in inner_self.directories.values():
                    directory[:] = [item for item in directory if item.file_id not in set(file_ids)]
                inner_self.directories.setdefault(destination_id, []).append(
                    RemoteEntry("external", destination_id, "流浪地球2.2023.mkv", 8_000_000_000)
                )

        adapter = CollisionAdapter()
        adapter.source_tree = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
        )
        with self.assertRaisesRegex(RuntimeError, "未唯一确认"):
            _execute_copy(organizer_settings(), adapter, self._movie_plan(), "fingerprint")
        self.assertNotIn(("trash", "source-folder"), adapter.calls)

    def test_copy_does_not_claim_unbound_file_preexisting_in_staging(self):
        adapter = RecordingAdapter()
        adapter.source_tree = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
        )
        staging_path = "/.media-index-staging/cloud-download-organizer/fingerprint/1"
        adapter.path_ids[staging_path] = "preexisting-stage"
        adapter.directories["preexisting-stage"] = [
            RemoteEntry("external-stage", "preexisting-stage", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
        ]
        with self.assertRaisesRegex(OrganizerReview, "没有本任务回执"):
            _execute_copy(organizer_settings(), adapter, self._movie_plan(), "fingerprint")
        self.assertFalse(any(call[0] in {"copy", "move", "rename", "trash"} for call in adapter.calls))

    def test_move_cleans_exact_residuals_then_recycles_verified_source_folder(self):
        adapter = RecordingAdapter()
        adapter.source_tree = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
            RemoteEntry("readme", "source-folder", "readme.txt", 1024),
            RemoteEntry("empty-dir", "source-folder", "extras", 0, True),
        )
        adapter.directories["scope"].append(
            RemoteEntry("sibling-folder", "scope", "另一部电影.2024", is_dir=True)
        )
        _execute_move(adapter, self._movie_plan())
        self.assertIn(("trash", "readme"), adapter.calls)
        self.assertIn(("trash", "source-folder"), adapter.calls)
        self.assertNotIn(("trash", "empty-dir"), adapter.calls)
        self.assertLess(
            next(i for i, call in enumerate(adapter.calls) if call[0] == "move"),
            next(i for i, call in enumerate(adapter.calls) if call == ("trash", "readme")),
        )
        self.assertLess(
            next(i for i, call in enumerate(adapter.calls) if call == ("trash", "readme")),
            next(i for i, call in enumerate(adapter.calls) if call == ("trash", "source-folder")),
        )
        self.assertTrue(any(entry.file_id == "sibling-folder" for entry in adapter.directories["scope"]))

    def test_move_does_not_recycle_shared_scope_for_direct_file_group(self):
        adapter = RecordingAdapter()
        scope_path = "/媒体库/下载文件夹/01电影"
        source_entry = RemoteEntry(
            "source-video", "scope", "流浪地球2.2023.2160p.mkv", 8_000_000_000, False,
            "流浪地球2.2023.2160p.mkv",
        )
        adapter.directories["scope"] = [source_entry]
        group_key = organizer._loose_media_groups((source_entry,), "movie")[0][0]
        plan = OrganizePlan(
            MediaTarget(101, "movie", "流浪地球2", category="movie", series_year="2023"),
            RemoteEntry("scope", "", "流浪地球2.2023", is_dir=True),
            f"{scope_path}/流浪地球2.2023",
            "/媒体库/01电影/流浪地球2 (2023)",
            "movie",
            (
                PlannedFile(
                    SourceFile(source_entry.name, source_entry.size, source_entry.name, source_entry.file_id, "scope"),
                    "流浪地球2.2023.mkv",
                    "/媒体库/01电影/流浪地球2 (2023)",
                ),
            ),
            scope_path,
            group_key,
        )

        _execute_move(adapter, plan, source_entries=(source_entry,))

        self.assertNotIn(("trash", "scope"), adapter.calls)

    def test_move_does_not_accept_external_same_name_target_after_preflight(self):
        class CollisionAdapter(RecordingAdapter):
            def move(inner_self, file_ids, destination_id):
                inner_self.calls.append(("move", tuple(file_ids), destination_id))
                inner_self.source_tree = tuple(
                    item for item in inner_self.source_tree if item.file_id not in set(file_ids)
                )
                inner_self.directories.setdefault(destination_id, []).append(
                    RemoteEntry("external", destination_id, "流浪地球2.2023.mkv", 8_000_000_000)
                )

        adapter = CollisionAdapter()
        adapter.source_tree = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
            RemoteEntry("readme", "source-folder", "readme.txt", 1024),
        )
        with self.assertRaisesRegex(RuntimeError, "未唯一确认"):
            _execute_move(adapter, self._movie_plan())
        self.assertNotIn(("trash", "readme"), adapter.calls)

    def test_move_retry_skips_source_that_is_already_renamed(self):
        adapter = RecordingAdapter()
        adapter.source_tree = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.mkv", 8_000_000_000),
        )
        _execute_move(adapter, self._movie_plan())
        self.assertFalse(any(call[0] == "rename" for call in adapter.calls))
        self.assertTrue(any(call[0] == "move" for call in adapter.calls))

    def test_move_direct_file_group_keeps_unrelated_scope_files(self):
        adapter = RecordingAdapter()
        scope_path = "/媒体库/下载文件夹/01电影"
        source_entry = RemoteEntry(
            "source-video", "scope", "流浪地球2.2023.2160p.mkv", 8_000_000_000, False,
            "流浪地球2.2023.2160p.mkv",
        )
        unrelated = RemoteEntry("unrelated", "scope", "other-download.txt", 1024)
        adapter.directories["scope"] = [source_entry, unrelated]
        group_key = organizer._loose_media_groups((source_entry, unrelated), "movie")[0][0]
        source = SourceFile(
            source_entry.name,
            source_entry.size,
            source_entry.name,
            source_entry.file_id,
            "scope",
        )
        destination = "/媒体库/01电影/流浪地球2 (2023)"
        plan = OrganizePlan(
            MediaTarget(101, "movie", "流浪地球2", category="movie", series_year="2023"),
            RemoteEntry("scope", "", "流浪地球2.2023", is_dir=True),
            f"{scope_path}/流浪地球2.2023",
            destination,
            "movie",
            (PlannedFile(source, "流浪地球2.2023.mkv", destination),),
            scope_path,
            group_key,
        )
        _execute_move(adapter, plan, source_entries=(source_entry,))
        self.assertTrue(any(item.file_id == "unrelated" for item in adapter.directories["scope"]))
        self.assertFalse(any(call == ("trash", "unrelated") for call in adapter.calls))

    def test_cleanup_requires_trash_result_to_disappear(self):
        class NoOpTrashAdapter(RecordingAdapter):
            request_timeout_seconds = 1

            def trash(self, file_id):
                self.calls.append(("trash", file_id))

        adapter = NoOpTrashAdapter()
        adapter.source_tree = (RemoteEntry("readme", "source-folder", "readme.txt", 1024),)
        with self.assertRaisesRegex(RuntimeError, "未在时限内确认"):
            organizer._cleanup_residual_files(adapter, self._movie_plan())
        self.assertIn(("trash", "readme"), adapter.calls)

    def test_empty_source_folder_cleanup_requires_parent_listing_confirmation(self):
        class NoOpFolderTrashAdapter(RecordingAdapter):
            def trash(self, file_id):
                self.calls.append(("trash", file_id))
                if file_id != "source-folder":
                    super().trash(file_id)

        adapter = NoOpFolderTrashAdapter()
        adapter.source_tree = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
        )
        with patch("app.services.cloud_download_organizer.time.monotonic", side_effect=[0, 2]), patch(
            "app.services.cloud_download_organizer.time.sleep"
        ):
            with self.assertRaisesRegex(RuntimeError, "源媒体目录回收操作未在时限内确认"):
                _execute_move(adapter, self._movie_plan())
        self.assertIn(("trash", "source-folder"), adapter.calls)

    def test_folder_cleanup_rechecks_tree_after_parent_identity_read(self):
        class LateArrivalAdapter(RecordingAdapter):
            def __init__(inner_self):
                super().__init__()
                inner_self.scope_reads = 0

            def list_directory(inner_self, directory_id):
                result = super().list_directory(directory_id)
                if directory_id == "scope":
                    inner_self.scope_reads += 1
                    if inner_self.scope_reads == 2:
                        inner_self.source_tree = (
                            RemoteEntry("late-video", "source-folder", "Late.Arrival.mkv", 1_000_000_000),
                        )
                return result

        adapter = LateArrivalAdapter()
        with self.assertRaisesRegex(OrganizerReview, "计划外的新到达"):
            _trash_empty_source_folder(adapter, self._movie_plan(), (), job_id=None)

        self.assertNotIn(("trash", "source-folder"), adapter.calls)

    def test_source_scope_identity_change_blocks_all_remote_mutations(self):
        adapter = RecordingAdapter()
        adapter.source_tree = (
            RemoteEntry("source-video", "source-folder", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
        )
        adapter.directories["scope"] = [
            RemoteEntry("replacement-folder", "scope", "流浪地球2.2023", is_dir=True),
        ]
        with self.assertRaises((OrganizerReview, RuntimeError)):
            organizer._verify_source_folder_scope(adapter, self._movie_plan())
        with self.assertRaises((OrganizerReview, RuntimeError)):
            _execute_move(adapter, self._movie_plan())
        self.assertFalse(any(call[0] in {"ensure", "rename", "move", "copy", "trash"} for call in adapter.calls))

    def test_planned_source_identity_change_blocks_all_remote_mutations(self):
        adapter = RecordingAdapter()
        adapter.source_tree = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                7_999_999_999,
            ),
        )
        planned_snapshot = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
            ),
        )
        with self.assertRaises((OrganizerReview, RuntimeError)):
            _execute_move(adapter, self._movie_plan(), source_entries=planned_snapshot)
        self.assertFalse(any(call[0] in {"ensure", "rename", "move", "copy", "trash"} for call in adapter.calls))

    def test_cleanup_refuses_excluded_or_large_unknown_potential_video(self):
        settings = organizer_settings(resource_excluded_keywords_json='["TC"]')
        for residual in (
            RemoteEntry("excluded", "source-folder", "流浪地球2.TC.mkv", 2_000_000_000),
            RemoteEntry("unknown", "source-folder", "未知媒体.payload", 200 * 1024 * 1024),
            RemoteEntry("legacy-video", "source-folder", "旧格式影片.rmvb", 50 * 1024 * 1024),
            RemoteEntry("audio", "source-folder", "原声带.flac", 50 * 1024 * 1024),
            RemoteEntry("document", "source-folder", "收藏清单.pdf", 1024),
            RemoteEntry("small-unknown", "source-folder", "片段.payload", 1024),
        ):
            with self.subTest(residual=residual.name):
                adapter = RecordingAdapter()
                adapter.source_tree = (residual,)
                with patch("app.services.cloud_download_organizer.get_settings", return_value=settings), patch(
                    "app.services.episode_matcher.get_settings", return_value=settings
                ):
                    with self.assertRaises((OrganizerReview, RuntimeError)):
                        organizer._cleanup_residual_files(adapter, self._movie_plan())
                self.assertFalse(any(call[0] == "trash" for call in adapter.calls))

    def test_preflight_reuses_only_verified_exact_target_and_rejects_wrong_size(self):
        adapter = RecordingAdapter()
        target_path = "/媒体库/01电影/流浪地球2 (2023)"
        adapter.path_ids[target_path] = "target"
        adapter.directories["target"] = [
            RemoteEntry("existing", "target", "流浪地球2.2023.mkv", 8_000_000_000),
        ]
        binding = {
            "source-video": {
                "path": target_path,
                "file_id": "existing",
                "name": "流浪地球2.2023.mkv",
                "size": 8_000_000_000,
            }
        }
        _preflight_destinations(adapter, self._movie_plan(), reusable_targets=binding)
        with self.assertRaises(OrganizerReview):
            _preflight_destinations(adapter, self._movie_plan())

        adapter.directories["target"] = [
            RemoteEntry("existing", "target", "流浪地球2.2023.mkv", 7_999_999_999),
        ]
        with self.assertRaises(OrganizerReview):
            _preflight_destinations(adapter, self._movie_plan(), reusable_targets=binding)

        adapter.directories["target"] = [
            RemoteEntry("existing-dir", "target", "流浪地球2.2023.mkv", 0, True),
        ]
        with self.assertRaises(OrganizerReview):
            _preflight_destinations(adapter, self._movie_plan(), reusable_targets=binding)

    def _movie_plan(self):
        source = SourceFile(
            "流浪地球2.2023.2160p.mkv",
            8_000_000_000,
            "流浪地球2.2023.2160p.mkv",
            "source-video",
            "source-folder",
        )
        target = MediaTarget(101, "movie", "流浪地球2", category="movie", series_year="2023")
        return OrganizePlan(
            target,
            RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
            "/媒体库/下载文件夹/01电影/流浪地球2.2023",
            "/媒体库/01电影/流浪地球2 (2023)",
            "movie",
            (PlannedFile(source, "流浪地球2.2023.mkv", "/媒体库/01电影/流浪地球2 (2023)"),),
        )

    def test_quark_completion_uses_media_target_series_year(self):
        plan = self._movie_plan()
        with patch(
            "app.services.cloud_download_organizer._verified_target_bindings",
            return_value={"source-video": {"file_id": "target-video"}},
        ), patch(
            "app.services.organized_p115_completion.prepare_organized_quark_completion",
            return_value=True,
        ) as prepare:
            result = organizer._prepare_organized_quark_completion(42, plan, "movie")
        self.assertTrue(result)
        self.assertEqual("2023", prepare.call_args.kwargs["year"])


class CloudDownloadOrganizerJobTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {"DB_PATH": str(Path(self.tempdir.name) / "test.db")},
            clear=False,
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_stability_job_is_idempotent_and_failed_attempt_restarts_wait(self):
        execution_key = "organizer:p115:folder:copy"
        first = _stable_job(execution_key, "p115", "/source", "媒体", "fingerprint", "copy")
        second = _stable_job(execution_key, "p115", "/source", "媒体", "fingerprint", "copy")
        self.assertEqual(first["id"], second["id"])
        with db() as conn:
            conn.execute("UPDATE transfer_jobs SET status='failed' WHERE id=?", (first["id"],))
        restarted = _stable_job(execution_key, "p115", "/source", "媒体", "fingerprint", "copy")
        self.assertEqual(first["id"], restarted["id"])
        self.assertEqual("ready", restarted["status"])

    def test_post_processing_failure_does_not_claim_ingestion_or_prompt_backfill(self):
        plan = self._movie_plan()
        with db() as conn:
            job_id = int(conn.execute(
                """INSERT INTO transfer_jobs(
                       target,provider,status,stage,request_source,external_provider_status
                   ) VALUES('cloud','p115','running','organizer_post_processing','cloud_download_organizer','{}')"""
            ).lastrowid)
        with (
            patch("app.services.cloud_download_organizer.run_post_transfer_pipeline", return_value=False),
            patch("app.services.cloud_download_organizer._prepare_organized_media_followup") as followup,
            patch("app.services.organized_media_followup.deliver_organized_backfill_prompt") as prompt,
        ):
            message = organizer._finalize_organized_landing(
                job_id,
                plan,
                RecordingAdapter(),
                "正式媒体库落盘已核验",
            )

        followup.assert_not_called()
        prompt.assert_not_called()
        self.assertIn("入库后处理未完成", message)
        with db() as conn:
            row = conn.execute("SELECT status,message FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual("done", row["status"])
        self.assertIn("暂未发起缺集确认", row["message"])

    def test_unacknowledged_copy_result_is_not_claimed_after_client_timeout(self):
        class TimeoutAfterCopyAdapter(RecordingAdapter):
            timed_out = False

            def copy(inner_self, file_ids, destination_id):
                super().copy(file_ids, destination_id)
                if not inner_self.timed_out:
                    inner_self.timed_out = True
                    raise RuntimeError("provider response lost after successful copy")

        settings = organizer_settings(cloud_download_organizer_enabled=True)
        plan = self._movie_plan()
        expected = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
                False,
                "流浪地球2.2023.2160p.mkv",
            ),
        )
        fingerprint = organizer._inventory_fingerprint(plan.source_folder, expected)
        job = _stable_job(
            "organizer:p115:copy-intent:copy",
            "p115",
            plan.source_path,
            plan.source_folder.name,
            fingerprint,
            "copy",
        )
        serialized = [{**asdict(item), "source": asdict(item.source)} for item in plan.files]
        organizer._update_job_plan(
            int(job["id"]),
            plan,
            serialized,
            fingerprint,
            "copy",
            source_entries=expected,
        )
        organizer._mark_job_write_started(int(job["id"]))
        adapter = TimeoutAfterCopyAdapter()
        adapter.source_tree = expected

        with patch("app.services.cloud_download_organizer.get_settings", return_value=settings):
            with self.assertRaisesRegex(RuntimeError, "response lost"):
                _execute_copy(
                    settings,
                    adapter,
                    plan,
                    fingerprint,
                    job_id=int(job["id"]),
                    source_entries=expected,
                )
            intents = organizer._copy_intent_bindings(int(job["id"]))
            self.assertIn("source-video", intents)
            self.assertFalse(intents["source-video"]["acknowledged"])
            with self.assertRaisesRegex(OrganizerReview, "没有本任务回执"):
                _execute_copy(
                    settings,
                    adapter,
                    plan,
                    fingerprint,
                    job_id=int(job["id"]),
                    source_entries=expected,
                )

        self.assertEqual(1, len([call for call in adapter.calls if call[0] == "copy"]))
        self.assertFalse(any(call[0] == "move" for call in adapter.calls))
        self.assertEqual({}, organizer._verified_target_bindings(int(job["id"])))

    def test_acknowledged_copy_intent_recovers_crash_before_receipt(self):
        settings = organizer_settings(cloud_download_organizer_enabled=True)
        plan = self._movie_plan()
        expected = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
                False,
                "流浪地球2.2023.2160p.mkv",
            ),
        )
        fingerprint = organizer._inventory_fingerprint(plan.source_folder, expected)
        job = _stable_job(
            "organizer:p115:copy-acknowledged:copy",
            "p115",
            plan.source_path,
            plan.source_folder.name,
            fingerprint,
            "copy",
        )
        serialized = [{**asdict(item), "source": asdict(item.source)} for item in plan.files]
        organizer._update_job_plan(
            int(job["id"]),
            plan,
            serialized,
            fingerprint,
            "copy",
            source_entries=expected,
        )
        organizer._mark_job_write_started(int(job["id"]))
        adapter = RecordingAdapter()
        adapter.source_tree = expected

        with patch("app.services.cloud_download_organizer.get_settings", return_value=settings):
            with patch(
                "app.services.cloud_download_organizer._record_write_receipts",
                side_effect=RuntimeError("crash before receipt"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash before receipt"):
                    _execute_copy(
                        settings,
                        adapter,
                        plan,
                        fingerprint,
                        job_id=int(job["id"]),
                        source_entries=expected,
                    )
            self.assertTrue(
                organizer._copy_intent_bindings(int(job["id"]))["source-video"]["acknowledged"]
            )
            _execute_copy(
                settings,
                adapter,
                plan,
                fingerprint,
                job_id=int(job["id"]),
                source_entries=expected,
            )

        self.assertEqual(1, len([call for call in adapter.calls if call[0] == "copy"]))
        self.assertEqual({}, organizer._copy_intent_bindings(int(job["id"])))
        self.assertEqual(
            "copy-video",
            organizer._verified_target_bindings(int(job["id"]))["source-video"]["file_id"],
        )

    def test_provider_scan_includes_media_files_directly_under_selected_scope(self):
        settings = organizer_settings(cloud_download_organizer_enabled=True)
        adapter = RecordingAdapter()
        adapter.directories["scope"] = [
            RemoteEntry("direct-video", "scope", "流浪地球2.2023.2160p.mkv", 8_000_000_000),
        ]
        fake_tmdb = SimpleNamespace(configured=lambda: True)
        with patch("app.services.cloud_download_organizer._provider_adapter", return_value=adapter), patch(
            "app.services.cloud_download_organizer.TmdbClient", return_value=fake_tmdb
        ), patch(
            "app.services.cloud_download_organizer.get_settings", return_value=settings
        ), patch(
            "app.services.cloud_download_organizer._process_media_folder", return_value="waiting"
        ) as process:
            result = organizer._run_provider(
                settings,
                "p115",
                ("/媒体库/下载文件夹/01电影",),
            )
        self.assertEqual(1, result["scanned"])
        self.assertEqual(1, result["waiting"])
        self.assertEqual("scope", process.call_args.args[3].file_id)
        self.assertEqual("/媒体库/下载文件夹/01电影", process.call_args.kwargs["source_scope_path"])
        self.assertTrue(process.call_args.kwargs["loose_group_key"].startswith("movie:"))

    def test_fingerprint_a_to_b_to_a_resets_stability_clock_each_transition(self):
        execution_key = "organizer:p115:folder:copy"
        first = _stable_job(execution_key, "p115", "/source", "媒体", "A", "copy")
        with db() as conn:
            conn.execute("UPDATE transfer_jobs SET created_at='2001-01-01 00:00:00' WHERE id=?", (first["id"],))

        changed_to_b = _stable_job(execution_key, "p115", "/source", "媒体", "B", "copy")
        self.assertEqual(first["id"], changed_to_b["id"])
        self.assertNotEqual("2001-01-01 00:00:00", changed_to_b["created_at"])
        self.assertEqual("B", json.loads(changed_to_b["external_provider_status"])["fingerprint"])

        with db() as conn:
            conn.execute("UPDATE transfer_jobs SET created_at='2001-01-01 00:00:00' WHERE id=?", (first["id"],))
        changed_back_to_a = _stable_job(execution_key, "p115", "/source", "媒体", "A", "copy")
        self.assertEqual(first["id"], changed_back_to_a["id"])
        self.assertNotEqual("2001-01-01 00:00:00", changed_back_to_a["created_at"])
        self.assertEqual("A", json.loads(changed_back_to_a["external_provider_status"])["fingerprint"])

    def test_same_fingerprint_stopped_job_is_never_revived(self):
        execution_key = "organizer:p115:folder:copy"
        first = _stable_job(execution_key, "p115", "/source", "媒体", "same", "copy")
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET status='stopped',created_at='2001-01-01 00:00:00' WHERE id=?",
                (first["id"],),
            )
        stopped = _stable_job(execution_key, "p115", "/source", "媒体", "same", "copy")
        self.assertEqual("stopped", stopped["status"])
        self.assertEqual("2001-01-01 00:00:00", stopped["created_at"])

    def test_same_fingerprint_review_retries_after_a_fresh_stable_interval(self):
        execution_key = "organizer:p115:folder:copy"
        first = _stable_job(execution_key, "p115", "/source", "媒体", "same", "copy")
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET status='needs_review',created_at='2001-01-01 00:00:00' WHERE id=?",
                (first["id"],),
            )
        retried = _stable_job(execution_key, "p115", "/source", "媒体", "same", "copy")
        self.assertEqual("ready", retried["status"])
        self.assertNotEqual("2001-01-01 00:00:00", retried["created_at"])

    def test_stopped_job_is_checked_before_move_mutation(self):
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,request_source)
                   VALUES('cloud','p115','stopped','organizer_stopped','cloud_download_organizer')"""
            )
            job_id = int(cursor.lastrowid)
        source = SourceFile(
            "流浪地球2.2023.2160p.mkv",
            8_000_000_000,
            "流浪地球2.2023.2160p.mkv",
            "source-video",
            "source-folder",
        )
        plan = OrganizePlan(
            MediaTarget(101, "movie", "流浪地球2", category="movie", series_year="2023"),
            RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
            "/媒体库/下载文件夹/01电影/流浪地球2.2023",
            "/媒体库/01电影/流浪地球2 (2023)",
            "movie",
            (PlannedFile(source, "流浪地球2.2023.mkv", "/媒体库/01电影/流浪地球2 (2023)"),),
        )
        adapter = RecordingAdapter()
        with self.assertRaises(OrganizerStopped):
            _execute_move(adapter, plan, job_id=job_id)
        self.assertFalse(any(call[0] in {"ensure", "rename", "move", "trash"} for call in adapter.calls))

    def test_disabled_switch_is_checked_at_mutation_boundary(self):
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,request_source)
                   VALUES('cloud','p115','running','organizer_transferring','cloud_download_organizer')"""
            )
            job_id = int(cursor.lastrowid)
        disabled = organizer_settings(cloud_download_organizer_enabled=False)
        with patch("app.services.cloud_download_organizer.get_settings", return_value=disabled):
            with self.assertRaises(OrganizerStopped):
                organizer._ensure_job_active(job_id)

    def test_mode_change_stops_an_inflight_move_job(self):
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,request_source,execution_key,
                   source_file,save_path)
                   VALUES('cloud','p115','running','organizer_transferring','cloud_download_organizer',
                   'organizer:p115:folder:move',?,?)""",
                (
                    "/媒体库/下载文件夹/01电影/流浪地球2.2023",
                    "/媒体库/01电影/流浪地球2 (2023)",
                ),
            )
            job_id = int(cursor.lastrowid)
        switched = organizer_settings(
            cloud_download_organizer_enabled=True,
            cloud_download_organizer_mode="copy",
        )
        with patch("app.services.cloud_download_organizer.get_settings", return_value=switched):
            with self.assertRaisesRegex(OrganizerStopped, "模式已变更"):
                organizer._ensure_job_active(job_id)

    def test_move_batches_mutations_and_observes_stop_between_batches(self):
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,request_source)
                   VALUES('cloud','p115','running','organizer_transferring','cloud_download_organizer')"""
            )
            job_id = int(cursor.lastrowid)

        class StopAfterFirstMoveAdapter(RecordingAdapter):
            def move(inner_self, file_ids, destination_id):
                super().move(file_ids, destination_id)
                with db() as conn:
                    conn.execute("UPDATE transfer_jobs SET status='stopped' WHERE id=?", (job_id,))

        plan = self._many_file_plan(205)
        adapter = StopAfterFirstMoveAdapter()
        adapter.source_tree = tuple(
            RemoteEntry(
                item.source.provider_file_id,
                "source-folder",
                item.source.name,
                item.source.size,
            )
            for item in plan.files
        )
        enabled = organizer_settings(cloud_download_organizer_enabled=True)
        with patch("app.services.cloud_download_organizer.get_settings", return_value=enabled):
            with self.assertRaises(OrganizerStopped):
                _execute_move(adapter, plan, job_id=job_id)
        move_calls = [call for call in adapter.calls if call[0] == "move"]
        self.assertEqual(1, len(move_calls))
        self.assertLessEqual(len(move_calls[0][1]), organizer.REMOTE_MUTATION_BATCH_SIZE)

    def test_scope_revocation_stops_before_second_move_batch(self):
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,request_source,execution_key,
                   source_file,save_path)
                   VALUES('cloud','p115','running','organizer_transferring','cloud_download_organizer',
                   'organizer:p115:folder:move',?,?)""",
                (
                    "/媒体库/下载文件夹/01电影/流浪地球2.2023",
                    "/媒体库/01电影/批量媒体 (2026)",
                ),
            )
            job_id = int(cursor.lastrowid)

        authorized = organizer_settings(
            cloud_download_organizer_enabled=True,
            cloud_download_organizer_mode="move",
        )
        revoked = organizer_settings(
            cloud_download_organizer_enabled=True,
            cloud_download_organizer_mode="move",
            p115_cloud_download_organizer_directories_json="[]",
        )

        class RevokeAfterFirstMoveAdapter(RecordingAdapter):
            revoked = False

            def move(inner_self, file_ids, destination_id):
                super().move(file_ids, destination_id)
                inner_self.revoked = True

        plan = self._many_file_plan(205)
        adapter = RevokeAfterFirstMoveAdapter()
        adapter.source_tree = tuple(
            RemoteEntry(item.source.provider_file_id, "source-folder", item.source.name, item.source.size)
            for item in plan.files
        )
        with patch(
            "app.services.cloud_download_organizer.get_settings",
            side_effect=lambda: revoked if adapter.revoked else authorized,
        ):
            with self.assertRaises(OrganizerStopped):
                _execute_move(adapter, plan, job_id=job_id)
        move_calls = [call for call in adapter.calls if call[0] == "move"]
        self.assertEqual(1, len(move_calls))

    def test_new_arrival_after_write_start_enters_fresh_stability_cycle(self):
        settings = organizer_settings(cloud_download_organizer_enabled=True)
        plan = self._movie_plan()
        expected = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
                False,
                "流浪地球2.2023.2160p.mkv",
            ),
        )
        current = expected + (
            RemoteEntry("new-video", "source-folder", "流浪地球2.2023.CD2.mkv", 7_000_000_000, False, "CD2.mkv"),
        )
        fingerprint = organizer._inventory_fingerprint(plan.source_folder, expected)
        execution_key = "organizer:p115:new-arrival:copy"
        job = _stable_job(execution_key, "p115", plan.source_path, plan.source_folder.name, fingerprint, "copy")
        serialized = [{**asdict(item), "source": asdict(item.source)} for item in plan.files]
        organizer._update_job_plan(int(job["id"]), plan, serialized, fingerprint, "copy", source_entries=expected)
        with db() as conn:
            row = conn.execute(
                "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
                (job["id"],),
            ).fetchone()
            state = json.loads(row["external_provider_status"])
            state["write_started"] = True
            state["write_receipts"] = {
                "source-video": {
                    "path": plan.media_path,
                    "file_id": "copied-before-new-arrival",
                    "name": "流浪地球2.2023.mkv",
                    "size": 8_000_000_000,
                }
            }
            conn.execute(
                "UPDATE transfer_jobs SET status='failed',external_provider_status=? WHERE id=?",
                (json.dumps(state, ensure_ascii=False), job["id"]),
            )
        adapter = RecordingAdapter()
        adapter.source_tree = current
        with patch("app.services.cloud_download_organizer.get_settings", return_value=settings):
            outcome = organizer._recover_started_job(
                settings,
                adapter,
                plan.source_folder,
                plan.source_path,
                current,
                execution_key,
            )
        self.assertIsNone(outcome)
        with db() as conn:
            row = conn.execute(
                "SELECT status,stage,external_provider_status FROM transfer_jobs WHERE id=?",
                (job["id"],),
            ).fetchone()
        state = json.loads(row["external_provider_status"])
        self.assertEqual("ready", row["status"])
        self.assertEqual("organizer_waiting_stable", row["stage"])
        self.assertFalse(state["write_started"])
        self.assertEqual(organizer._inventory_fingerprint(plan.source_folder, current), state["fingerprint"])
        self.assertEqual(
            "copied-before-new-arrival",
            state["write_receipts"]["source-video"]["file_id"],
        )
        adapter.path_ids[plan.media_path] = "target"
        adapter.directories["target"] = [
            RemoteEntry("copied-before-new-arrival", "target", "流浪地球2.2023.mkv", 8_000_000_000),
        ]
        bindings = {**organizer._write_receipt_bindings(int(job["id"])), **organizer._verified_target_bindings(int(job["id"]))}
        _preflight_destinations(adapter, plan, reusable_targets=bindings)
        self.assertFalse(any(call[0] in {"ensure", "copy", "move", "rename", "trash"} for call in adapter.calls))

    def test_completed_move_is_finalized_before_nonvideo_new_arrival_is_left_alone(self):
        settings = organizer_settings(
            cloud_download_organizer_enabled=True,
            cloud_download_organizer_mode="move",
        )
        plan = self._movie_plan()
        expected = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
                False,
                "流浪地球2.2023.2160p.mkv",
            ),
        )
        current = (RemoteEntry("new-readme", "source-folder", "new-readme.txt", 100, False, "new-readme.txt"),)
        fingerprint = organizer._inventory_fingerprint(plan.source_folder, expected)
        execution_key = "organizer:p115:move-before-readme:move"
        job = _stable_job(execution_key, "p115", plan.source_path, plan.source_folder.name, fingerprint, "move")
        serialized = [{**asdict(item), "source": asdict(item.source)} for item in plan.files]
        organizer._update_job_plan(int(job["id"]), plan, serialized, fingerprint, "move", source_entries=expected)
        with db() as conn:
            row = conn.execute(
                "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
                (job["id"],),
            ).fetchone()
            state = json.loads(row["external_provider_status"])
            state["write_started"] = True
            conn.execute(
                "UPDATE transfer_jobs SET status='failed',external_provider_status=? WHERE id=?",
                (json.dumps(state, ensure_ascii=False), job["id"]),
            )
        adapter = RecordingAdapter()
        adapter.source_tree = current
        adapter.path_ids[plan.media_path] = "target"
        adapter.directories["target"] = [
            RemoteEntry("source-video", "target", "流浪地球2.2023.mkv", 8_000_000_000),
        ]
        with patch("app.services.cloud_download_organizer.get_settings", return_value=settings), patch(
            "app.services.cloud_download_organizer.run_post_transfer_pipeline"
        ) as pipeline:
            outcome = organizer._recover_started_job(
                settings,
                adapter,
                plan.source_folder,
                plan.source_path,
                current,
                execution_key,
            )
        self.assertEqual("organized", outcome)
        pipeline.assert_called_once()
        with db() as conn:
            row = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job["id"],)).fetchone()
        self.assertEqual("done", row["status"])
        self.assertTrue(any(item.file_id == "new-readme" for item in adapter.source_tree))
        self.assertFalse(any(call[0] in {"move", "rename", "trash"} for call in adapter.calls))

    def test_started_copy_job_recovers_when_all_targets_are_already_verified(self):
        settings = organizer_settings(cloud_download_organizer_enabled=True)
        plan = self._movie_plan()
        entries = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
                False,
                "流浪地球2.2023.2160p.mkv",
            ),
        )
        fingerprint = organizer._inventory_fingerprint(plan.source_folder, entries)
        execution_key = "organizer:p115:folder:copy"
        job = _stable_job(
            execution_key,
            "p115",
            plan.source_path,
            plan.source_folder.name,
            fingerprint,
            "copy",
        )
        serialized = [{**asdict(item), "source": asdict(item.source)} for item in plan.files]
        organizer._update_job_plan(
            int(job["id"]),
            plan,
            serialized,
            fingerprint,
            "copy",
            source_entries=entries,
        )
        with db() as conn:
            row = conn.execute(
                "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
                (job["id"],),
            ).fetchone()
            state = json.loads(row["external_provider_status"])
            state["write_started"] = True
            state["write_receipts"] = {
                "source-video": {
                    "path": plan.media_path,
                    "file_id": "copied-target",
                    "name": "流浪地球2.2023.mkv",
                    "size": 8_000_000_000,
                }
            }
            conn.execute(
                """UPDATE transfer_jobs SET status='failed',stage='organizer_failed',external_provider_status=?
                   WHERE id=?""",
                (json.dumps(state, ensure_ascii=False), job["id"]),
            )

        adapter = RecordingAdapter()
        adapter.source_tree = entries
        adapter.path_ids[plan.media_path] = "target"
        adapter.directories["target"] = [
            RemoteEntry("copied-target", "target", "流浪地球2.2023.mkv", 8_000_000_000),
        ]
        with patch("app.services.cloud_download_organizer.get_settings", return_value=settings), patch(
            "app.services.cloud_download_organizer.run_post_transfer_pipeline"
        ) as pipeline:
            outcome = organizer._recover_started_job(
                settings,
                adapter,
                plan.source_folder,
                plan.source_path,
                entries,
                execution_key,
            )
        self.assertEqual("organized", outcome)
        self.assertFalse(any(call[0] in {"ensure", "copy", "move", "rename", "trash"} for call in adapter.calls))
        pipeline.assert_called_once()
        with db() as conn:
            row = conn.execute("SELECT status FROM transfer_jobs WHERE id=?", (job["id"],)).fetchone()
        self.assertEqual("done", row["status"])

    def test_started_copy_does_not_claim_external_same_name_same_size_target(self):
        settings = organizer_settings(cloud_download_organizer_enabled=True)
        plan = self._movie_plan()
        entries = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
                False,
                "流浪地球2.2023.2160p.mkv",
            ),
        )
        fingerprint = organizer._inventory_fingerprint(plan.source_folder, entries)
        execution_key = "organizer:p115:external-target:copy"
        job = _stable_job(execution_key, "p115", plan.source_path, plan.source_folder.name, fingerprint, "copy")
        serialized = [{**asdict(item), "source": asdict(item.source)} for item in plan.files]
        organizer._update_job_plan(int(job["id"]), plan, serialized, fingerprint, "copy", source_entries=entries)
        with db() as conn:
            row = conn.execute(
                "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
                (job["id"],),
            ).fetchone()
            state = json.loads(row["external_provider_status"])
            state["write_started"] = True
            state["write_receipts"] = {
                "source-video": {
                    "path": plan.media_path,
                    "file_id": "expected-copy-id",
                    "name": "流浪地球2.2023.mkv",
                    "size": 8_000_000_000,
                }
            }
            conn.execute(
                "UPDATE transfer_jobs SET status='failed',external_provider_status=? WHERE id=?",
                (json.dumps(state, ensure_ascii=False), job["id"]),
            )
        adapter = RecordingAdapter()
        adapter.source_tree = entries
        adapter.path_ids[plan.media_path] = "target"
        adapter.directories["target"] = [
            RemoteEntry("external-file-id", "target", "流浪地球2.2023.mkv", 8_000_000_000),
        ]
        with patch("app.services.cloud_download_organizer.get_settings", return_value=settings), patch(
            "app.services.cloud_download_organizer.run_post_transfer_pipeline"
        ) as pipeline:
            outcome = organizer._recover_started_job(
                settings,
                adapter,
                plan.source_folder,
                plan.source_path,
                entries,
                execution_key,
            )
        self.assertEqual("review", outcome)
        pipeline.assert_not_called()
        self.assertFalse(any(call[0] in {"ensure", "copy", "move", "rename", "trash"} for call in adapter.calls))

    def test_direct_move_job_recovers_after_all_source_files_left_scope(self):
        settings = organizer_settings(
            cloud_download_organizer_enabled=True,
            cloud_download_organizer_mode="move",
        )
        scope_path = "/媒体库/下载文件夹/01电影"
        destination = "/媒体库/01电影/流浪地球2 (2023)"
        source_entry = RemoteEntry(
            "source-video", "scope", "流浪地球2.2023.2160p.mkv", 8_000_000_000, False,
            "流浪地球2.2023.2160p.mkv",
        )
        group_key = organizer._loose_media_groups((source_entry,), "movie")[0][0]
        plan = OrganizePlan(
            MediaTarget(101, "movie", "流浪地球2", category="movie", series_year="2023"),
            RemoteEntry("scope", "", "流浪地球2.2023", is_dir=True),
            f"{scope_path}/流浪地球2.2023",
            destination,
            "movie",
            (
                PlannedFile(
                    SourceFile(source_entry.name, source_entry.size, source_entry.name, source_entry.file_id, "scope"),
                    "流浪地球2.2023.mkv",
                    destination,
                ),
            ),
            scope_path,
            group_key,
        )
        fingerprint = organizer._inventory_fingerprint(plan.source_folder, (source_entry,))
        execution_key = "organizer:p115:loose:recover-direct:move"
        job = _stable_job(execution_key, "p115", plan.source_path, plan.source_folder.name, fingerprint, "move")
        serialized = [{**asdict(item), "source": asdict(item.source)} for item in plan.files]
        organizer._update_job_plan(
            int(job["id"]),
            plan,
            serialized,
            fingerprint,
            "move",
            source_entries=(source_entry,),
        )
        with db() as conn:
            row = conn.execute(
                "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
                (job["id"],),
            ).fetchone()
            state = json.loads(row["external_provider_status"])
            state["write_started"] = True
            conn.execute(
                "UPDATE transfer_jobs SET status='failed',external_provider_status=? WHERE id=?",
                (json.dumps(state, ensure_ascii=False), job["id"]),
            )
        adapter = RecordingAdapter()
        adapter.directories["scope"] = [RemoteEntry("unrelated", "scope", "keep.txt", 10)]
        adapter.path_ids[destination] = "target"
        adapter.directories["target"] = [
            RemoteEntry("source-video", "target", "流浪地球2.2023.mkv", 8_000_000_000),
        ]
        with patch("app.services.cloud_download_organizer.get_settings", return_value=settings), patch(
            "app.services.cloud_download_organizer.run_post_transfer_pipeline"
        ) as pipeline:
            outcomes = organizer._recover_started_loose_jobs(settings, adapter, scope_path)
        self.assertEqual({execution_key: "organized"}, outcomes)
        pipeline.assert_called_once()
        self.assertTrue(any(item.file_id == "unrelated" for item in adapter.directories["scope"]))
        self.assertFalse(any(call[0] in {"copy", "move", "rename", "trash"} for call in adapter.calls))

    def test_move_accepts_rename_applied_before_connection_error_and_records_receipt(self):
        class AppliedThenDisconnectedAdapter(RecordingAdapter):
            def rename(inner_self, pairs):
                super().rename(pairs)
                raise QuarkError("夸克连接失败（URLError）")

        plan = self._movie_plan()
        adapter = AppliedThenDisconnectedAdapter()
        adapter.source_tree = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
            ),
        )
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(target,provider,status,stage,request_source,execution_key,
                   source_file,save_path,external_provider_status)
                   VALUES('cloud','p115','running','organizer_renaming','cloud_download_organizer',
                   'organizer:p115:folder:move',?,?, '{}')""",
                (plan.source_path, plan.media_path),
            )
            job_id = int(cursor.lastrowid)
        settings = organizer_settings(
            cloud_download_organizer_enabled=True,
            cloud_download_organizer_mode="move",
        )
        with patch("app.services.cloud_download_organizer.get_settings", return_value=settings):
            _execute_move(adapter, plan, job_id=job_id)
        self.assertEqual(1, len([call for call in adapter.calls if call[0] == "rename"]))
        self.assertTrue(any(call[0] == "move" for call in adapter.calls))
        with db() as conn:
            row = conn.execute(
                "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        state = json.loads(row["external_provider_status"])
        self.assertEqual(
            "reconciled_after_error",
            state["rename_receipts"]["source-video"]["result"],
        )

    def test_move_rename_failure_before_apply_stops_with_exact_file_and_later_resumes(self):
        class DisconnectBeforeApplyAdapter(RecordingAdapter):
            provider = "quark"
            fail = True

            def rename(inner_self, pairs):
                if inner_self.fail:
                    inner_self.calls.append(("rename", tuple(pairs)))
                    raise QuarkError("夸克连接失败（URLError）")
                super().rename(pairs)

        plan = self._movie_plan()
        adapter = DisconnectBeforeApplyAdapter()
        adapter.source_tree = (
            RemoteEntry(
                "source-video",
                "source-folder",
                "流浪地球2.2023.2160p.mkv",
                8_000_000_000,
            ),
        )
        with patch("app.services.cloud_download_organizer.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "第 1/1 个.*2160p.*流浪地球2.2023.mkv"):
                _execute_move(adapter, plan)
        self.assertEqual("流浪地球2.2023.2160p.mkv", adapter.source_tree[0].name)
        adapter.fail = False
        _execute_move(adapter, plan)
        self.assertEqual(4, len([call for call in adapter.calls if call[0] == "rename"]))
        self.assertTrue(any(call[0] == "move" for call in adapter.calls))

    def test_move_retry_skips_files_renamed_before_later_file_failed(self):
        destination = "/媒体库/01电影/测试剧 (2026)/Season 1"
        files = tuple(
            PlannedFile(
                SourceFile(
                    f"{episode:02d}-4K.mp4",
                    1_000_000_000 + episode,
                    f"{episode:02d}-4K.mp4",
                    f"source-{episode}",
                    "source-folder",
                ),
                f"测试剧.2026.S01E{episode:02d}.mp4",
                destination,
                1,
            )
            for episode in (1, 2)
        )
        plan = OrganizePlan(
            MediaTarget(999, "tv", "测试剧", category="tv", series_year="2026"),
            RemoteEntry("source-folder", "scope", "测试剧 (2026)", is_dir=True),
            "/媒体库/下载文件夹/01电影/测试剧 (2026)",
            "/媒体库/01电影/测试剧 (2026)",
            "tv",
            files,
        )

        class FailSecondOnceAdapter(RecordingAdapter):
            provider = "quark"
            failed = False

            def rename(inner_self, pairs):
                if pairs[0][0] == "source-2" and not inner_self.failed:
                    inner_self.failed = True
                    inner_self.calls.append(("rename", tuple(pairs)))
                    raise QuarkError("夸克连接失败（URLError）")
                super().rename(pairs)

        adapter = FailSecondOnceAdapter()
        adapter.directories["scope"] = [
            RemoteEntry("source-folder", "scope", "测试剧 (2026)", is_dir=True),
        ]
        adapter.source_tree = tuple(
            RemoteEntry(item.source.provider_file_id, "source-folder", item.source.name, item.source.size)
            for item in files
        )
        with patch("app.services.cloud_download_organizer.time.sleep"):
            _execute_move(adapter, plan)
        renamed_ids = [call[1][0][0] for call in adapter.calls if call[0] == "rename"]
        self.assertEqual(["source-1", "source-2", "source-2"], renamed_ids)
        self.assertTrue(any(call[0] == "move" for call in adapter.calls))

    @staticmethod
    def _movie_plan():
        source = SourceFile(
            "流浪地球2.2023.2160p.mkv",
            8_000_000_000,
            "流浪地球2.2023.2160p.mkv",
            "source-video",
            "source-folder",
        )
        return OrganizePlan(
            MediaTarget(101, "movie", "流浪地球2", category="movie", series_year="2023"),
            RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
            "/媒体库/下载文件夹/01电影/流浪地球2.2023",
            "/媒体库/01电影/流浪地球2 (2023)",
            "movie",
            (PlannedFile(source, "流浪地球2.2023.mkv", "/媒体库/01电影/流浪地球2 (2023)"),),
        )

    @staticmethod
    def _many_file_plan(count):
        destination = "/媒体库/01电影/批量媒体 (2026)"
        files = tuple(
            PlannedFile(
                SourceFile(
                    f"批量媒体.{index:03d}.mkv",
                    1_000_000_000 + index,
                    f"批量媒体.{index:03d}.mkv",
                    f"source-{index}",
                    "source-folder",
                ),
                f"批量媒体.{index:03d}.mkv",
                destination,
            )
            for index in range(count)
        )
        return OrganizePlan(
            MediaTarget(999, "movie", "批量媒体", category="movie", series_year="2026"),
            RemoteEntry("source-folder", "scope", "流浪地球2.2023", is_dir=True),
            "/媒体库/下载文件夹/01电影/流浪地球2.2023",
            destination,
            "movie",
            files,
        )


if __name__ == "__main__":
    unittest.main()
