import os
import unittest
from unittest.mock import patch

from app.clients.pansou import (
    _load_pansou_json,
    _should_retry_post,
    PansouClient,
    enabled_pansou_cloud_types,
    normalize_pansou_results,
)
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

    def test_enabled_providers_drive_pansou_cloud_types(self):
        with patch.dict(os.environ, {"ENABLED_CLOUD_PROVIDERS": "qas,p115"}):
            get_settings.cache_clear()
            self.assertEqual(["quark", "115"], enabled_pansou_cloud_types())
        get_settings.cache_clear()

    def test_search_request_uses_enabled_cloud_types(self):
        with patch.dict(
            os.environ,
            {"PANSOU_URL": "http://pansou.test", "ENABLED_CLOUD_PROVIDERS": "qas,p115"},
        ):
            get_settings.cache_clear()
            client = PansouClient()
            with patch.object(client, "_search_native_get", return_value=({"data": {"results": []}}, "")) as native:
                client.search_detailed("测试")
            self.assertEqual(["quark", "115"], native.call_args.args[1]["cloud_types"])
        get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
