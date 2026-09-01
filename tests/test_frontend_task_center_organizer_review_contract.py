import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendTaskCenterOrganizerReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.component = (
            ROOT / "frontend/src/features/workspace/TaskCenterPage.tsx"
        ).read_text(encoding="utf-8")

    def test_organizer_review_explains_safe_exact_source_retry(self):
        self.assertIn(
            'selected?.request_source === "cloud_download_organizer"',
            self.component,
        )
        self.assertIn("不支持跳过安全校验强制确认", self.component)
        self.assertIn("修正源目录名称、内容或目标命名冲突", self.component)
        self.assertIn("不会扫描同级媒体，也不会再次转存分享文件", self.component)
        self.assertIn("重新核对当前目录", self.component)
        self.assertIn("api.retryCloudDownloadOrganizer", self.component)

    def test_organizer_branch_has_no_force_confirmation_or_research_controls(self):
        organizer_branch = self.component.split(
            '? <section className="task-review-section"><h3>需要处理</h3>',
            1,
        )[1].split(
            ': <section className="task-review-section"><h3>需要你确认</h3>',
            1,
        )[0]
        self.assertNotIn("confirm(", organizer_branch)
        self.assertNotIn("research(", organizer_branch)
        self.assertNotIn("确认此候选并继续", organizer_branch)
        self.assertEqual(1, organizer_branch.count("<button"))


if __name__ == "__main__":
    unittest.main()
