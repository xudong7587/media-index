import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendResourceAcquisitionContractTests(unittest.TestCase):
    def setUp(self):
        self.sources = (ROOT / "frontend/src/features/workspace/ResourceAcquisitionPage.tsx").read_text(encoding="utf-8")
        self.channels = (ROOT / "frontend/src/features/cloud/ChannelWorkspace.tsx").read_text(encoding="utf-8")
        self.channel_styles = (ROOT / "frontend/src/features/cloud/channel-workspace.css").read_text(encoding="utf-8")
        self.guide = (ROOT / "frontend/src/features/settings/UserGuide.tsx").read_text(encoding="utf-8")
        self.guide_styles = (ROOT / "frontend/src/features/settings/user-guide.css").read_text(encoding="utf-8")
        self.main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        self.routes = (ROOT / "frontend/src/app/routes.ts").read_text(encoding="utf-8")
        self.shell = (ROOT / "frontend/src/app/ApplicationShell.tsx").read_text(encoding="utf-8")

    def test_pansou_and_telegram_are_separate_tabs(self):
        self.assertIn('role="tablist" aria-label="资源获取来源"', self.sources)
        self.assertIn('aria-selected={source === "pansou"}', self.sources)
        self.assertIn('aria-selected={source === "telegram"}', self.sources)
        self.assertIn('source === "pansou" ? <PansouSourceSettings /> : <ChannelWorkspace />', self.sources)
        self.assertIn("与 TG 频道规则完全独立", self.sources)

    def test_channel_directory_is_bounded_searchable_and_filterable(self):
        self.assertIn("const PAGE_SIZE = 8", self.channels)
        self.assertIn('placeholder="搜索频道名称或 @用户名"', self.channels)
        self.assertIn('["setup", "待配置"]', self.channels)
        self.assertIn('filteredSubscriptions.slice((page - 1) * PAGE_SIZE', self.channels)
        self.assertIn("旧版收集但尚未启用自动转存的来源集中在这里", self.channels)
        self.assertIn("上一页", self.channels)
        self.assertIn("下一页", self.channels)

    def test_each_channel_owns_an_independent_rule(self):
        self.assertIn("修改只影响当前频道，不会覆盖 PanSou 或其他频道", self.channels)
        self.assertIn("必须包含（正向词）", self.channels)
        self.assertIn("必须排除（反向词）", self.channels)
        self.assertIn("自动识别分类", self.channels)
        self.assertIn("云下载直属子目录", self.channels)
        self.assertIn("保存当前频道", self.channels)
        self.assertIn('role="tab" aria-selected={view === "activity"}', self.channels)

    def test_global_tracking_settings_are_saved_separately(self):
        settings_body = self.channels.split("async function saveTrackingSettings", 1)[1].split("async function saveChannel", 1)[0]
        channel_body = self.channels.split("async function saveChannel", 1)[1].split("async function syncPublicSources", 1)[0]
        self.assertIn("telegram_channel_source_enabled", settings_body)
        self.assertNotIn("telegram_channel_source_enabled", channel_body)
        self.assertIn("saveChannelSubscription", channel_body)

    def test_guide_is_a_full_workflow_manual_with_direct_routes(self):
        for title in ("第一次配置", "资源从哪里进入", "云下载与正式媒体库", "追更、愿望单与频道", "STRM、302 与 Emby", "任务、日志与排障", "备份、升级与安全"):
            self.assertIn(title, self.guide)
        self.assertIn("完成标志：", self.guide)
        self.assertIn("你现在要完成什么？", self.guide)
        self.assertIn("MediaIndex 两条主要流程", self.guide)
        self.assertIn("onNavigate(chapter.route!)", self.guide)
        self.assertIn('route.page === "guide" && <UserGuide onNavigate={navigate} />', self.main)
        self.assertIn('{ page: "guide", label: "使用手册", hint: "流程与操作指南", icon: BookOpenText }', self.shell)
        self.assertIn('guide: { label: "使用手册", context: "帮助中心" }', self.shell)
        self.assertIn('"settings-guide": { page: "guide" }', self.routes)
        self.assertNotIn('["guide", "使用手册"]', self.main)

    def test_ui_motion_is_restrained_and_accessible(self):
        self.assertIn("cubic-bezier(.23, 1, .32, 1)", self.channel_styles)
        self.assertIn("transform: scale(.97)", self.channel_styles)
        self.assertIn("@media (hover: hover) and (pointer: fine)", self.channel_styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.channel_styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.guide_styles)


if __name__ == "__main__":
    unittest.main()
