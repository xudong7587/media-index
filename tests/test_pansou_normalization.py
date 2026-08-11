import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.clients.pansou import (
    _load_pansou_json,
    _should_retry_post,
    PansouClient,
    enabled_pansou_cloud_types,
    normalize_pansou_results,
)
from app.api.config import ConfigUpdate, update_config
from app.core.config import get_settings


class PansouNormalizationTests(unittest.TestCase):
    def test_invalid_scraped_bytes_do_not_discard_valid_results(self):
        data = _load_pansou_json(b'{"data":{"results":[]},"message":"bad\xfftext"}')
        self.assertEqual([], data["data"]["results"])
        self.assertIn("bad", data["message"])

    def test_post_fallback_only_for_method_or_request_shape_errors(self):
        self.assertTrue(_should_retry_post("http_405"))
        self.assertTrue(_should_retry_post("http_422"))
        self.assertFalse(_should_retry_post("timeout"))
        self.assertFalse(_should_retry_post("connection_error:ConnectionRefusedError"))

    def test_res_all_flattens_quark_links_with_context(self):
        data = {
            "data": {
                "results": [
                    {
                        "channel": "example",
                        "datetime": "2026-07-10T00:00:00Z",
                        "title": "节目第3季",
                        "content": "含本周更新",
                        "links": [
                            {"type": "quark", "url": "https://pan.quark.cn/s/abc", "work_title": "节目 S03"},
                            {"type": "baidu", "url": "https://pan.baidu.com/s/def"},
                        ],
                    }
                ],
                "merged_by_type": {
                    "quark": [
                        {"url": "https://pan.quark.cn/s/abc", "note": "节目 S03"},
                        {"url": "https://pan.quark.cn/s/xyz", "note": "节目第二季"},
                    ]
                },
            }
        }
        results = normalize_pansou_results(data, 10)
        self.assertEqual(2, len(results))
        self.assertEqual("https://pan.quark.cn/s/abc", results[0]["share_url"])
        self.assertEqual("含本周更新", results[0]["content"])
        self.assertEqual("https://pan.quark.cn/s/xyz", results[1]["share_url"])

    def test_quark_and_115_results_keep_cloud_and_provider_identity(self):
        data = {
            "data": {
                "results": [
                    {
                        "title": "测试节目",
                        "links": [
                            {"type": "quark", "url": "https://pan.quark.cn/s/q1"},
                            {"type": "115", "url": "https://115.com/s/s115"},
                            {"type": "115", "url": "https://example.com/not-a-share"},
                        ],
                    }
                ],
                "merged_by_type": {
                    "115": [
                        {"url": "https://115.com/s/s115/", "note": "重复结果"},
                        {"url": "https://115.com/s/s116", "note": "另一结果"},
                    ]
                },
            }
        }
        results = normalize_pansou_results(data, 10)
        self.assertEqual(3, len(results))
        self.assertEqual(("quark", "qas"), (results[0]["cloud_type"], results[0]["provider"]))
        self.assertEqual(("115", "p115"), (results[1]["cloud_type"], results[1]["provider"]))
        self.assertEqual("https://115.com/s/s116", results[2]["share_url"])

    def test_115cdn_root_share_with_password_is_kept_as_p115(self):
        share_url = "https://115cdn.com/s/example-code?password=ke27"
        results = normalize_pansou_results(
            {
                "data": {
                    "results": [
                        {
                            "title": "测试电影",
                            "links": [{"type": "115", "url": share_url}],
                        }
                    ]
                }
            },
            10,
        )

        self.assertEqual(1, len(results))
        self.assertEqual(share_url, results[0]["share_url"])
        self.assertEqual(("115", "p115"), (results[0]["cloud_type"], results[0]["provider"]))

    def test_large_quark_group_does_not_starve_115_results_at_limit(self):
        quark = [
            {"url": f"https://pan.quark.cn/s/q{index}", "note": f"夸克 {index}"}
            for index in range(120)
        ]
        p115 = [
            {"url": f"https://115cdn.com/s/p{index}", "note": f"115 {index}"}
            for index in range(9)
        ]

        results = normalize_pansou_results(
            {"data": {"merged_by_type": {"quark": quark, "115": p115}}},
            100,
        )

        self.assertEqual(100, len(results))
        self.assertEqual(9, sum(1 for item in results if item["cloud_type"] == "115"))
        self.assertEqual(91, sum(1 for item in results if item["cloud_type"] == "quark"))

    def test_enabled_providers_drive_pansou_cloud_types(self):
        with patch.dict(os.environ, {"ENABLED_CLOUD_PROVIDERS": "qas,p115"}):
            get_settings.cache_clear()
            self.assertEqual(["quark", "115"], enabled_pansou_cloud_types())
        get_settings.cache_clear()

    def test_search_request_only_sends_keyword_to_pansou(self):
        with patch.dict(
            os.environ,
            {"PANSOU_URL": "http://pansou.test", "ENABLED_CLOUD_PROVIDERS": "qas,p115"},
        ):
            get_settings.cache_clear()
            client = PansouClient()
            with patch.object(client, "_search_native_get", return_value=({"data": {"results": []}}, "")) as native:
                client.search_detailed("测试")
            self.assertEqual({"kw": "测试"}, native.call_args.args[1])
        get_settings.cache_clear()

    def test_search_polls_until_async_results_stop_growing(self):
        with patch.dict(os.environ, {"PANSOU_URL": "http://pansou.test"}):
            get_settings.cache_clear()
            client = PansouClient()
            responses = [
                ({"data": {"results": []}}, ""),
                (
                    {
                        "data": {
                            "results": [
                                {
                                    "title": "挽救计划",
                                    "links": [
                                        {"type": "115", "url": "https://115.com/s/one"},
                                        {"type": "115", "url": "https://115.com/s/two"},
                                    ],
                                }
                            ]
                        }
                    },
                    "",
                ),
                (
                    {
                        "data": {
                            "results": [
                                {
                                    "title": "挽救计划",
                                    "links": [
                                        {"type": "115", "url": "https://115.com/s/one"},
                                        {"type": "115", "url": "https://115.com/s/two"},
                                    ],
                                }
                            ]
                        }
                    },
                    "",
                ),
            ]
            with (
                patch.object(client, "_search_native_get", side_effect=responses) as native,
                patch("app.clients.pansou.time.sleep") as sleep,
            ):
                result = client.search_detailed("挽救计划", timeout=45)

            self.assertEqual(2, len(result.items))
            self.assertEqual(3, native.call_count)
            self.assertEqual([10, 10, 9], [call.args[2] for call in native.call_args_list])
            self.assertTrue(all(call.args[1] == {"kw": "挽救计划"} for call in native.call_args_list))
            self.assertEqual(2, sleep.call_count)
        get_settings.cache_clear()

    def test_empty_async_snapshots_consume_the_full_poll_window(self):
        with patch.dict(os.environ, {"PANSOU_URL": "http://pansou.test"}):
            get_settings.cache_clear()
            client = PansouClient()
            with (
                patch.object(client, "_search_native_get", return_value=({"data": {"total": 0}}, "")) as native,
                patch("app.clients.pansou.time.sleep") as sleep,
            ):
                result = client.search_detailed("挽救计划", timeout=45)

            self.assertEqual([], result.items)
            self.assertEqual(4, native.call_count)
            self.assertEqual(3, sleep.call_count)
        get_settings.cache_clear()

    def test_search_response_limit_keeps_115_when_quark_exceeds_limit(self):
        with patch.dict(os.environ, {"PANSOU_URL": "http://pansou.test"}):
            get_settings.cache_clear()
            client = PansouClient()
            quark = [
                {"url": f"https://pan.quark.cn/s/q{index}", "note": f"夸克 {index}"}
                for index in range(120)
            ]
            p115 = [
                {"url": f"https://115cdn.com/s/p{index}", "note": f"115 {index}"}
                for index in range(9)
            ]
            response = {"data": {"merged_by_type": {"quark": quark, "115": p115}}}
            with (
                patch.object(client, "_search_native_get", return_value=(response, "")),
                patch("app.clients.pansou.time.sleep"),
            ):
                result = client.search_detailed("挽救计划", limit=50)

            self.assertEqual(50, len(result.items))
            self.assertEqual(9, sum(1 for item in result.items if item["cloud_type"] == "115"))
            self.assertEqual(41, sum(1 for item in result.items if item["cloud_type"] == "quark"))
        get_settings.cache_clear()

    def test_saved_pansou_url_overrides_compose_environment(self):
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "runtime.env"
            with patch.dict(
                os.environ,
                {
                    "MEDIA_CONFIG_PATH": str(config_path),
                    "PANSOU_URL": "http://compose-pansou:8888",
                    "DB_PATH": str(Path(directory) / "media_index.db"),
                },
            ):
                get_settings.cache_clear()
                with patch("app.api.config.stop_scheduler"), patch("app.api.config.start_scheduler"):
                    update_config(ConfigUpdate(pansou_url="http://saved-pansou:8888"))
                self.assertIn("PANSOU_URL=http://saved-pansou:8888", config_path.read_text(encoding="utf-8"))
                get_settings.cache_clear()
                self.assertEqual("http://saved-pansou:8888", get_settings().pansou_url)
        get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
