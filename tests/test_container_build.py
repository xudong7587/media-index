import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContainerBuildTests(unittest.TestCase):
    def test_brand_icon_is_included_in_frontend_image_build(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY frontend/public ./public", dockerfile)
        self.assertTrue((ROOT / "frontend/public/assets/media-index-icon.png").is_file())


if __name__ == "__main__":
    unittest.main()
