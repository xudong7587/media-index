import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendCloudDownloadOrganizerContractTests(unittest.TestCase):
    def setUp(self):
        self.component = (
            ROOT / "frontend/src/features/transfer/CloudDownloadOrganizerSettings.tsx"
        ).read_text(encoding="utf-8")
        self.workspace = (
            ROOT / "frontend/src/features/workspace/WorkspaceSections.tsx"
        ).read_text(encoding="utf-8")
        self.main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        self.api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")

    def test_transfer_component_is_injected_without_new_workspace_cross_feature_import(self):
        self.assertIn('type TransferRulesSection = "common" | "quark" | "p115" | "organizer"', self.workspace)
        self.assertIn("cloudDownloadOrganizer?: ReactNode", self.workspace)
        self.assertIn(">云下载整理</button>", self.workspace)
        self.assertNotIn('from "../transfer/', self.workspace)
        self.assertIn('from "./features/transfer/CloudDownloadOrganizerSettings"', self.main)
        self.assertIn('section === "rules-organizer"', self.main)

    def test_api_contract_keeps_typed_config_and_provider_isolated_run_results(self):
        for field in (
            "cloud_download_organizer_enabled: boolean",
            'cloud_download_organizer_mode: CloudDownloadOrganizerMode',
            "cloud_download_organizer_interval_minutes: number",
            "cloud_download_organizer_stable_minutes: number",
            "p115_cloud_download_organizer_directories: string[]",
            "quark_cloud_download_organizer_directories: string[]",
        ):
            self.assertIn(field, self.api)
        self.assertIn('runCloudDownloadOrganizer: (provider?: "p115" | "quark")', self.api)
        self.assertIn('"/api/transfers/cloud-download-organizer/run"', self.api)
        self.assertIn("jobs: CloudDownloadOrganizerRunJob[]", self.api)

    def test_component_selects_only_provider_direct_children_and_previews_fixed_mapping(self):
        self.assertIn("api.browseProviderPath(provider, root, true)", self.component)
        self.assertIn("result.directories", self.component)
        self.assertIn("path: childPath(result.path, item.name)", self.component)
        self.assertIn("mappedTarget(provider, option.path)", self.component)
        self.assertIn("只整理明确勾选的一级子目录", self.component)
        self.assertIn("不接受浏览器提交任意目标绝对路径", self.component)
        self.assertNotIn("target_path:", self.component)

    def test_typed_save_does_not_use_legacy_string_form_payload_builder(self):
        self.assertIn("cloud_download_organizer_enabled: enabled", self.component)
        self.assertIn("cloud_download_organizer_interval_minutes: interval", self.component)
        self.assertIn("p115_cloud_download_organizer_directories: selectedDirectories.p115", self.component)
        self.assertIn("quark_cloud_download_organizer_directories: selectedDirectories.quark", self.component)
        self.assertNotIn("buildConfigPayload", self.component)

    def test_copy_move_cleanup_and_fail_closed_guidance_is_explicit(self):
        for text in (
            "云下载来源目录和文件保持不动",
            "所有目标名称和大小逐项唯一核验后",
            "只按文件 ID 精确清理当时再次确认仍在源媒体目录内的残留普通文件",
            "绝不回收整个源媒体文件夹",
            "发现新到达文件、疑似视频、身份变化、TMDB 歧义、命名冲突或任一步失败时，会停止残留清理并提示核对",
            "目录读取失败会明确报错，不会退化为“目录为空”",
            "证据不足、重名或目标冲突会进入待确认",
        ):
            self.assertIn(text, self.component)

    def test_recent_status_reuses_standard_transfer_jobs_and_has_error_and_empty_states(self):
        self.assertIn('job.request_source === "cloud_download_organizer"', self.component)
        self.assertIn("api.transfers()", self.component)
        for stage in (
            "organizer_resuming",
            "organizer_recovering",
            "organizer_tmdb_resolving",
            "organizer_transferring",
            "organizer_post_processing",
            "organizer_completed",
            "organizer_failed",
            "organizer_needs_review",
            "organizer_stopped",
        ):
            self.assertIn(stage, self.component)
        self.assertIn("还没有云下载整理任务", self.component)
        self.assertIn("云下载整理任务状态读取失败", self.component)
        self.assertIn("一个网盘失败不会隐藏另一个网盘的结果", self.component)


if __name__ == "__main__":
    unittest.main()
