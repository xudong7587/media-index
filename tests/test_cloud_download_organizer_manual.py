import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.security import require_user
from app.main import app


class ManualOrganizeEndpointTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[require_user] = lambda: "local"
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_blank_directory_is_rejected(self):
        response = self.client.post(
            "/api/transfers/cloud-download-organizer/organize",
            json={"provider": "quark", "source_path": "   "},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("目录", response.json()["detail"])

    def test_manual_organize_calls_targeted_runner(self):
        with patch("app.api.transfers.run_targeted_cloud_download_organizer") as runner:
            runner.return_value = {"accepted": True}
            response = self.client.post(
                "/api/transfers/cloud-download-organizer/organize",
                json={"provider": "p115", "source_path": "/115/云下载/剧名 (2024)"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        runner.assert_called_once()
        args, kwargs = runner.call_args
        self.assertEqual(args[0], "p115")
        self.assertEqual(args[1], "/115/云下载/剧名 (2024)")
        self.assertTrue(kwargs.get("explicit_request"))

    def test_runner_failure_is_reported(self):
        with patch("app.api.transfers.run_targeted_cloud_download_organizer", side_effect=ValueError("不在允许的整理范围")):
            response = self.client.post(
                "/api/transfers/cloud-download-organizer/organize",
                json={"provider": "quark", "source_path": "/云下载/x"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不在允许的整理范围", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
