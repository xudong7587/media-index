import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "backend" / "app"

# This exists only to stop legacy debt from spreading. Remove entries as the
# WECOM orchestration is extracted into a shared application workflow.
LEGACY_SERVICE_TO_API_IMPORTS = {
    "services/wecom_callback.py": {
        "app.api.review",
        "app.api.transfers",
    },
}


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_services_do_not_gain_route_dependencies(self):
        for path in (APP_ROOT / "services").glob("*.py"):
            relative = path.relative_to(APP_ROOT).as_posix()
            allowed = LEGACY_SERVICE_TO_API_IMPORTS.get(relative, set())
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.api")
            }
            self.assertLessEqual(
                imports,
                allowed,
                f"{relative} imports route-layer code: {sorted(imports - allowed)}",
            )

    def test_frontend_legacy_entry_does_not_keep_growing(self):
        main = ROOT / "frontend" / "src" / "main.tsx"
        line_count = len(main.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            line_count,
            3888,
            "Extract new UI from frontend/src/main.tsx into frontend/src/features/ before adding more code.",
        )
