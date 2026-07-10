import unittest

from app.clients.pansou import _should_retry_post, normalize_pansou_results


class PansouNormalizationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
