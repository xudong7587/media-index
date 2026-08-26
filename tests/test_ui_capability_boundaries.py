import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiCapabilityBoundaryTests(unittest.TestCase):
    def test_cross_cloud_page_reuses_openlist_manual_sync_and_hides_native_experiment(self):
        main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        start = main.index("function CrossCloudPage")
        end = main.index("function WorkspacePortal", start)
        cross_cloud_page = main[start:end]

        self.assertIn("<OpenListManualSync", cross_cloud_page)
        self.assertIn("需要 OpenList 支持", cross_cloud_page)
        self.assertIn("OpenList 复制进度", cross_cloud_page)
        self.assertIn("正在进行", cross_cloud_page)
        self.assertIn("已完成", cross_cloud_page)
        self.assertNotIn("CrossCloudTransferCenter", cross_cloud_page)
        self.assertNotIn("原生秒传", cross_cloud_page)

    def test_openlist_configuration_no_longer_hosts_a_second_manual_copy_surface(self):
        main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")

        self.assertEqual(1, main.count("<OpenListManualSync"))
        self.assertNotIn('["manual", "手动同步"]', main)

    def test_pansou_channel_import_reads_configured_channels_without_keyword_search(self):
        component = (ROOT / "frontend/src/features/workspace/PansouChannelImport.tsx").read_text(encoding="utf-8")

        self.assertIn("api.pansouChannels()", component)
        self.assertIn("直接读取 PanSou 当前配置", component)
        self.assertNotIn("discoverPansouChannels", component)
        self.assertNotIn("发现关键词", component)

    def test_discover_restores_review_and_only_shows_active_openlist_workflow(self):
        main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        routes = (ROOT / "frontend/src/app/routes.ts").read_text(encoding="utf-8")

        self.assertIn('section: "review"', routes)
        self.assertIn('discoverSection === "review" && <ReviewPage', main)
        self.assertLess(main.index("链接下载</button>"), main.index("待确认</button>"))
        self.assertIn('step.key !== "openlist_sync" || !["pending", "skipped"].includes(step.status)', main)
        self.assertIn("media-workflow-current", main)

    def test_activity_log_tasks_link_to_owned_pages(self):
        component = (ROOT / "frontend/src/features/activity/ActivityCenter.tsx").read_text(encoding="utf-8")

        self.assertIn("function routeForJob", component)
        self.assertIn('className="activity-card-link"', component)
        self.assertNotIn("打开对应页面", component)
        self.assertNotIn("任务 #{job.id}", component)
        self.assertIn("api.transferLogs()", component)
        self.assertIn("ACTIVITY_CLEARED_BEFORE_KEY", component)
        self.assertIn('{ page: "discover", section: "review" }', component)
        self.assertIn('{ page: "cross-cloud" }', component)
        self.assertIn('{ page: "media-server" }', component)


if __name__ == "__main__":
    unittest.main()
