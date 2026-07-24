import json
import os
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.clients.p115 import P115Client, P115Error, P115File, P115ShareRef, P115ShareSnapshot
from app.core.config import Settings, get_settings
from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget, RenamePair
from app.providers.base import ProviderCapability, TransferPlan
from app.providers.p115 import P115LocalTransferProvider, P115TransferProvider
from app.services.link_resolver import resolve_episode_source


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def p115_settings(**overrides) -> Settings:
    values = {
        "p115_cookie": "UID=1_A1_1; CID=abc; SEID=secret",
        "p115_root_path": "/MediaIndex",
        "p115_staging_path": "/MediaIndex/.staging",
        "p115_request_timeout_seconds": 1,
        "db_path": "unused.db",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class P115ClientTests(unittest.TestCase):
    def test_expired_share_error_has_actionable_message(self):
        client = P115Client(p115_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"state": False, "errno": 4100018})):
            with self.assertRaisesRegex(P115Error, "分享链接已过期.*4100018"):
                client.receive_share_files(P115ShareRef("share", "pass"), ["1"], "99")

    def test_recursive_share_inspection_keeps_file_identity_and_sends_cookie(self):
        client = P115Client(p115_settings())
        responses = [
            FakeResponse(
                {
                    "state": True,
                    "data": {
                        "list": [
                            {"cid": "10", "pid": "0", "n": "S01", "fc": "0"},
                            {"fid": "1", "pid": "0", "n": "movie.mkv", "s": "100", "fc": "1"},
                        ],
                        "count": 2,
                    },
                }
            ),
            FakeResponse(
                {
                    "state": True,
                    "data": {
                        "list": [{"fid": "2", "pid": "10", "n": "show.S01E01.mkv", "s": "200", "fc": "1"}],
                        "count": 1,
                    },
                }
            ),
        ]
        with patch.object(client._opener, "open", side_effect=responses) as request:
            snapshot = client.inspect_share("https://115.com/s/share-code?password=abcd")
        self.assertEqual(["1", "2"], [item.file_id for item in snapshot.files])
        self.assertEqual(["/movie.mkv", "/S01/show.S01E01.mkv"], [item.path for item in snapshot.files])
        self.assertEqual("UID=1_A1_1; CID=abc; SEID=secret", request.call_args_list[0].args[0].get_header("Cookie"))
        first_query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args_list[0].args[0].full_url).query)
        self.assertEqual(["abcd"], first_query["receive_code"])

    def test_requires_complete_cookie_before_network_access(self):
        client = P115Client(p115_settings(p115_cookie="UID=1; CID=2"))
        with patch.object(client._opener, "open") as request:
            with self.assertRaisesRegex(P115Error, "有效的 115 Cookie"):
                client.inspect_share("https://115.com/s/share-code")
        request.assert_not_called()

    def test_rejects_cookie_with_newline_before_network_access(self):
        client = P115Client(p115_settings(p115_cookie="UID=1; CID=2; SEID=3\nINJECTED=value"))
        with patch.object(client._opener, "open") as request:
            with self.assertRaisesRegex(P115Error, "有效的 115 Cookie"):
                client.list_directory(0)
        request.assert_not_called()

    def test_rejects_non_115_and_non_https_share_urls(self):
        client = P115Client(p115_settings())
        for value in ("http://115.com/s/code", "https://example.com/s/code", "https://115.com/no-code"):
            with self.subTest(value=value), self.assertRaises(P115Error):
                client.parse_share_url(value)

    def test_accepts_115cdn_share_and_preserves_password(self):
        client = P115Client(p115_settings())
        share = client.parse_share_url("https://115cdn.com/s/swsoiie3wjf?password=m287")
        self.assertEqual("swsoiie3wjf", share.share_code)
        self.assertEqual("m287", share.receive_code)

    def test_receive_uses_selective_file_ids_and_target_directory(self):
        client = P115Client(p115_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"state": True, "data": {}})) as request:
            client.receive_share_files(P115ShareRef("share", "pass"), ["1", "2", "1"], "99")
        body = urllib.parse.parse_qs(request.call_args.args[0].data.decode())
        self.assertEqual(["1,2"], body["file_id"])
        self.assertEqual(["99"], body["cid"])
        self.assertNotIn("secret", request.call_args.args[0].full_url)

    def test_move_uses_repeated_fid_array_contract(self):
        client = P115Client(p115_settings())
        with patch.object(client._opener, "open", return_value=FakeResponse({"state": True, "data": {}})) as request:
            client.move(["1", "2", "1"], "99")
        body = urllib.parse.parse_qs(request.call_args.args[0].data.decode())
        self.assertEqual(["1", "2"], body["fid[]"])
        self.assertEqual(["99"], body["pid"])


class FakeP115Client:
    def __init__(self):
        self.settings = SimpleNamespace(
            p115_root_path="/MediaIndex",
            p115_staging_path="/MediaIndex/.staging",
            cloud_save_path="/strm",
            p115_request_timeout_seconds=1,
        )
        self.snapshot = P115ShareSnapshot(
            P115ShareRef("share"),
            (
                P115File("source-1", "0", "source.mkv", "/source.mkv", 100),
                P115File("source-2", "0", "other.mkv", "/other.mkv", 200),
            ),
        )
        self.staging_items: list[P115File] = []
        self.final_items: list[P115File] = []
        self.received_ids: list[str] = []

    def configured(self):
        return True

    def inspect_share(self, _share_url):
        return self.snapshot

    def ensure_directory(self, path):
        return "staging" if "/.staging/" in path else "final"

    def directory_id(self, path):
        return "final" if path.startswith("/MediaIndex/movie") else "0"

    def list_directory(self, cid):
        return tuple(self.staging_items if cid == "staging" else self.final_items)

    def receive_share_files(self, _share, file_ids, _target_cid):
        self.received_ids = list(file_ids)
        source = next(item for item in self.snapshot.files if item.file_id == file_ids[0])
        self.staging_items = [P115File("received-1", "staging", source.name, source.path, source.size)]
        return {}

    def rename(self, pairs):
        names = dict(pairs)
        self.staging_items = [
            P115File(item.file_id, item.parent_id, names.get(item.file_id, item.name), item.path, item.size)
            for item in self.staging_items
        ]

    def move(self, file_ids, _target_cid):
        self.final_items.extend(item for item in self.staging_items if item.file_id in file_ids)
        self.staging_items = [item for item in self.staging_items if item.file_id not in file_ids]

    def download_share_file(self, _share, source, destination):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * source.size)
        return source.size


class P115ProviderTests(unittest.TestCase):
    def test_provider_executes_selected_receive_rename_move_and_reconcile(self):
        client = FakeP115Client()
        provider = P115TransferProvider(client)
        target = MediaTarget(1, "movie", "测试", series_year="2026")
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(
                RenamePair(
                    "source.mkv",
                    "source\\.mkv",
                    "测试.2026.mkv",
                    source_id="source-1",
                    source_path="/source.mkv",
                    source_size=100,
                ),
            ),
        )
        result = provider.execute(TransferPlan(target, resolution, "/strm/movie/测试 (2026)"))
        self.assertTrue(result.ok)
        self.assertTrue(result.confirmed)
        self.assertEqual("provider_completed", result.stage)
        self.assertEqual(["source-1"], client.received_ids)
        self.assertEqual(["测试.2026.mkv"], [item.name for item in client.final_items])
        self.assertIn(ProviderCapability.SELECTIVE_TRANSFER, provider.capabilities())

    def test_local_provider_downloads_selected_file_into_configured_root(self):
        client = FakeP115Client()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
            with patch.dict(
                os.environ,
                {
                    "P115_LOCAL_PATH": tempdir,
                    "P115_CATEGORY_PATHS_JSON": '{"movie":"/电影"}',
                    "DB_PATH": ":memory:",
                },
            ):
                get_settings.cache_clear()
                save_path = f"{tempdir.replace(chr(92), '/')}/电影/测试(2026)"
                target = MediaTarget(1, "movie", "测试", category="movie", series_year="2026")
                resolution = LinkResolution(
                    True,
                    "ready",
                    "ready",
                    share_url="https://115.com/s/share",
                    rename_pairs=(
                        RenamePair(
                            "source.mkv",
                            "source\\.mkv",
                            "测试.2026.mkv",
                            source_id="source-1",
                            source_size=100,
                        ),
                    ),
                )
                with patch("app.providers.p115.is_allowed_save_path", return_value=True):
                    result = P115LocalTransferProvider(client).execute(
                        TransferPlan(target, resolution, save_path)
                    )
                self.assertTrue(result.ok, result.message)
                self.assertTrue((Path(save_path) / "测试.2026.mkv").is_file())
        get_settings.cache_clear()

    def test_provider_fails_closed_when_source_identity_is_ambiguous(self):
        client = FakeP115Client()
        client.snapshot = P115ShareSnapshot(
            P115ShareRef("share"),
            (
                P115File("1", "0", "same.mkv", "/A/same.mkv", 100),
                P115File("2", "0", "same.mkv", "/B/same.mkv", 100),
            ),
        )
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            share_url="https://115.com/s/share",
            rename_pairs=(RenamePair("same.mkv", "same", "renamed.mkv", source_size=100),),
        )
        result = P115TransferProvider(client).execute(
            TransferPlan(MediaTarget(1, "movie", "测试"), resolution, "/strm/movie/测试")
        )
        self.assertFalse(result.ok)
        self.assertEqual("provider_failed", result.stage)
        self.assertEqual([], client.received_ids)

    def test_episode_resolver_uses_native_115_inspection(self):
        client = FakeP115Client()
        client.snapshot = P115ShareSnapshot(
            P115ShareRef("share"),
            (P115File("1", "0", "测试剧.S01E01.mkv", "/测试剧.S01E01.mkv", 100),),
        )
        provider = P115TransferProvider(client)

        class Pansou:
            def search_detailed(self, *_args, **_kwargs):
                return SimpleNamespace(
                    items=[{"share_url": "https://115.com/s/share", "title": "测试剧 S01"}],
                    error="",
                )

        target = MediaTarget(
            1,
            "tv",
            "测试剧",
            series_year="2026",
            season_number=1,
            episodes=(EpisodeTarget(1, 1, match_tokens=("S01E01", "E01")),),
        )
        result = resolve_episode_source(target, qas=provider, pansou=Pansou(), max_queries=1, provider_filter="p115")
        self.assertTrue(result.ok)
        self.assertEqual("1", result.rename_pairs[0].source_id)


if __name__ == "__main__":
    unittest.main()
