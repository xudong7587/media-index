import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendWebhookWorkspaceContractTests(unittest.TestCase):
    def test_workspace_keeps_mdc_adapter_and_adds_generic_connection_manager(self):
        source = (ROOT / "frontend/src/features/integrations/WebhookWorkspacePage.tsx").read_text(encoding="utf-8")
        self.assertIn("WebhookConnectionManager", source)
        self.assertIn("MdcWebhookSettings", source)
        self.assertIn("<strong>MDC-NG</strong>", source)
        self.assertIn("内置适配器 · 专用接收端与增量 STRM", source)
        self.assertIn("aria-expanded={mdcOpen}", source)
        self.assertIn("保存 MDC-NG 设置", source)

    def test_generic_manager_exposes_both_directions_and_truthful_statuses(self):
        source = (ROOT / "frontend/src/features/integrations/WebhookConnectionManager.tsx").read_text(encoding="utf-8")
        for text in (
            "新建 Webhook",
            "接收消息",
            "发送消息",
            "已连通",
            "待验证",
            "投递异常",
            "Standard Webhooks",
            "CloudEvents 1.0",
            "查看 MDC-NG 设置",
        ):
            self.assertIn(text, source)

    def test_existing_mdc_contract_remains_on_original_endpoint(self):
        source = (ROOT / "frontend/src/features/integrations/MdcWebhookSettings.tsx").read_text(encoding="utf-8")
        self.assertIn('const WEBHOOK_PATH = "/api/webhooks/strm-incremental"', source)
        self.assertIn("X-MediaIndex-Settings-Test", source)
        self.assertIn("mdc_webhook_scan_path", source)


if __name__ == "__main__":
    unittest.main()
