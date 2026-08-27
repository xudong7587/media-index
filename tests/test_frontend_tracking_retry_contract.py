import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendTrackingRetryContractTests(unittest.TestCase):
    def setUp(self):
        self.component = (ROOT / "frontend/src/features/tracking/TrackingRetrySettings.tsx").read_text(encoding="utf-8")
        self.main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        self.styles = (ROOT / "frontend/src/styles.css").read_text(encoding="utf-8")

    def test_tracking_page_exposes_retry_interval_and_maximum(self):
        self.assertIn("<TrackingRetrySettings />", self.main)
        self.assertIn("失败后重试间隔（分钟）", self.component)
        self.assertIn("最大重试次数", self.component)
        self.assertIn("tracking_retry_interval_minutes", self.component)
        self.assertIn("tracking_max_retries", self.component)
        self.assertIn("api.saveConfig", self.component)

    def test_interval_is_explained_in_hours_and_silent_retries_are_not_capped(self):
        self.assertIn("formatInterval", self.component)
        self.assertIn("小时", self.component)
        self.assertIn("未发布或未搜到会继续静默检查", self.component)
        self.assertIn("执行失败累计达到上限", self.component)

    def test_new_task_frontend_fallback_is_noon_and_layout_is_responsive(self):
        self.assertIn('task.check_time ?? "12:00"', self.main)
        self.assertNotIn('task.check_time ?? "10:00"', self.main)
        self.assertIn(".tracking-retry-settings", self.styles)
        self.assertIn(".tracking-retry-settings-fields", self.styles)


if __name__ == "__main__":
    unittest.main()
