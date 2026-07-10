import unittest

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.candidate_ranker import rank_resource_candidates
from app.services.query_planner import build_search_queries


class QueryAndCandidateTests(unittest.TestCase):
    def test_single_episode_queries_are_tried_before_season_queries(self):
        target = MediaTarget(
            1,
            "variety",
            "Test Show",
            season_number=2,
            episodes=(EpisodeTarget(2, 28, "2026-07-10"),),
        )
        queries = build_search_queries(target, max_queries=4)
        self.assertEqual("target_episode_sxxexx", queries[0].reason)
        self.assertIn("S02E28", queries[0].keyword)
        self.assertIn("target_variety_issue", {query.reason for query in queries})
        self.assertIn("target_air_date", {query.reason for query in queries})
        self.assertIn("0710", next(query.keyword for query in queries if query.reason == "target_air_date"))

    def test_single_episode_plan_uses_alias_before_broad_queries(self):
        target = MediaTarget(
            1,
            "variety",
            "音乐缘计划",
            aliases=("音乐缘计划第二季",),
            season_number=2,
            episodes=(EpisodeTarget(2, 8, "2026-07-10"),),
        )
        queries = build_search_queries(target, max_queries=4)
        self.assertIn("target_episode_alias", {query.reason for query in queries})
        self.assertNotIn("canonical_title_broad", {query.reason for query in queries})

    def test_variety_query_uses_tmdb_issue_part_instead_of_episode_ordinal(self):
        target = MediaTarget(
            1,
            "variety",
            "音乐缘计划",
            season_number=2,
            episodes=(EpisodeTarget(2, 14, "2025-11-28", title="第 6 期（中）：合作舞台"),),
        )
        queries = build_search_queries(target, max_queries=4)
        issue_query = next(query for query in queries if query.reason == "target_variety_issue")
        self.assertEqual("音乐缘计划 第6期中", issue_query.keyword)
        self.assertIn("canonical_title_fallback", {query.reason for query in queries})

    def target(self):
        return MediaTarget(
            123,
            "variety",
            "喜剧之王单口季",
            original_title="King of Stand-up Comedy",
            aliases=("喜单",),
            series_year="2024",
            season_number=3,
            season_year="2026",
        )

    def test_query_plan_uses_title_aliases_and_season(self):
        queries = build_search_queries(self.target())
        values = [item.keyword for item in queries]
        self.assertEqual("喜剧之王单口季 第3季", values[0])
        self.assertIn("King of Stand-up Comedy S03", values)
        self.assertEqual(len(values), len(set(values)))

    def test_wrong_season_and_year_are_rejected(self):
        ranked = rank_resource_candidates(
            self.target(),
            [
                {"share_url": "https://pan.quark.cn/s/right", "title": "喜剧之王单口季 第3季 2026"},
                {"share_url": "https://pan.quark.cn/s/wrong-season", "title": "喜剧之王单口季 第2季 2024"},
                {"share_url": "https://pan.quark.cn/s/wrong-year", "title": "喜剧之王单口季 第3季 2023"},
            ],
        )
        self.assertEqual("https://pan.quark.cn/s/right", ranked[0].share_url)
        self.assertFalse(ranked[0].rejected)
        self.assertTrue(ranked[1].rejected)
        self.assertTrue(ranked[2].rejected)

    def test_derivative_content_is_penalized(self):
        ranked = rank_resource_candidates(
            self.target(),
            [
                {"share_url": "https://pan.quark.cn/s/main", "title": "喜剧之王单口季 第3季"},
                {"share_url": "https://pan.quark.cn/s/trailer", "title": "喜剧之王单口季 第3季 预告花絮"},
            ],
        )
        self.assertEqual("https://pan.quark.cn/s/main", ranked[0].share_url)
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_equally_relevant_candidates_are_newest_first(self):
        ranked = rank_resource_candidates(
            self.target(),
            [
                {
                    "share_url": "https://pan.quark.cn/s/old",
                    "title": "King of Stand-up Comedy S03 2026",
                    "datetime": "2026-06-01T00:00:00Z",
                },
                {
                    "share_url": "https://pan.quark.cn/s/new",
                    "title": "King of Stand-up Comedy S03 2026",
                    "datetime": "2026-07-10T00:00:00Z",
                },
            ],
        )
        self.assertEqual("https://pan.quark.cn/s/new", ranked[0].share_url)

    def test_update_progress_prioritizes_share_covering_target_episode(self):
        target = MediaTarget(
            123,
            "variety",
            "音乐缘计划",
            season_number=2,
            episodes=(EpisodeTarget(2, 28, "2026-07-10", match_tokens=("第28期",)),),
        )
        ranked = rank_resource_candidates(
            target,
            [
                {"share_url": "https://pan.quark.cn/s/old", "title": "音乐缘计划 第二季 更新至27期"},
                {"share_url": "https://pan.quark.cn/s/new", "title": "音乐缘计划 第二季 更新至28期"},
            ],
            query_priority=165,
        )
        self.assertEqual("https://pan.quark.cn/s/new", ranked[0].share_url)
        self.assertIn("updated_through_target", ranked[0].reasons)
        self.assertIn("update_lags_target", ranked[1].reasons)


if __name__ == "__main__":
    unittest.main()
