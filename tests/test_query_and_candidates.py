import unittest
import os
from unittest.mock import patch

from app.core.config import get_settings

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.candidate_ranker import rank_resource_candidates, score_resource_candidate
from app.services.query_planner import build_search_queries


class QueryAndCandidateTests(unittest.TestCase):
    def test_single_tv_plan_uses_canonical_title_then_english_without_season_or_year(self):
        target = MediaTarget(
            106449,
            "tv",
            "凡人修仙传",
            series_year="2020",
            season_number=1,
            episodes=(EpisodeTarget(1, 182, "2026-07-11"),),
        )
        queries = build_search_queries(target, max_queries=4)
        self.assertEqual(["凡人修仙传"], [query.keyword for query in queries])

    def test_movie_plan_tries_bare_title_then_english_without_year_filter(self):
        target = MediaTarget(1, "movie", "挽救计划", english_title="Project Hail Mary", series_year="2026")

        queries = build_search_queries(target, max_queries=4)

        self.assertEqual(["挽救计划", "Project Hail Mary"], [query.keyword for query in queries])

    def test_single_tv_plan_does_not_search_by_missing_episode_number(self):
        target = MediaTarget(
            1,
            "tv",
            "娴嬭瘯鍓?",
            series_year="2026",
            season_number=1,
            episodes=(EpisodeTarget(1, 7, "2026-07-10"),),
        )
        queries = build_search_queries(target, max_queries=8)
        self.assertNotIn("target_episode_sxxexx", {query.reason for query in queries})

    def test_variety_plan_does_not_expand_to_episode_or_date_queries(self):
        target = MediaTarget(
            1,
            "variety",
            "Test Show",
            season_number=2,
            episodes=(EpisodeTarget(2, 28, "2026-07-10"),),
        )
        queries = build_search_queries(target, max_queries=4)
        self.assertEqual("tmdb_canonical_zh", queries[0].reason)
        self.assertEqual(["Test Show"], [query.keyword for query in queries])

    def test_single_episode_plan_ignores_aliases(self):
        target = MediaTarget(
            1,
            "variety",
            "音乐缘计划",
            aliases=("音乐缘计划第二季",),
            season_number=2,
            episodes=(EpisodeTarget(2, 8, "2026-07-10"),),
        )
        queries = build_search_queries(target, max_queries=4)
        self.assertEqual(["音乐缘计划"], [query.keyword for query in queries])

    def test_variety_issue_title_does_not_change_resource_query(self):
        target = MediaTarget(
            1,
            "variety",
            "音乐缘计划",
            season_number=2,
            episodes=(EpisodeTarget(2, 14, "2025-11-28", title="第 6 期（中）：合作舞台"),),
        )
        queries = build_search_queries(target, max_queries=4)
        self.assertEqual(["音乐缘计划"], [query.keyword for query in queries])

    def test_multi_episode_variety_plan_stays_on_canonical_title(self):
        target = MediaTarget(
            261391,
            "variety",
            "喜剧之王单口季",
            aliases=("喜单",),
            season_number=3,
            episodes=(
                EpisodeTarget(3, 10, "2026-07-17", "第 10 集"),
                EpisodeTarget(3, 11, "2026-07-17", "第 11 集"),
            ),
        )

        queries = build_search_queries(target, max_queries=4)

        self.assertEqual("tmdb_canonical_zh", queries[0].reason)
        self.assertNotIn("target_air_date", {query.reason for query in queries})

    def test_multi_episode_tv_plan_stays_within_three_queries(self):
        target = MediaTarget(
            296206,
            "tv",
            "金特务：本色回归",
            season_number=1,
            episodes=tuple(EpisodeTarget(1, number) for number in range(1, 9)),
        )

        queries = build_search_queries(target, max_queries=4)

        self.assertEqual(1, len(queries))
        self.assertIn("金特务：本色回归", [query.keyword for query in queries])
        self.assertIn("tmdb_canonical_zh", {query.reason for query in queries})

    def target(self):
        return MediaTarget(
            123,
            "variety",
            "喜剧之王单口季",
            original_title="King of Stand-up Comedy",
            english_title="King of Stand-up Comedy",
            aliases=("喜单",),
            series_year="2024",
            season_number=3,
            season_year="2026",
        )

    def test_query_plan_uses_canonical_title_then_english_only(self):
        queries = build_search_queries(self.target())
        values = [item.keyword for item in queries]
        self.assertNotIn("喜单 第三季", values)
        self.assertIn("喜剧之王单口季", values)
        self.assertNotIn("King of Stand-up Comedy 第三季", values)
        self.assertEqual(["喜剧之王单口季", "King of Stand-up Comedy"], values)
        self.assertEqual(len(values), len(set(values)))

    def test_localized_alias_is_not_searched_but_english_title_is_the_only_fallback(self):
        target = MediaTarget(
            94997,
            "tv",
            "权力的游戏前传：龙族",
            original_title="House of the Dragon",
            english_title="House of the Dragon",
            aliases=("龙之家族",),
            season_number=2,
        )
        queries = build_search_queries(target, max_queries=4)
        values = [item.keyword for item in queries]
        self.assertNotIn("龙之家族", values)
        self.assertIn("House of the Dragon", values)
        self.assertNotIn("Дом дракона 第二季", values)

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

    def test_custom_early_release_and_low_resolution_keywords_are_rejected(self):
        target = MediaTarget(634649, "movie", "蜘蛛侠：英雄无归", series_year="2021")
        with patch.dict(os.environ, {"RESOURCE_EXCLUDED_KEYWORDS_JSON": '["TC","抢先","480p"]'}, clear=False):
            get_settings.cache_clear()
            ranked = rank_resource_candidates(target, [
                {"share_url": "https://pan.quark.cn/s/clear", "title": "蜘蛛侠：英雄无归 2021 1080p WEB-DL"},
                {"share_url": "https://pan.quark.cn/s/tc", "title": "蜘蛛侠：英雄无归 2021 TC 抢先 480p"},
            ])
        get_settings.cache_clear()
        self.assertFalse(ranked[0].rejected)
        self.assertTrue(ranked[1].rejected)
        self.assertTrue(any(reason.startswith("excluded_quality:") for reason in ranked[1].reasons))

    def test_movie_derivative_title_is_rejected_even_when_it_contains_the_full_title(self):
        target = MediaTarget(634649, "movie", "蜘蛛侠：英雄无归", series_year="2021")
        ranked = rank_resource_candidates(
            target,
            [
                {
                    "share_url": "https://pan.quark.cn/s/feature",
                    "title": "蜘蛛侠：英雄无归 2021 2160p",
                },
                {
                    "share_url": "https://pan.quark.cn/s/behind",
                    "title": "蜘蛛侠：英雄无归 电影幕后纪录片",
                },
            ],
            query="蜘蛛侠：英雄无归",
            query_priority=80,
        )
        self.assertEqual("https://pan.quark.cn/s/feature", ranked[0].share_url)
        self.assertFalse(ranked[0].rejected)
        self.assertTrue(ranked[1].rejected)
        self.assertIn("derivative_title", ranked[1].reasons)

    def test_long_running_tv_current_arc_year_is_not_rejected(self):
        target = MediaTarget(106449, "tv", "凡人修仙传", series_year="2020", season_number=1)
        ranked = rank_resource_candidates(
            target,
            [{"share_url": "https://pan.quark.cn/s/current", "title": "凡人修仙传 年番4 (2026) 更新182集"}],
        )
        self.assertFalse(ranked[0].rejected)
        self.assertIn("year_context_different", ranked[0].reasons)

    def test_candidate_body_cannot_fake_a_movie_title_match(self):
        target = MediaTarget(1108427, "movie", "海洋奇缘：启航", original_title="Moana", series_year="2026")
        ranked = rank_resource_candidates(
            target,
            [{
                "share_url": "https://pan.quark.cn/s/noise",
                "title": "2026-04-27合辑",
                "content": "搜索词：海洋奇缘：启航 2026；本条实际是其他资源",
            }],
        )
        self.assertIn("title_weak", ranked[0].reasons)
        self.assertNotIn("title_exact_or_contained", ranked[0].reasons)

    def test_unrelated_episodic_title_is_rejected_even_when_query_is_short_alias(self):
        target = MediaTarget(
            261391,
            "variety",
            "喜剧之王单口季",
            aliases=("喜单",),
            season_number=3,
            episodes=(EpisodeTarget(3, 12), EpisodeTarget(3, 13)),
        )
        ranked = rank_resource_candidates(
            target,
            [{"share_url": "https://pan.quark.cn/s/noise", "title": "2026-07-17合辑：短剧全集"}],
            query="喜单 第三季",
            query_priority=115,
        )
        self.assertTrue(ranked[0].rejected)
        self.assertIn("episodic_title_mismatch", ranked[0].reasons)

    def test_tv_weak_title_is_left_for_file_matching(self):
        target = MediaTarget(
            94997,
            "tv",
            "龙之家族",
            aliases=("House of the Dragon",),
            season_number=3,
            episodes=(EpisodeTarget(3, 1, "2026-06-21", match_tokens=("S03E01", "E01")),),
        )
        candidate = score_resource_candidate(
            target,
            {"share_url": "https://115.com/s/example", "title": "HOTD.S03E01.2160p.WEB-DL"},
            query="龙之家族",
            query_priority=90,
        )
        self.assertFalse(candidate.rejected)
        self.assertIn("title_weak", candidate.reasons)

    def test_variety_weak_title_still_requires_strict_filtering(self):
        target = MediaTarget(
            1,
            "variety",
            "喜剧之王单口季",
            season_number=3,
            episodes=(EpisodeTarget(3, 10, "2026-07-17", "第3期（一）", ("第3期", "20260717")),),
        )
        candidate = score_resource_candidate(
            target,
            {"share_url": "https://pan.quark.cn/s/example", "title": "Unknown.Show.20260717.第3期"},
            query="喜剧之王单口季",
            query_priority=90,
        )
        self.assertFalse(candidate.rejected)
        self.assertIn("target_air_date", candidate.reasons)

    def test_variety_chinese_calendar_date_is_high_value_candidate_evidence(self):
        target = MediaTarget(
            1,
            "variety",
            "喜剧之王单口季",
            season_number=3,
            episodes=(EpisodeTarget(3, 10, "2026-07-17"),),
        )
        candidate = score_resource_candidate(
            target,
            {"share_url": "https://pan.quark.cn/s/example", "title": "7月17日更新 第3期（上）"},
            query="喜剧之王单口季",
            query_priority=190,
        )
        self.assertFalse(candidate.rejected)
        self.assertIn("target_air_date", candidate.reasons)

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
