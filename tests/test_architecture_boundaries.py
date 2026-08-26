import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "backend" / "app"
FEATURE_ROOT = ROOT / "frontend" / "src" / "features"

# This exists only to stop legacy debt from spreading. Remove entries as the
# WECOM orchestration is extracted into a shared application workflow.
LEGACY_SERVICE_TO_API_IMPORTS = {
    "services/wecom_callback.py": {
        "app.api.review",
        "app.api.transfers",
    },
}

# These imports predate the target technical-layer direction. They are exact
# quarantine lists: removals are welcome, additions require moving the shared
# contract to a lower layer instead of widening the allowlist.
LEGACY_PROVIDER_TO_SERVICE_IMPORTS = {
    "providers/base.py": {"app.services.share_inspector"},
    "providers/moviepilot_115.py": {"app.services.share_inspector"},
    "providers/p115.py": {"app.services.paths", "app.services.share_inspector"},
    "providers/qas.py": {"app.services.qas_executor", "app.services.share_inspector"},
    "providers/quark.py": {"app.services.paths", "app.services.share_inspector"},
}

LEGACY_CLIENT_TO_SERVICE_IMPORTS = {
    "clients/tmdb.py": {"app.services.cache", "app.services.resource_aliases"},
}

LEGACY_FRONTEND_CROSS_FEATURE_IMPORTS = {
    "activity/ActivityCenter.tsx": {"openlist/OpenListTaskMonitor"},
    "cloud/ChannelWorkspace.tsx": {"settings/SettingsFormParts"},
    "cloud/CloudCenter.tsx": {"settings/QuarkReadOnlySettings"},
    "cloud/MediaLibraryWorkspace.tsx": {"settings/SettingsFormParts"},
    "integrations/MdcWebhookSettings.tsx": {
        "settings/SettingsFormParts",
        "settings/SettingsUi",
    },
    "strm/StrmPortal.tsx": {
        "openlist/OpenListSettingsTools",
        "settings/SettingsFormParts",
        "settings/SettingsUi",
    },
    "workspace/ResourceAcquisitionPage.tsx": {
        "cloud/ChannelWorkspace",
        "settings/SettingsFormParts",
        "settings/SettingsUi",
    },
    "workspace/WorkspaceSections.tsx": {
        "openlist/OpenListSettingsTools",
        "settings/QuarkReadOnlySettings",
        "settings/SettingsFormParts",
        "settings/SettingsUi",
    },
}


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(APP_ROOT).with_suffix("")
    package = ("app", *relative.parts[:-1])
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            parent_hops = node.level - 1
            prefix = package[: max(0, len(package) - parent_hops)]
            module = ".".join((*prefix, *(node.module or "").split("."))).rstrip(".")
            if module:
                imports.add(module)
            if not node.module:
                imports.update(f"{module}.{alias.name}" for alias in node.names)
            continue
        if node.module:
            imports.add(node.module)
            if node.module == "app":
                imports.update(f"app.{alias.name}" for alias in node.names)
    return imports


def _cross_feature_imports(path: Path) -> set[str]:
    owner = path.relative_to(FEATURE_ROOT).parts[0]
    imports: set[str] = set()
    source = path.read_text(encoding="utf-8")
    specifiers = set(re.findall(r"from\s+[\"']([^\"']+)[\"']", source))
    specifiers.update(re.findall(r"import\s+[\"']([^\"']+)[\"']", source))
    specifiers.update(re.findall(r"import\s*\(\s*[\"']([^\"']+)[\"']\s*\)", source))
    for specifier in specifiers:
        if not specifier.startswith("."):
            continue
        target = (path.parent / specifier).resolve()
        try:
            relative = target.relative_to(FEATURE_ROOT.resolve())
        except (ValueError, IndexError):
            continue
        target_owner = relative.parts[0]
        if target_owner != owner:
            imports.add(relative.as_posix())
    return imports


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_services_do_not_gain_route_dependencies(self):
        for path in (APP_ROOT / "services").glob("*.py"):
            relative = path.relative_to(APP_ROOT).as_posix()
            allowed = LEGACY_SERVICE_TO_API_IMPORTS.get(relative, set())
            imports = {
                module for module in _absolute_imports(path) if module.startswith("app.api")
            }
            self.assertLessEqual(
                imports,
                allowed,
                f"{relative} imports route-layer code: {sorted(imports - allowed)}",
            )

    def test_domain_remains_free_of_outward_dependencies(self):
        forbidden = (
            "app.api",
            "app.services",
            "app.providers",
            "app.clients",
            "app.db",
            "app.core",
        )
        for path in (APP_ROOT / "domain").glob("*.py"):
            imports = {module for module in _absolute_imports(path) if module.startswith(forbidden)}
            self.assertFalse(imports, f"{path.name} has outward dependencies: {sorted(imports)}")

    def test_providers_do_not_gain_workflow_dependencies(self):
        for path in (APP_ROOT / "providers").glob("*.py"):
            relative = path.relative_to(APP_ROOT).as_posix()
            allowed = LEGACY_PROVIDER_TO_SERVICE_IMPORTS.get(relative, set())
            imports = {module for module in _absolute_imports(path) if module.startswith("app.services")}
            self.assertLessEqual(
                imports,
                allowed,
                f"{relative} imports new workflow code: {sorted(imports - allowed)}",
            )

    def test_clients_do_not_gain_workflow_dependencies(self):
        for path in (APP_ROOT / "clients").glob("*.py"):
            relative = path.relative_to(APP_ROOT).as_posix()
            allowed = LEGACY_CLIENT_TO_SERVICE_IMPORTS.get(relative, set())
            imports = {module for module in _absolute_imports(path) if module.startswith("app.services")}
            self.assertLessEqual(
                imports,
                allowed,
                f"{relative} imports new workflow code: {sorted(imports - allowed)}",
            )

    def test_frontend_cross_feature_imports_do_not_spread(self):
        for path in FEATURE_ROOT.rglob("*"):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            relative = path.relative_to(FEATURE_ROOT).as_posix()
            allowed = LEGACY_FRONTEND_CROSS_FEATURE_IMPORTS.get(relative, set())
            imports = _cross_feature_imports(path)
            self.assertLessEqual(
                imports,
                allowed,
                f"{relative} imports new feature internals: {sorted(imports - allowed)}",
            )

    def test_frontend_legacy_entry_does_not_keep_growing(self):
        main = ROOT / "frontend" / "src" / "main.tsx"
        line_count = len(main.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            line_count,
            3871,
            "Extract new UI from frontend/src/main.tsx into frontend/src/features/ before adding more code.",
        )
