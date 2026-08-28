import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendWorkflowOverviewContractTests(unittest.TestCase):
    def setUp(self):
        self.component = (ROOT / "frontend/src/features/settings/WorkflowOverview.tsx").read_text(encoding="utf-8")
        self.styles = (ROOT / "frontend/src/features/settings/workflow-overview.css").read_text(encoding="utf-8")
        self.main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        self.routes = (ROOT / "frontend/src/app/routes.ts").read_text(encoding="utf-8")
        self.mdc_settings = (ROOT / "frontend/src/features/integrations/MdcWebhookSettings.tsx").read_text(encoding="utf-8")
        self.network_proxy = (ROOT / "frontend/src/features/settings/NetworkProxySettings.tsx").read_text(encoding="utf-8")

    def test_overview_is_first_settings_tab_and_stays_out_of_legacy_main(self):
        self.assertLess(self.main.index('["overview", "链路概览"]'), self.main.index('["basic", "全局设置"]'))
        self.assertIn("<WorkflowOverview", self.main)
        self.assertIn('if (target === "webhook") { onNavigate({ page: "workspace", section: "webhook" }); return; }', self.main)

    def test_flow_covers_all_sources_and_mdc_bypass(self):
        for label in ("发现", "外部投递 / 目录监测", "智能追更", "愿望单", "链接 / 浏览器插件", "Webhook 引入媒体"):
            self.assertIn(f'label: "{label}"', self.component)
        self.assertIn('title="直接入库媒体链"', self.component)
        self.assertIn('title="云下载暂存整理链"', self.component)
        self.assertIn('label: "接收 / 发现原始文件"', self.component)
        self.assertIn('label: "正式媒体库"', self.component)
        self.assertIn("此时尚未入库", self.component)
        self.assertIn("这条链不经过云下载文件夹", self.component)
        self.assertIn("流程停在云下载文件夹", self.component)
        self.assertIn("由外部工具整理，不经过 MediaIndex 改名", self.component)
        self.assertIn("STRM 增量生成", self.component)
        self.assertIn("Emby 入库", self.component)

    def test_configuration_states_and_click_targets_are_accessible(self):
        self.assertIn('node.configured ? "已配置" : "待配置"', self.component)
        self.assertIn('className={`workflow-node', self.component)
        self.assertIn("aria-label={`${node.label}", self.component)
        self.assertIn('key: "paste-link"', self.component)
        self.assertIn('onNavigate({ page: "workspace", section: "cloud-download" })', self.component)
        self.assertIn(".workflow-node:focus-visible", self.styles)
        self.assertIn(".workflow-flow-step:focus-visible", self.styles)
        self.assertIn(".workflow-milestone.cloud", self.styles)
        self.assertIn(".workflow-milestone.library", self.styles)
        self.assertIn("入口在这里汇合，接着按顺序执行", self.component)
        self.assertIn(".workflow-branch-layout {", self.styles)
        self.assertIn("grid-template-columns: 1fr;", self.styles)
        self.assertIn(".workflow-branch-process { align-self: stretch; }", self.styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.styles)
        self.assertIn('"settings-webhook": { page: "workspace", section: "webhook" }', self.routes)
        self.assertIn('if (value === "system/webhook") return { page: "workspace", section: "webhook" };', self.routes)

    def test_readiness_requires_native_cloud_connections(self):
        self.assertIn('const nativeP115Ready = config.enabled_providers.includes("p115") && config.has_p115_cookie;', self.component)
        self.assertIn('const nativeQuarkReady = config.enabled_providers.includes("quark") && config.has_quark_cookie;', self.component)
        self.assertNotIn("config.has_p115_open", self.component)
        self.assertNotIn("config.direct_download_enabled", self.component)
        self.assertIn("nativeP115Ready\n      && config.p115_strm_enabled", self.component)
        self.assertIn("nativeQuarkReady\n      && config.quark_strm_enabled", self.component)
        self.assertIn("const interactiveCloudConfigured = interactiveCloudProviders.length > 0;", self.component)
        self.assertIn("请至少配置一个原生网盘连接与云下载路径", self.component)
        self.assertIn('const directSources = [source("discover"), source("tracking"), source("wishlist")];', self.component)
        self.assertIn('const cloudSources = [source("cloud-download"), source("paste-link")];', self.component)
        self.assertNotIn("除外部 Webhook 外的入口汇入统一处理链", self.component)

    def test_mdc_setup_uses_one_saved_incremental_directory_without_external_paths(self):
        self.assertIn("mdc_webhook_scan_path", self.mdc_settings)
        self.assertIn("不读取 MDC-NG 的文件路径", self.mdc_settings)
        self.assertIn("请求不需要携带媒体文件或目录路径", self.mdc_settings)
        self.assertIn("configured_incremental", self.mdc_settings)
        self.assertIn("点选目录", self.mdc_settings)
        self.assertIn("<ProviderDirectoryPicker", self.mdc_settings)
        self.assertIn("boundaryRoots={includedDirectories}", self.mdc_settings)
        self.assertIn("webhook-scan-path-control", self.mdc_settings)
        self.assertNotIn('"target_path"', self.mdc_settings)

    def test_network_proxy_is_tested_by_the_backend_container(self):
        api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
        self.assertIn('testProxy: (proxyUrl?: string)', api)
        self.assertIn('"/api/config/test-proxy"', api)
        self.assertIn('section === "network"', self.main)
        self.assertIn('"\u6d4b\u8bd5\u4ee3\u7406"', self.network_proxy)
        self.assertIn("允许局域网连接", self.network_proxy)
        self.assertIn('PROXY_URL: ${PROXY_URL:-}', compose)
        self.assertIn('HTTP_PROXY: ${HTTP_PROXY:-}', compose)
        self.assertIn('HTTPS_PROXY: ${HTTPS_PROXY:-}', compose)
        self.assertIn('NO_PROXY: ${NO_PROXY:-', compose)

    def test_connector_only_stretches_paths_not_nodes_or_icons(self):
        connector = self.component.split("function WorkflowMergeConnector", 1)[1].split("type WorkflowFlowItem", 1)[0]
        self.assertIn('preserveAspectRatio="none"', connector)
        self.assertIn('vectorEffect="non-scaling-stroke"', connector)
        self.assertNotIn("<circle", connector)
        self.assertNotIn("<ellipse", connector)
        self.assertIn(".workflow-branch-merge::after", self.styles)
        self.assertIn("aspect-ratio: 1", self.styles)
        self.assertIn(".workflow-overview-page svg:not(.workflow-merge-connector) { flex-shrink: 0; }", self.styles)


if __name__ == "__main__":
    unittest.main()
