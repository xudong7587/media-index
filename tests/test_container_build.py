import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContainerBuildTests(unittest.TestCase):
    def test_brand_icon_is_included_in_frontend_image_build(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY frontend/public ./public", dockerfile)
        self.assertTrue((ROOT / "frontend/public/assets/media-index-icon.png").is_file())

    def test_container_build_uses_locked_dependencies(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("pnpm install --frozen-lockfile", dockerfile)
        self.assertIn("pip install --no-cache-dir -r requirements.lock", dockerfile)
        self.assertTrue((ROOT / "frontend/pnpm-lock.yaml").is_file())
        self.assertTrue((ROOT / "requirements.lock").is_file())
        workspace = (ROOT / "frontend/pnpm-workspace.yaml").read_text(encoding="utf-8")
        self.assertIn("allowBuilds:\n  esbuild: true", workspace)

    def test_application_drops_root_after_fixing_data_permissions(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('ENTRYPOINT ["media-index-entrypoint"]', dockerfile)
        self.assertIn("sed -i 's/\\r$//' /usr/local/bin/media-index-entrypoint", dockerfile)
        self.assertIn("--reuid=10001", entrypoint)
        self.assertIn("--regid=10001", entrypoint)


if __name__ == "__main__":
    unittest.main()
