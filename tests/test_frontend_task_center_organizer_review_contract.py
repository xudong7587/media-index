import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendTaskCenterOrganizerReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.component = (
            ROOT / "frontend/src/features/workspace/TaskCenterPage.tsx"
        ).read_text(encoding="utf-8")

    def test_organizer_review_explains_regular_series_and_variety_boundaries(self):
        self.assertIn(
            'selected?.request_source === "cloud_download_organizer"',
            self.component,
        )
        self.assertIn("普通剧集直接整理", self.component)
        self.assertIn("不再用网盘文件名筛选剧名", self.component)
        self.assertIn("集号明确且不重复", self.component)
        self.assertIn("综艺仍会核对日期、期数、上下篇和特别内容", self.component)
        self.assertIn("来源目录", self.component)
        self.assertIn("api.retryCloudDownloadOrganizer", self.component)

    def test_superseded_organizer_review_opens_the_newer_task_instead_of_retrying(self):
        self.assertIn("selected.superseded_by_job_id", self.component)
        self.assertIn("这是一条较早的目录记录", self.component)
        self.assertIn("旧记录不再重复扫描或执行文件操作", self.component)
        self.assertIn("查看新任务", self.component)
        self.assertIn("setSelected(selectedNewerJob)", self.component)

    def test_organizer_review_uses_a_dedicated_compact_resolution_surface(self):
        self.assertIn("task-resolution-panel", self.component)
        self.assertIn("task-resolution-action", self.component)
        self.assertNotIn(
            '<section className="task-review-section"><h3>需要处理</h3>',
            self.component,
        )

    def test_completed_organizer_exposes_optional_direct_library_backfill(self):
        self.assertIn("task-followup-panel", self.component)
        self.assertIn("selected.backfill_confirmation_state", self.component)
        self.assertIn("api.decideOrganizedBackfill", self.component)
        self.assertIn("启动一次补集", self.component)
        self.assertIn("不经过云下载", self.component)


if __name__ == "__main__":
    unittest.main()
