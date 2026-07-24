import unittest

from app.domain.media import LinkResolution, RenamePair
from app.services.episode_naming import adapt_resolution_to_existing_episode_names, infer_episode_name_template


class EpisodeNamingTests(unittest.TestCase):
    def response(self, names):
        return {
            "success": True,
            "data": {"list": [{"file_name": name, "dir": False} for name in names]},
        }

    def test_infers_dominant_video_template_and_preserves_new_extension(self):
        response = self.response(
            [
                "凡人修仙传 - S01E181 - 第 181 集.mkv",
                "凡人修仙传 - S01E182 - 第 182 集.mp4",
                "凡人修仙传 - S01E183 - 第 183 集.mkv",
                "凡人修仙传 - S01E183 - 第 183 集.nfo",
                "凡人修仙传.2020.S01E180.mkv",
            ]
        )
        resolution = LinkResolution(
            True,
            "ready",
            "ready",
            rename_pairs=(RenamePair("source.mp4", "source", "凡人修仙传.2020.S01E184.mp4", episode_number=184),),
        )

        adapted = adapt_resolution_to_existing_episode_names(resolution, response, 1)

        self.assertEqual("凡人修仙传 - S01E184 - 第 184 集.mp4", adapted.rename_pairs[0].replacement)

    def test_mixed_or_sparse_names_fall_back_to_standard_rename(self):
        response = self.response(["A.S01E01.mkv", "B - S01E02.mp4"])
        self.assertIsNone(infer_episode_name_template(response, 1))

    def test_episode_digit_growth_is_one_template(self):
        response = self.response(
            [
                "凡人修仙传 - S01E01 - 第 1 集.mp4",
                "凡人修仙传 - S01E99 - 第 99 集.mp4",
                "凡人修仙传 - S01E183 - 第 183 集.mkv",
            ]
        )
        template = infer_episode_name_template(response, 1)
        self.assertIsNotNone(template)
        self.assertEqual("凡人修仙传 - S01E184 - 第 184 集.mkv", template.render(1, 184, ".mkv"))


if __name__ == "__main__":
    unittest.main()
