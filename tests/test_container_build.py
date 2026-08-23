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

    def test_application_drops_root_to_configured_uid_and_gid(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('ENTRYPOINT ["media-index-entrypoint"]', dockerfile)
        self.assertIn("sed -i 's/\\r$//' /usr/local/bin/media-index-entrypoint", dockerfile)
        self.assertIn('runtime_uid="${PUID:-10001}"', entrypoint)
        self.assertIn('runtime_gid="${PGID:-10001}"', entrypoint)
        self.assertIn('strm_output_root="${STRM_OUTPUT_ROOT:-/strm}"', entrypoint)
        self.assertIn('--reuid="$runtime_uid"', entrypoint)
        self.assertIn('--regid="$runtime_gid"', entrypoint)
        self.assertIn("--clear-groups", entrypoint)

    def test_entrypoint_assigns_only_the_strm_mount_root(self):
        entrypoint = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('chown "$runtime_uid:$runtime_gid" "$strm_output_root"', entrypoint)
        self.assertNotIn('chown -R "$runtime_uid:$runtime_gid" "$strm_output_root"', entrypoint)
        self.assertIn('chmod u+rwx "$strm_output_root"', entrypoint)
        self.assertIn("Unable to assign STRM output directory", entrypoint)

    def test_compose_sets_nas_runtime_uid_and_gid(self):
        for filename in ("docker-compose.yaml", "docker-compose.bridge.yaml"):
            compose = (ROOT / filename).read_text(encoding="utf-8")
            self.assertEqual(1, compose.count("PUID: ${PUID:-10001}"))
            self.assertEqual(1, compose.count("PGID: ${PGID:-10001}"))

    def test_management_and_playback_share_one_container(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('EXPOSE 8000 8097', dockerfile)
        self.assertIn('CMD ["python", "-m", "app.combined_server"]', dockerfile)
        for filename in ("docker-compose.yaml", "docker-compose.bridge.yaml"):
            compose = (ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn("media-index-playback:", compose)
            self.assertIn('- "8097:8097"', compose)


if __name__ == "__main__":
    unittest.main()
