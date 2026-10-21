import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendShellContractTests(unittest.TestCase):
    """Guard the shipped native entry, rather than the retired React shell."""

    def setUp(self):
        self.main = (ROOT / "frontend/src/next/main.js").read_text(encoding="utf-8")
        self.styles = (ROOT / "frontend/src/next/preview.css").read_text(encoding="utf-8")
        self.adaptations = (ROOT / "frontend/src/next/next.css").read_text(encoding="utf-8")

    def test_html_loads_the_accepted_native_shell(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        self.assertIn('src="/src/next/main.js"', html)
        self.assertNotIn('src="/src/main.tsx"', html)
        self.assertIn('<aside class="sidebar" id="sidebar">', self.main)
        self.assertIn('<nav class="nav" aria-label="主导航">', self.main)

    def test_menu_has_accessible_open_close_state_and_target(self):
        self.assertIn('aria-label="打开菜单" aria-controls="sidebar" aria-expanded="false"', self.main)
        self.assertIn('setAttribute("aria-label", open ? "关闭菜单" : "打开菜单")', self.main)
        self.assertIn('setAttribute("aria-expanded", String(Boolean(open)))', self.main)

    def test_backdrop_closes_the_drawer_and_resets_accessibility_state(self):
        binding = self.main.split('document.querySelector("[data-menu-close]")?.addEventListener', 1)[1].split("\n", 1)[0]
        self.assertIn('classList.remove("menu-open")', binding)
        self.assertIn('setAttribute("aria-expanded", "false")', binding)
        self.assertIn('setAttribute("aria-label", "打开菜单")', binding)

    def test_active_navigation_is_exposed_to_assistive_technology(self):
        self.assertIn('aria-current="page"', self.main)
        self.assertIn('data-route="${page}"', self.main)
        self.assertIn('id="content"', self.main)

    def test_sidebar_keeps_the_server_version_after_navigation(self):
        self.assertIn('id="version">MediaIndex${state.config?.version', self.main)
        self.assertIn('esc(state.config.version)', self.main)
        self.assertIn('status.version', self.main)

    def test_mobile_drawer_uses_the_shared_button_and_responsive_layout(self):
        self.assertIn('class="icon-btn menu-btn" data-menu', self.main)
        self.assertIn('@media(max-width:1000px){.menu-btn.icon-btn{display:grid}}', self.adaptations)
        self.assertIn('.app.menu-open .sidebar', self.styles)
        self.assertIn('.menu-backdrop', self.styles)


if __name__ == "__main__":
    unittest.main()
