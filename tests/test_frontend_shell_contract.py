import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendShellContractTests(unittest.TestCase):
    def setUp(self):
        self.shell = (ROOT / "frontend/src/app/ApplicationShell.tsx").read_text(encoding="utf-8")
        self.styles = (ROOT / "frontend/src/app/emil-workbench.css").read_text(encoding="utf-8")
        self.main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")

    def test_sidebar_has_accessible_collapse_and_expand_labels(self):
        self.assertIn('"收起工作区导航"', self.shell)
        self.assertIn('"展开工作区导航"', self.shell)

    def test_sidebar_collapse_state_is_persisted(self):
        self.assertGreaterEqual(self.shell.count('localStorage.getItem("mi-sidebar-collapsed")'), 1)
        self.assertGreaterEqual(self.shell.count('localStorage.setItem("mi-sidebar-collapsed"'), 1)

    def test_collapsed_sidebar_hides_text_and_keeps_icon_layout(self):
        self.assertIn(".app-shell.sidebar-collapsed .app-sidebar nav button > span", self.styles)
        self.assertIn(".app-shell.sidebar-collapsed .sidebar-footer .icon", self.styles)

    def test_sidebar_displays_application_version(self):
        self.assertIn("MediaIndex v{version}", self.shell)
        self.assertIn("version={appVersion}", self.main)

    def test_global_settings_footer_no_longer_displays_version(self):
        self.assertNotIn("<span>版本 {config.version}</span>", self.main)

    def test_mobile_navigation_keeps_its_existing_toggle(self):
        self.assertIn('className="mobile-nav-toggle"', self.shell)
        self.assertIn("@media (max-width: 700px)", self.styles)


if __name__ == "__main__":
    unittest.main()
