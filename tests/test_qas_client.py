import unittest

from app.clients.qas import QasClient


class RecordingQasClient(QasClient):
    def __init__(self):
        self.posts = []

    def task_data(self) -> dict:
        return {
            "source": {
                "cloudsaver": {"enable": True, "server": "http://cloudsaver"},
                "pansou": {"enable": True, "server": "http://pansou"},
            }
        }

    def post(self, endpoint: str, data: dict | None = None, timeout: int = 60) -> dict:
        self.posts.append((endpoint, data, timeout))
        return {"success": True}


class QasClientTests(unittest.TestCase):
    def test_disabling_pansou_preserves_other_qas_sources(self):
        client = RecordingQasClient()
        result = client.disable_pansou_search()

        self.assertTrue(result["success"])
        endpoint, payload, timeout = client.posts[0]
        self.assertEqual("/update", endpoint)
        self.assertEqual(30, timeout)
        self.assertFalse(payload["source"]["pansou"]["enable"])
        self.assertEqual("http://pansou", payload["source"]["pansou"]["server"])
        self.assertTrue(payload["source"]["cloudsaver"]["enable"])


if __name__ == "__main__":
    unittest.main()
