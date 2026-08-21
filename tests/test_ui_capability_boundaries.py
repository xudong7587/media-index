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
        self.assertIn("执行器：OpenList", cross_cloud_page)
        self.assertIn("OpenList 所在节点", cross_cloud_page)
        self.assertNotIn("CrossCloudTransferCenter", cross_cloud_page)
        self.assertIn("不宣称原生秒传", cross_cloud_page)

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


if __name__ == "__main__":
    unittest.main()
