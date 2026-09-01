import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiCapabilityBoundaryTests(unittest.TestCase):
    def test_resource_acquisition_exposes_pansou_and_tg_as_independent_sources(self):
        component = (ROOT / "frontend/src/features/workspace/ResourceAcquisitionPage.tsx").read_text(encoding="utf-8")

        self.assertIn("<PansouSourceSettings />", component)
        self.assertIn("<ChannelWorkspace onOpenTelegramSettings=", component)
        self.assertIn("pansou_exclude_keywords", component)
        self.assertIn('role="tablist" aria-label="资源获取来源"', component)
        self.assertIn('aria-selected={source === "pansou"}', component)
        self.assertIn('aria-selected={source === "telegram"}', component)

    def test_active_resolvers_do_not_claim_to_search_telegram(self):
        for relative in ("link_resolver.py", "movie_resolver.py", "standard_resolver.py"):
            source = (ROOT / "backend/app/services" / relative).read_text(encoding="utf-8")
            self.assertNotIn("TG 频道源", source)

    def test_cross_cloud_page_reuses_openlist_manual_sync_and_hides_native_experiment(self):
        main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        start = main.index("function CrossCloudPage")
        end = main.index("function WorkspacePortal", start)
        cross_cloud_page = main[start:end]

        self.assertIn("<OpenListManualSync", cross_cloud_page)
        self.assertIn("<OpenListSettingsPanel", cross_cloud_page)
        self.assertIn("补偿链路，不是发现入口", cross_cloud_page)
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
        component = (ROOT / "frontend/src/features/tracking/PansouChannelImport.tsx").read_text(encoding="utf-8")

        self.assertIn("api.pansouChannels()", component)
        self.assertIn("读取 PanSou 已配置的公开频道名单", component)
        self.assertIn("全选可导入频道", component)
        self.assertNotIn("discoverPansouChannels", component)
        self.assertNotIn("发现关键词", component)

    def test_review_lives_beside_wishlist_and_discover_only_shows_active_openlist_workflow(self):
        main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        routes = (ROOT / "frontend/src/app/routes.ts").read_text(encoding="utf-8")

        self.assertIn('section: "review"', routes)
        self.assertIn('tab === "review" && <ReviewPage', main)
        self.assertLess(main.index("愿望单</button>"), main.index("待确认</button>"))
        self.assertNotIn('discoverSection === "review"', main)
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
        self.assertIn('{ page: "subscriptions", section: "review" }', component)
        self.assertIn('{ page: "cross-cloud" }', component)
        self.assertIn('{ page: "media-server" }', component)

    def test_discovery_waits_for_provider_config_and_reports_transfer_failures(self):
        main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        styles = (ROOT / "frontend/src/styles.css").read_text(encoding="utf-8")

        self.assertIn("providersLoaded", main)
        self.assertIn("providersLoadError", main)
        self.assertNotIn('setEnabledProviders(["quark"])', main)
        self.assertIn("网盘配置读取失败，请刷新页面", main)
        self.assertIn('batchProviders.length > 1 ? "两边网盘已同时"', main)
        self.assertIn("开始转存（批次 #", main)
        self.assertIn("buildCloudBatchItems(providers, false, trackingTaskIds)", main)
        self.assertIn("selectedUrl ? [selectedUrl] : resourcePlanShareUrls(status)", main)
        self.assertIn("当前快照没有可直接转存的资源，后续追更会按计划继续检查", main)
        self.assertIn("已更 ${airedEpisodes}/${totalEpisodes} 集 · ${availableEpisodes} 集可转", main)
        self.assertIn(".notice.error", styles)

    def test_discovery_labels_and_submits_quark_to_p115_openlist_fallback(self):
        main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
        support = (ROOT / "frontend/src/features/discover/mediaDetailSupport.ts").read_text(encoding="utf-8")
        api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")

        self.assertIn('config.openlist_auto_sync', support)
        self.assertIn('["bidirectional", "qas_to_p115"]', support)
        self.assertIn("shouldOfferQuarkToP115Sync", main)
        self.assertIn('openlist_fallback_to_p115: provider === "quark" && shouldSyncQuarkToP115', main)
        self.assertIn("转存到夸克并同步到 115", main)
        self.assertIn("openlist_fallback_to_p115?: boolean", api)

    def test_activity_keeps_running_openlist_queue_on_top_but_moves_finished_history_below_jobs(self):
        activity = (ROOT / "frontend/src/features/activity/ActivityCenter.tsx").read_text(encoding="utf-8")
        running = '<OpenListQueueSection tasks={visibleRunningOpenListTasks}'
        jobs = "{visibleJobs.map((job) => {"
        finished = '<OpenListQueueSection tasks={visibleFinishedOpenListTasks} history'
        self.assertLess(activity.index(running), activity.index(jobs))
        self.assertLess(activity.index(jobs), activity.index(finished))
        self.assertIn('task.state === "running"', activity)
        self.assertIn('task.state !== "running"', activity)

    def test_openlist_settings_warn_when_interactive_completion_prerequisites_are_missing(self):
        panel = (ROOT / "frontend/src/features/settings/OpenListSettingsPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("config.quark_cloud_download_organizer_enabled", panel)
        self.assertIn("夸克云下载根与正式媒体库根相同", panel)

    def test_category_paths_use_an_inline_custom_editor_instead_of_browser_prompt(self):
        component = (ROOT / "frontend/src/features/settings/SettingsFormParts.tsx").read_text(encoding="utf-8")

        self.assertIn('aria-label="自定义分类标识"', component)
        self.assertIn("function addCustomPath()", component)
        self.assertNotIn("window.prompt(\"自定义分类标识", component)

    def test_quality_priority_uses_an_inline_custom_editor_instead_of_browser_prompt(self):
        component = (ROOT / "frontend/src/features/settings/SettingsFormParts.tsx").read_text(encoding="utf-8")

        self.assertIn('aria-label="自定义质量关键词"', component)
        self.assertIn("function addCustomKeyword()", component)
        self.assertIn("这个质量关键词已经存在", component)
        self.assertNotIn('window.prompt("输入自定义质量关键词', component)

    def test_mdcng_settings_are_collapsed_inside_the_builtin_adapter_card(self):
        page = (ROOT / "frontend/src/features/integrations/WebhookWorkspacePage.tsx").read_text(encoding="utf-8")

        self.assertIn("mdc-adapter-card", page)
        self.assertIn("aria-expanded={mdcOpen}", page)
        self.assertIn("{mdcOpen && <div", page)
        self.assertIn("<MdcWebhookSettings", page)
        self.assertIn("config.has_mdc_webhook_token", page)


if __name__ == "__main__":
    unittest.main()
