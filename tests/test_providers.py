import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.transfers import list_transfers
from app.api.review import _run_confirmed_candidate, prepare_candidate_confirmation
from app.core.config import get_settings
from app.db.database import db, init_db
from app.domain.media import LinkResolution, MediaTarget, RenamePair
from app.providers.base import ProviderCapability, TransferPlan
from app.providers.moviepilot_115 import MoviePilot115TransferProvider
from app.providers.p115 import P115TransferProvider
from app.providers.qas import QasTransferProvider
from app.providers.quark import QuarkTransferProvider
from app.providers.registry import resolve_provider_key
from app.providers.status import normalize_provider_stage, transfer_status_for_stage


class FakeQas:
    def __init__(self):
        self.runs = []

    def configured(self):
        return True

    def tasklist(self):
        return []

    def run_task(self, task):
        self.runs.append(task)
        return {"success": True, "confirmed": True}

    def savepath_detail(self, path):
        return {
            "success": True,
            "data": {"list": [{"file_name": "测试.2026.mkv", "size": 10, "dir": False}]},
        }


class FakeMoviePilot115:
    def configured(self):
        return True

    def submit_share(self, share_url):
        from app.clients.moviepilot_115 import MoviePilot115Submission

        return MoviePilot115Submission(True, "转存成功", "/媒体/电影", "123")


class FakeQuark:
    def __init__(self):
        from types import SimpleNamespace

        self.settings = SimpleNamespace(
            quark_root_path="/quark",
            quark_staging_path="/.media-index-staging",
            cloud_save_path="/strm",
            quark_request_timeout_seconds=1,
            provider_cloud_download_path=lambda provider: "/quark/云下载",
        )
        self.calls = []
        self._list_calls = 0
        self._renamed_name = "测试.2026.mkv"

    def configured(self):
        return True

    def inspect_share(self, _share_url):
        from app.clients.quark import QuarkShareFile, QuarkShareRef, QuarkShareSnapshot

        return QuarkShareSnapshot(
            share=QuarkShareRef("share"),
            share_token="token",
            title="来源.mkv",
            files=(QuarkShareFile("source", "0", "来源.mkv", 42, share_fid_token="fid-token"),),
        )

    def ensure_directory(self, path):
        self.calls.append(("ensure", path))
        return "staging" if ".media-index-staging" in path else "final"

    def directory_id(self, _path):
        self.calls.append(("lookup", _path))
        return "final"

    def list_directory(self, _directory):
        from app.clients.quark import QuarkFile

        self._list_calls += 1
        if self._list_calls == 1:
            return ()
        if self._list_calls == 2:
            return (QuarkFile("received", "staging", "来源.mkv", 42),)
        return (QuarkFile("received", "final", self._renamed_name, 42),)

    def list_directory_complete(self, directory):
        return self.list_directory(directory)

    def save_share_files(self, _snapshot, file_ids, destination_id):
        self.calls.append(("save", tuple(file_ids), destination_id))
        return "task"

    def task(self, _task_id, *, retry_index=0):
        self.calls.append(("task", _task_id, retry_index))
        return {"status": "done"}

    def rename_file(self, file_id, name):
        self.calls.append(("rename", file_id, name))
        self._renamed_name = name

    def move_files(self, file_ids, destination_id):
        self.calls.append(("move", tuple(file_ids), destination_id))
        return "move-task"

    def wait_task(self, task_id):
        self.calls.append(("wait", task_id))
        return {"status": "done"}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "ENABLED_CLOUD_PROVIDERS": "quark",
                "DEFAULT_CLOUD_PROVIDER": "quark",
                "CLOUD_SAVE_PATH": "/strm",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_qas_provider_preserves_execution_and_returns_generic_stage(self):
        client = FakeQas()
        provider = QasTransferProvider(client)
        target = MediaTarget(1, "movie", "测试", series_year="2026")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/example",
            rename_pairs=(RenamePair("source.mkv", "source\\.mkv", "测试.2026.mkv"),),
        )
        result = provider.execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))

        self.assertTrue(result.ok)
        self.assertTrue(result.confirmed)
        self.assertEqual("provider_completed", result.stage)
        self.assertEqual(1, len(client.runs))
        self.assertIn(ProviderCapability.EXECUTION_RECONCILE, provider.capabilities())

    def test_provider_selection_defaults_to_native_quark_and_requires_configuration(self):
        with self.assertRaisesRegex(ValueError, "尚未配置"):
            resolve_provider_key("cloud")
        self.assertEqual("", resolve_provider_key("local"))
        with self.assertRaisesRegex(ValueError, "尚未配置"):
            with patch.dict(os.environ, {"ENABLED_CLOUD_PROVIDERS": "qas,moviepilot_115"}):
                get_settings.cache_clear()
                resolve_provider_key("cloud", "moviepilot_115")

    def test_local_115_requires_enabled_provider_and_cookie(self):
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "p115",
                "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
            },
        ):
            get_settings.cache_clear()
            self.assertEqual("p115", resolve_provider_key("local", "p115"))

    def test_default_provider_falls_back_to_first_enabled_provider(self):
        with patch.dict(
            os.environ,
            {"ENABLED_CLOUD_PROVIDERS": "p115", "DEFAULT_CLOUD_PROVIDER": "qas"},
        ):
            get_settings.cache_clear()
            self.assertEqual("p115", get_settings().default_provider_key())

    def test_native_quark_requires_enabled_provider_and_cookie(self):
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "quark",
                "DEFAULT_CLOUD_PROVIDER": "quark",
                "QUARK_COOKIE": "__puus=abc; __pus=def",
            },
        ):
            get_settings.cache_clear()
            self.assertEqual("quark", resolve_provider_key("cloud"))

    def test_native_quark_provider_stages_renames_moves_and_confirms(self):
        provider = QuarkTransferProvider(FakeQuark())
        target = MediaTarget(1, "movie", "测试", series_year="2026", category="movie")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/share",
            rename_pairs=(RenamePair("来源.mkv", "来源\\.mkv", "测试.2026.mkv", source_id="source", source_size=42),),
        )
        with patch.dict(os.environ, {"QUARK_ROOT_PATH": "/quark", "QUARK_CATEGORY_PATHS_JSON": '{"movie":"/movie"}'}, clear=False):
            get_settings.cache_clear()
            result = provider.execute(TransferPlan(target, resolution, "/quark/movie/测试 (2026)"))
        self.assertTrue(result.ok)
        self.assertTrue(result.confirmed)
        self.assertEqual("provider_completed", result.stage)
        self.assertEqual(1, result.executed_items)
        self.assertEqual(
            ({"file_id": "received", "parent_id": "final", "file_name": "测试.2026.mkv", "size": 42, "path": "/quark/movie/测试 (2026)"},),
            result.outputs,
        )
        self.assertIn(ProviderCapability.EXECUTION_RECONCILE, provider.capabilities())
        self.assertIn(("save", ("source",), "staging"), provider.client.calls)
        self.assertIn(("rename", "received", "测试.2026.mkv"), provider.client.calls)
        self.assertIn(("move", ("received",), "final"), provider.client.calls)
        self.assertIn(("wait", "move-task"), provider.client.calls)

    def test_native_quark_skips_noop_rename_for_numeric_only_direct_link(self):
        client = FakeQuark()
        client._renamed_name = "来源.mkv"
        provider = QuarkTransferProvider(client)
        target = MediaTarget(0, "tv", "下载链接", category="tv")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/share",
            rename_pairs=(RenamePair("来源.mkv", "来源\\.mkv", "来源.mkv", source_id="source", source_size=42),),
        )

        result = provider.execute(
            TransferPlan(
                target,
                resolution,
                "/quark/云下载/03电视剧/来源",
                destination_scope="cloud_download",
                cloud_download_child="03电视剧",
            )
        )

        self.assertTrue(result.ok, result.message)
        self.assertNotIn(("rename", "received", "来源.mkv"), client.calls)
        self.assertIn(("move", ("received",), "final"), client.calls)

    def test_native_quark_waits_for_task_and_stable_metadata_before_matching(self):
        class EventuallyConsistentQuark(FakeQuark):
            def __init__(self):
                super().__init__()
                self.polls = 0

            def task(self, task_id, *, retry_index=0):
                self.calls.append(("task", task_id, retry_index))
                self.polls += 1
                return {"status": "pending" if self.polls == 1 else "done"}

            def list_directory(self, directory):
                from app.clients.quark import QuarkFile

                if directory == "staging":
                    if self.polls == 0:
                        return ()
                    size = 0 if self.polls == 1 else 42
                    return (QuarkFile("received", "staging", "来源.mkv", size),)
                return (QuarkFile("received", "final", self._renamed_name, 42),)

        provider = QuarkTransferProvider(EventuallyConsistentQuark())
        target = MediaTarget(1, "movie", "测试", series_year="2026", category="movie")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/share",
            rename_pairs=(RenamePair("来源.mkv", "来源\\.mkv", "测试.2026.mkv", source_id="source", source_size=42),),
        )

        with patch("app.providers.quark.time.sleep"):
            result = provider.execute(
                TransferPlan(
                    target,
                    resolution,
                    "/quark/云下载/03电视剧",
                    destination_scope="cloud_download",
                    cloud_download_child="03电视剧",
                )
            )

        self.assertTrue(result.ok, result.message)
        self.assertIn(("task", "task", 0), provider.client.calls)
        self.assertIn(("task", "task", 1), provider.client.calls)

    def test_native_quark_reports_the_operation_that_returned_http_400(self):
        class FailingStagingQuark(FakeQuark):
            def ensure_directory(self, _path):
                from app.clients.quark import QuarkError

                raise QuarkError("夸克请求失败（HTTP 400）")

        provider = QuarkTransferProvider(FailingStagingQuark())
        target = MediaTarget(1, "tv", "测试剧", series_year="2026", category="tv")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/share",
            rename_pairs=(
                RenamePair("来源.mkv", "来源\\.mkv", "测试剧.2026.S01E01.mkv", source_id="source", source_size=42),
            ),
        )

        result = provider.execute(
            TransferPlan(
                target,
                resolution,
                "/quark/云下载/03电视剧/测试剧 (2026)",
                destination_scope="cloud_download",
                cloud_download_child="03电视剧",
            )
        )

        self.assertFalse(result.ok)
        self.assertIn("创建转存暂存目录失败", result.message)
        self.assertIn("HTTP 400", result.message)

    def test_native_quark_submits_nested_share_parents_separately(self):
        class NestedShareQuark(FakeQuark):
            def __init__(self):
                super().__init__()
                self.staging = {}
                self.final = []

            def inspect_share(self, _share_url):
                from app.clients.quark import QuarkShareFile, QuarkShareRef, QuarkShareSnapshot

                return QuarkShareSnapshot(
                    share=QuarkShareRef("share"),
                    share_token="token",
                    title="电视剧",
                    files=(
                        QuarkShareFile("source-1", "season-1", "S01E01.mkv", 41, share_fid_token="token-1"),
                        QuarkShareFile("source-2", "season-2", "S02E01.mkv", 42, share_fid_token="token-2"),
                    ),
                )

            def ensure_directory(self, path):
                self.calls.append(("ensure", path))
                if ".media-index-staging" not in path:
                    return "final"
                directory_id = f"staging-{len(self.staging) + 1}"
                self.staging[directory_id] = []
                return directory_id

            def list_directory(self, directory):
                return tuple(self.final if directory == "final" else self.staging.get(directory, ()))

            def save_share_files(self, snapshot, file_ids, destination_id):
                from app.clients.quark import QuarkFile

                selected = [item for item in snapshot.files if item.file_id in file_ids]
                if len({item.parent_id for item in selected}) != 1:
                    raise AssertionError("mixed share parents were submitted together")
                self.calls.append(("save", tuple(file_ids), destination_id))
                self.staging[destination_id].extend(
                    QuarkFile(f"received-{item.file_id}", destination_id, item.name, item.size)
                    for item in selected
                )
                return f"task-{destination_id}"

            def rename_file(self, file_id, name):
                from app.clients.quark import QuarkFile

                self.calls.append(("rename", file_id, name))
                for directory_id, items in self.staging.items():
                    self.staging[directory_id] = [
                        QuarkFile(item.file_id, item.parent_id, name if item.file_id == file_id else item.name, item.size)
                        for item in items
                    ]

            def move_files(self, file_ids, destination_id):
                selected = set(file_ids)
                self.calls.append(("move", tuple(file_ids), destination_id))
                self.final = [
                    item
                    for items in self.staging.values()
                    for item in items
                    if item.file_id in selected
                ]
                return "move-task"

        client = NestedShareQuark()
        provider = QuarkTransferProvider(client)
        target = MediaTarget(1, "tv", "测试剧", series_year="2026", category="tv")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/share",
            rename_pairs=(
                RenamePair("S01E01.mkv", "", "测试剧.S01E01.mkv", source_id="source-1", source_size=41),
                RenamePair("S02E01.mkv", "", "测试剧.S02E01.mkv", source_id="source-2", source_size=42),
            ),
        )

        result = provider.execute(
            TransferPlan(
                target,
                resolution,
                "/quark/云下载/03电视剧",
                destination_scope="cloud_download",
                cloud_download_child="03电视剧",
            )
        )

        self.assertTrue(result.ok, result.message)
        save_calls = [call for call in client.calls if call[0] == "save"]
        self.assertEqual([("source-1",), ("source-2",)], [call[1] for call in save_calls])

    def test_native_quark_direct_link_allows_only_download_root_direct_children(self):
        target = MediaTarget(1, "movie", "下载链接", category="movie")
        for replacement in ("来源.mkv", "黑夜告白.2026.mkv"):
            with self.subTest(replacement=replacement):
                client = FakeQuark()
                client._renamed_name = "来源.mkv"
                provider = QuarkTransferProvider(client)
                resolution = LinkResolution(
                    True,
                    "ready",
                    "ready",
                    share_url="https://pan.quark.cn/s/share",
                    rename_pairs=(
                        RenamePair(
                            "来源.mkv",
                            "来源\\.mkv",
                            replacement,
                            reasons=("direct_link", "native_quark"),
                            source_id="source",
                            source_size=42,
                        ),
                    ),
                )

                result = provider.execute(TransferPlan(target, resolution, "/quark/云下载/03电视剧"))

                self.assertTrue(result.ok)
                self.assertEqual(replacement, result.outputs[0]["file_name"])

        direct_resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/share",
            rename_pairs=(
                RenamePair(
                    "来源.mkv",
                    "来源\\.mkv",
                    "来源.mkv",
                    reasons=("direct_link", "native_quark"),
                    source_id="source",
                    source_size=42,
                ),
            ),
        )
        nested = QuarkTransferProvider(FakeQuark()).execute(
            TransferPlan(target, direct_resolution, "/quark/云下载/03电视剧/剧名")
        )
        generic_resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/share",
            rename_pairs=(RenamePair("来源.mkv", "来源\\.mkv", "来源.mkv", reasons=("manual",)),),
        )
        generic = QuarkTransferProvider(FakeQuark()).execute(
            TransferPlan(target, generic_resolution, "/quark/云下载/03电视剧")
        )

        self.assertFalse(nested.ok)
        self.assertFalse(generic.ok)

    def test_native_quark_accepts_only_marked_staging_path_outside_formal_root(self):
        client = FakeQuark()
        client.settings.provider_cloud_download_path = lambda _provider: "/独立云下载"
        provider = QuarkTransferProvider(client)
        target = MediaTarget(1, "movie", "测试", series_year="2026", category="movie")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://pan.quark.cn/s/share",
            rename_pairs=(
                RenamePair(
                    "来源.mkv",
                    "来源\\.mkv",
                    "测试.2026.mkv",
                    source_id="source",
                    source_size=42,
                ),
            ),
        )
        staging_path = "/独立云下载/01电影/测试 (2026)"

        accepted = provider.execute(
            TransferPlan(
                target,
                resolution,
                staging_path,
                destination_scope="cloud_download",
                cloud_download_child="01电影",
            )
        )
        rejected = QuarkTransferProvider(FakeQuark()).execute(
            TransferPlan(target, resolution, staging_path)
        )

        self.assertTrue(accepted.ok, accepted.message)
        self.assertIn(("ensure", staging_path), client.calls)
        self.assertFalse(rejected.ok)
        self.assertIn("超出允许", rejected.message)

    def test_native_quark_save_path_inspection_does_not_create_a_directory(self):
        provider = QuarkTransferProvider(FakeQuark())
        result = provider.inspect_save_path("/strm/movie/测试 (2026)")

        self.assertTrue(result["success"])
        self.assertEqual(
            [{"name": "strm"}, {"name": "movie"}, {"name": "测试 (2026)"}],
            result["data"]["paths"],
        )
        self.assertIn(("lookup", "/quark/movie/测试 (2026)"), provider.client.calls)
        self.assertNotIn(("ensure", "/quark/movie/测试 (2026)"), provider.client.calls)

    def test_native_quark_missing_path_is_a_verified_empty_result(self):
        provider = QuarkTransferProvider(FakeQuark())
        provider.client.directory_id = lambda _path: ""

        result = provider.inspect_save_path("/strm/tv/不存在 (2026)")

        self.assertFalse(result["data"]["exists"])
        self.assertEqual(
            [{"name": "strm"}, {"name": "tv"}, {"name": "不存在 (2026)"}],
            result["data"]["paths"],
        )
        self.assertEqual([], result["data"]["list"])

    def test_native_p115_save_path_reports_logical_path_not_provider_root(self):
        from types import SimpleNamespace
        from app.clients.p115 import P115File

        class FakeP115:
            settings = SimpleNamespace(p115_root_path="/115-root", cloud_save_path="/strm")

            def directory_id(_, path):
                self.assertEqual("/115-root/tv/测试 (2026)", path)
                return "folder"

            def list_directory(_, cid):
                self.assertEqual("folder", cid)
                return (P115File("1", "folder", "测试.S01E03.mkv", "/115-root/tv/测试 (2026)/测试.S01E03.mkv", 10),)

        result = P115TransferProvider(FakeP115()).inspect_save_path("/strm/tv/测试 (2026)")

        self.assertEqual(
            [{"name": "strm"}, {"name": "tv"}, {"name": "测试 (2026)"}],
            result["data"]["paths"],
        )
        self.assertEqual("测试.S01E03.mkv", result["data"]["list"][0]["file_name"])

    def test_moviepilot_provider_submits_without_claiming_completion(self):
        provider = MoviePilot115TransferProvider(FakeMoviePilot115())
        target = MediaTarget(1, "movie", "测试")
        resolution = LinkResolution(True, "ready", "ready", share_url="https://115.com/s/example")
        result = provider.execute(TransferPlan(target, resolution, ""))
        self.assertTrue(result.ok)
        self.assertEqual("provider_triggered", result.stage)
        self.assertFalse(result.confirmed)
        self.assertIn(ProviderCapability.EXTERNAL_ORGANIZE, provider.capabilities())

    def test_legacy_stages_are_exposed_as_generic_without_rewriting_history(self):
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage)
                VALUES('cloud','qas','triggered','qas_triggered')
                """
            ).lastrowid
        item = next(row for row in list_transfers() if row["id"] == job_id)
        self.assertEqual("provider_triggered", item["stage"])
        with db() as conn:
            stored = conn.execute("SELECT stage FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual("qas_triggered", stored["stage"])
        self.assertEqual("provider_failed", normalize_provider_stage("qas_failed"))
        self.assertEqual("triggered", transfer_status_for_stage("qas_triggered"))

    def test_provider_migration_backfills_related_records_and_is_idempotent(self):
        with db() as conn:
            wishlist_id = conn.execute(
                "INSERT INTO wishlist(tmdb_id,media_type,title,save_target,provider) VALUES(1,'movie','电影','cloud','')"
            ).lastrowid
            task_id = conn.execute(
                "INSERT INTO tracking_tasks(tmdb_id,media_type,title,save_target,provider) VALUES(2,'tv','剧集','cloud','')"
            ).lastrowid
            conn.execute(
                "INSERT INTO tracking_episodes(task_id,season_number,episode_number,provider) VALUES(?,1,1,'')",
                (task_id,),
            )
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage,execution_key)
                VALUES('cloud','','triggered','qas_triggered','2:tv:1:cloud')
                """
            ).lastrowid
            candidate_id = conn.execute(
                "INSERT INTO candidates(job_id,share_url,provider,cloud_type) VALUES(?,'https://pan.quark.cn/s/x','','')",
                (job_id,),
            ).lastrowid
            local_job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage,execution_key)
                VALUES('local','','running','created','3:movie:0:local')
                """
            ).lastrowid

        init_db()
        init_db()
        with db() as conn:
            wishlist = conn.execute("SELECT provider FROM wishlist WHERE id=?", (wishlist_id,)).fetchone()
            task = conn.execute("SELECT provider FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
            episode = conn.execute("SELECT provider FROM tracking_episodes WHERE task_id=?", (task_id,)).fetchone()
            job = conn.execute("SELECT provider,execution_key FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
            candidate = conn.execute(
                "SELECT provider,cloud_type FROM candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            local_job = conn.execute(
                "SELECT provider,execution_key FROM transfer_jobs WHERE id=?", (local_job_id,)
            ).fetchone()
        self.assertEqual("qas", wishlist["provider"])
        self.assertEqual("qas", task["provider"])
        self.assertEqual("qas", episode["provider"])
        self.assertEqual(("qas", "2:tv:1:cloud:qas"), tuple(job))
        self.assertEqual(("qas", "quark"), tuple(candidate))
        self.assertEqual(("", "3:movie:0:local:"), tuple(local_job))

    def test_init_db_adds_provider_columns_to_legacy_schema(self):
        legacy_path = Path(self.tempdir.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.executescript(
            """
            CREATE TABLE wishlist (
              id INTEGER PRIMARY KEY, tmdb_id INTEGER, media_type TEXT, title TEXT,
              save_target TEXT, status TEXT, check_hour INTEGER
            );
            CREATE TABLE tracking_tasks (
              id INTEGER PRIMARY KEY, tmdb_id INTEGER, media_type TEXT, title TEXT,
              save_target TEXT, status TEXT, check_time TEXT
            );
            CREATE TABLE tracking_episodes (
              id INTEGER PRIMARY KEY, task_id INTEGER, season_number INTEGER,
              episode_number INTEGER, status TEXT
            );
            CREATE TABLE transfer_jobs (
              id INTEGER PRIMARY KEY, target TEXT, status TEXT, stage TEXT,
              save_path TEXT, execution_key TEXT
            );
            CREATE TABLE candidates (id INTEGER PRIMARY KEY, job_id INTEGER, share_url TEXT);
            INSERT INTO wishlist VALUES(1,1,'movie','旧电影','cloud','pending',9);
            INSERT INTO transfer_jobs VALUES(1,'cloud','triggered','qas_triggered','/strm/movie/旧电影','1:movie:0:cloud');
            INSERT INTO candidates VALUES(1,1,'https://pan.quark.cn/s/legacy');
            """
        )
        connection.commit()
        connection.close()

        os.environ["DB_PATH"] = str(legacy_path)
        get_settings.cache_clear()
        init_db()
        with db() as conn:
            columns = {
                table: {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for table in ("wishlist", "tracking_tasks", "tracking_episodes", "transfer_jobs", "candidates")
            }
            wishlist = conn.execute("SELECT provider FROM wishlist WHERE id=1").fetchone()
            job = conn.execute("SELECT provider,external_job_id,external_provider_status FROM transfer_jobs WHERE id=1").fetchone()
            candidate = conn.execute("SELECT provider,cloud_type FROM candidates WHERE id=1").fetchone()
        for table in columns:
            self.assertIn("provider", columns[table])
        self.assertEqual("qas", wishlist["provider"])
        self.assertEqual(("qas", "", ""), tuple(job))
        self.assertEqual(("qas", "quark"), tuple(candidate))

    def test_115_review_confirmation_preserves_explicit_job_provider(self):
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(target,provider,status,stage,execution_key)
                VALUES('cloud','moviepilot_115','needs_review','needs_review','1:movie:0:cloud:moviepilot_115')
                """
            ).lastrowid
            candidate_id = conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,cloud_type,provider,rejected,decision)
                VALUES(?,'https://115.com/s/example','115','moviepilot_115',0,'pending')
                """,
                (job_id,),
            ).lastrowid
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "qas,moviepilot_115",
                "MOVIEPILOT_BASE_URL": "https://moviepilot.example",
                "MOVIEPILOT_API_TOKEN": "secret",
            },
        ):
            get_settings.cache_clear()
            candidate, job = prepare_candidate_confirmation(candidate_id)
        self.assertEqual("moviepilot_115", candidate["provider"])
        self.assertEqual("moviepilot_115", job["provider"])
        with db() as conn:
            stored = conn.execute(
                "SELECT provider,status,stage,execution_key FROM transfer_jobs WHERE id=?", (job_id,)
            ).fetchone()
        self.assertEqual(
            ("moviepilot_115", "running", "provider_submitting", "1:movie:0:cloud:moviepilot_115"),
            tuple(stored),
        )

    def test_115_candidate_cannot_change_a_qas_job_provider(self):
        with db() as conn:
            job_id = conn.execute(
                "INSERT INTO transfer_jobs(target,provider,status,stage) VALUES('cloud','qas','needs_review','needs_review')"
            ).lastrowid
            candidate_id = conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,cloud_type,provider,rejected,decision)
                VALUES(?,'https://115.com/s/example','115','moviepilot_115',0,'pending')
                """,
                (job_id,),
            ).lastrowid
        with self.assertRaises(HTTPException) as raised:
            prepare_candidate_confirmation(candidate_id)
        self.assertEqual(409, raised.exception.status_code)

    def test_115_review_submission_is_persisted_as_triggered(self):
        with db() as conn:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(tmdb_id,media_type,target,provider,status,stage,execution_key)
                VALUES(1,'movie','cloud','moviepilot_115','needs_review','needs_review','1:movie:0:cloud:moviepilot_115')
                """
            ).lastrowid
            candidate_id = conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,source_title,cloud_type,provider,rejected,decision)
                VALUES(?,'https://115.com/s/example','测试','115','moviepilot_115',0,'pending')
                """,
                (job_id,),
            ).lastrowid
        with patch.dict(
            os.environ,
            {
                "ENABLED_CLOUD_PROVIDERS": "qas,moviepilot_115",
                "MOVIEPILOT_BASE_URL": "https://moviepilot.example",
                "MOVIEPILOT_API_TOKEN": "secret",
            },
        ):
            get_settings.cache_clear()
            candidate, job = prepare_candidate_confirmation(candidate_id)
            with patch(
                "app.api.review.get_transfer_provider",
                return_value=MoviePilot115TransferProvider(FakeMoviePilot115()),
            ):
                _run_confirmed_candidate(candidate, job, [])
        with db() as conn:
            stored = conn.execute(
                """
                SELECT provider,status,stage,share_url,external_provider_status,review_state
                FROM transfer_jobs WHERE id=?
                """,
                (job_id,),
            ).fetchone()
        self.assertEqual(
            (
                "moviepilot_115",
                "triggered",
                "provider_triggered",
                "https://115.com/s/example",
                "accepted",
                "resolved",
            ),
            tuple(stored),
        )


if __name__ == "__main__":
    unittest.main()
