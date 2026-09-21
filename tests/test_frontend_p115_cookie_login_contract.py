import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class P115CookieLoginContractTests(unittest.TestCase):
    def test_api_exposes_the_115_cookie_qr_endpoints(self):
        api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")

        self.assertIn('startP115CookieQrLogin: (app?: string) =>', api)
        self.assertIn('"/api/cloud/p115/cookie/qrcode"', api)
        self.assertIn("`/api/cloud/p115/cookie/qrcode/${encodeURIComponent(sessionId)}`", api)
        self.assertIn('"waiting" | "scanned" | "done" | "expired" | "canceled" | "failed"', api)

    def test_scan_login_polls_every_two_seconds_and_stops_on_a_terminal_status(self):
        component = (ROOT / "frontend/src/components/cloud/P115CookieQrLogin.tsx").read_text(encoding="utf-8")

        self.assertIn("const POLL_INTERVAL_MS = 2000;", component)
        self.assertIn("window.setTimeout(() => void tick(), POLL_INTERVAL_MS);", component)
        self.assertIn("api.pollP115CookieQrLogin(sessionId)", component)
        self.assertIn('state.status === "done"', component)
        self.assertIn('state.status === "expired" || state.status === "canceled"', component)

    def test_scan_login_warns_about_the_device_kick_and_only_shows_the_masked_cookie(self):
        component = (ROOT / "frontend/src/components/cloud/P115CookieQrLogin.tsx").read_text(encoding="utf-8")

        self.assertIn("踢掉该设备上已登录的同一 App 会话", component)
        self.assertIn("state.cookie_masked", component)
        self.assertIn('useState("windows")', component)
        self.assertIn("Windows 版（推荐，与播放通道一致）", component)
        self.assertNotIn("P115_COOKIE", component)

    def test_115_connection_page_mounts_the_scan_login(self):
        page = (ROOT / "frontend/src/features/workspace/WorkspaceSections.tsx").read_text(encoding="utf-8")

        self.assertIn('import { P115CookieQrLogin } from "../../components/cloud/P115CookieQrLogin";', page)
        self.assertIn("<P115CookieQrLogin disabled={busy !== \"\"} onSaved={() => void refresh()} />", page)
        self.assertIn('title="扫码登录"', page)


if __name__ == "__main__":
    unittest.main()
