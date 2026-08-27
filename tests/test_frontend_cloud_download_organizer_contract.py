import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendCloudDownloadOrganizerContractTests(unittest.TestCase):
    def setUp(self):
        self.component = (ROOT / "frontend/src/features/transfer/CloudDownloadOrganizerSettings.tsx").read_text(encoding="utf-8")
        self.workspace = (ROOT / "frontend/src/features/workspace/WorkspaceSections.tsx").read_text(encoding="utf-8")
        self.main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        self.api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")

    def test_cloud_download_is_a_workspace_peer_between_rules_and_tasks(self):
        self.assertIn('{ key: "rules", label: "转存和整理规则" }', self.main)
        self.assertIn('{ key: "cloud-download", label: "云下载整理" }', self.main)
        self.assertIn('{ key: "tasks", label: "任务中心" }', self.main)
        self.assertIn('section === "cloud-download" || section === "rules-organizer"', self.main)
        self.assertEqual('type TransferRulesSection = "common" | "quark" | "p115";', next(line.strip() for line in self.workspace.splitlines() if line.startswith("type TransferRulesSection")))
        self.assertNotIn(">云下载整理</button>", self.workspace)

    def test_api_contract_keeps_legacy_fields_and_adds_provider_switches(self):
        for field in (
            "cloud_download_organizer_enabled: boolean",
            "p115_cloud_download_organizer_enabled: boolean",
            "quark_cloud_download_organizer_enabled: boolean",
            "cloud_download_organizer_interval_minutes: number",
            "cloud_download_organizer_stable_minutes: number",
            "p115_cloud_download_organizer_directories: string[]",
            "quark_cloud_download_organizer_directories: string[]",
        ):
            self.assertIn(field, self.api)

    def test_component_has_independent_switches_roots_pickers_and_fixed_mapping(self):
        self.assertIn('role="switch"', self.component)
        self.assertIn("p115_cloud_download_organizer_enabled: enabled.p115", self.component)
        self.assertIn("quark_cloud_download_organizer_enabled: enabled.quark", self.component)
        self.assertIn('field: "library"', self.component)
        self.assertIn('field: "download"', self.component)
        self.assertIn("ProviderDirectoryPicker", self.component)
        self.assertIn("api.browseProviderPath(provider, root, true)", self.component)
        self.assertIn("mappedTarget(provider, option.path)", self.component)

    def test_component_explains_event_driven_exact_behavior_without_scan_controls(self):
        for text in (
            "没有分钟级扫描",
            "前序动作事件",
            "不会遍历其他媒体或兄弟目录",
            "只响应 MediaIndex 前序转存完成事件",
            "不会每隔几分钟读取整个云下载根",
            "任何步骤都不会回退成全量或增量扫描",
        ):
            self.assertIn(text, self.component)
        self.assertNotIn("runCloudDownloadOrganizer", self.component)
        self.assertNotIn("立即整理全部", self.component)
        self.assertNotIn("intervalMinutes", self.component)
        self.assertNotIn("stableMinutes", self.component)

    def test_provider_rules_add_pickers_and_no_longer_own_cloud_download_root(self):
        self.assertIn('setDirectoryPicker("root")', self.workspace)
        self.assertIn('setDirectoryPicker("staging")', self.workspace)
        self.assertNotIn('label="云下载目录"', self.workspace)


if __name__ == "__main__":
    unittest.main()
