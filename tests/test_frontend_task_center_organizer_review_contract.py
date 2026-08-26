import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendTaskCenterOrganizerReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.component = (
            ROOT / "frontend/src/features/workspace/TaskCenterPage.tsx"
        ).read_text(encoding="utf-8")

    def test_organizer_review_is_read_only_and_explains_content_change_retry(self):
        self.assertIn(
            'selected?.request_source === "cloud_download_organizer"',
            self.component,
        )
        self.assertIn("需要修正来源", self.component)
        self.assertIn("不提供普通候选确认或重新搜索", self.component)
        self.assertIn("修正源目录名称、内容或目标命名冲突", self.component)
        self.assertIn("下一轮稳定检查会自动重新核对", self.component)

    def test_organizer_branch_has_no_confirmation_or_research_controls(self):
        organizer_branch = self.component.split(
            '? <section className="task-review-section"><h3>需要修正来源</h3>',
            1,
        )[1].split(
            ': <section className="task-review-section"><h3>需要你确认</h3>',
            1,
        )[0]
        self.assertNotIn("confirm(", organizer_branch)
        self.assertNotIn("research(", organizer_branch)
        self.assertNotIn("确认此候选并继续", organizer_branch)
        self.assertNotIn("<button", organizer_branch)


if __name__ == "__main__":
    unittest.main()
