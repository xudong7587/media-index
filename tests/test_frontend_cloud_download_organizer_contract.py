import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendCloudDownloadOrganizerContractTests(unittest.TestCase):
    def setUp(self):
        self.component = (ROOT / "frontend/src/features/transfer/CloudDownloadOrganizerSettings.tsx").read_text(encoding="utf-8")
        self.workspace = (ROOT / "frontend/src/features/workspace/WorkspaceSections.tsx").read_text(encoding="utf-8")
        self.main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        self.api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        self.styles = (ROOT / "frontend/src/features/transfer/cloud-download-organizer.css").read_text(encoding="utf-8")

    def test_cloud_download_is_a_workspace_peer_between_rules_and_tasks(self):
        self.assertIn('{ key: "rules", label: "转存和整理规则" }', self.main)
        self.assertIn('{ key: "cloud-download", label: "云下载" }', self.main)
        self.assertIn('{ key: "webhook", label: "Webhook" }', self.main)
        self.assertIn('{ key: "tasks", label: "任务中心" }', self.main)
        self.assertLess(self.main.index('{ key: "rules", label: "转存和整理规则" }'), self.main.index('{ key: "cloud-download", label: "云下载" }'))
        self.assertLess(self.main.index('{ key: "cloud-download", label: "云下载" }'), self.main.index('{ key: "webhook", label: "Webhook" }'))
        self.assertLess(self.main.index('{ key: "webhook", label: "Webhook" }'), self.main.index('{ key: "tasks", label: "任务中心" }'))
        self.assertIn('section === "cloud-download" || section === "rules-organizer"', self.main)
        self.assertEqual('type TransferRulesSection = "common" | "quark" | "p115";', next(line.strip() for line in self.workspace.splitlines() if line.startswith("type TransferRulesSection")))
        self.assertNotIn(">云下载整理</button>", self.workspace)

    def test_api_contract_keeps_legacy_fields_and_adds_provider_switches(self):
        for field in (
            "cloud_download_organizer_enabled: boolean",
            "p115_cloud_download_organizer_enabled: boolean",
            "quark_cloud_download_organizer_enabled: boolean",
            'CloudDownloadOrganizerTrigger = "event" | "scheduled"',
            'CloudDownloadOrganizerScopeMode = "all" | "selected"',
            "cloud_download_organizer_triggers: CloudDownloadOrganizerTrigger[]",
            "cloud_download_organizer_interval_minutes: number",
            "cloud_download_organizer_stable_minutes: number",
            "p115_cloud_download_organizer_scope_mode: CloudDownloadOrganizerScopeMode",
            "quark_cloud_download_organizer_scope_mode: CloudDownloadOrganizerScopeMode",
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

    def test_component_supports_event_and_scheduled_triggers_without_manual_full_scan(self):
        self.assertIn('const [triggers, setTriggers] = useState<CloudDownloadOrganizerTrigger[]>(["event"])', self.component)
        self.assertIn('toggleTrigger("event")', self.component)
        self.assertIn('toggleTrigger("scheduled")', self.component)
        self.assertIn('triggers.includes("scheduled") && <>', self.component)
        self.assertIn("cloud_download_organizer_interval_minutes: interval", self.component)
        self.assertIn("cloud_download_organizer_stable_minutes: stable", self.component)
        self.assertNotIn("没有分钟级扫描，也没有手动全量整理入口。前序动作完成后才处理该媒体。", self.component)
        self.assertNotIn("runCloudDownloadOrganizer", self.component)
        self.assertNotIn("立即整理全部", self.component)

    def test_providers_are_vertical_ordered_and_collapsed_until_enabled(self):
        self.assertIn('const providers: Provider[] = ["p115", "quark"]', self.component)
        self.assertIn('enabled[provider] && <div className="settings-section-body organizer-provider-body">', self.component)
        self.assertIn("aria-expanded={enabled[provider]}", self.component)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", self.styles)
        self.assertNotIn("grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 14px;\n}\n\n.organizer-provider-card", self.styles)

    def test_all_subdirectories_are_default_and_partial_selection_loads_on_demand(self):
        self.assertIn('useState<Record<Provider, CloudDownloadOrganizerScopeMode>>({ quark: "all", p115: "all" })', self.component)
        self.assertIn('p115_cloud_download_organizer_scope_mode: scopeModes.p115', self.component)
        self.assertIn('quark_cloud_download_organizer_scope_mode: scopeModes.quark', self.component)
        self.assertIn('scopeModes[provider] === "selected" && selectedDirectories[provider].length === 0', self.component)
        self.assertIn('loadProviderDirectories(provider, selectedDirectories[provider].length === 0)', self.component)
        self.assertIn('if (selectAllOnLoad) setSelectedDirectories', self.component)
        self.assertIn("已默认选择全部可安全映射的一级子目录", self.component)

    def test_cloud_download_root_copy_does_not_claim_it_must_be_under_library_root(self):
        self.assertIn('placeholder="/云下载"', self.component)
        self.assertIn("可位于网盘任意位置", self.component)
        self.assertNotIn("云下载根目录必须位于", self.component)

    def test_guide_explains_confirmed_links_completion_tracking_and_sync_order(self):
        for copy in (
            "直接作为高置信度身份",
            "网盘文件名只提取季号和集号",
            "仍在连载时自动加入智能追更",
            "已播或已完结内容缺集时自动登记补齐",
            "先通过 PanSou 查找并验真 115 资源",
            "才交给 OpenList",
        ):
            self.assertIn(copy, self.component)

    def test_provider_rules_add_pickers_and_no_longer_own_cloud_download_root(self):
        self.assertIn('setDirectoryPicker("root")', self.workspace)
        self.assertIn('setDirectoryPicker("staging")', self.workspace)
        self.assertNotIn('label="云下载目录"', self.workspace)


if __name__ == "__main__":
    unittest.main()
