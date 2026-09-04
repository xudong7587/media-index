import unittest
from unittest.mock import patch

from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget, ResourceCandidate
from app.services.resource_probe import _probe_resource_availability, get_cached_resource_availability, probe_resource_availability


class MemoryCache:
    value = None

    def __init__(self, namespace):
        self.namespace = namespace

    def get(self, key, ttl_seconds):
        return type(self).value

    def set(self, key, value):
        type(self).value = value


class ResourceProbeCacheTests(unittest.TestCase):
    def setUp(self):
        MemoryCache.value = None

    @patch("app.services.resource_probe.resolve_provider_key", return_value="quark")
    @patch("app.services.resource_probe.FileCache", MemoryCache)
    @patch("app.services.resource_probe._probe_resource_availability")
    def test_reuses_recent_probe_result(self, probe, _provider):
        probe.return_value = {"ok": True, "found": True, "message": "found"}

        first = probe_resource_availability(123, "tv", 2)
        second = probe_resource_availability(123, "tv", 2)

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(1, probe.call_count)

    @patch("app.services.resource_probe.resolve_provider_key", return_value="quark")
    @patch("app.services.resource_probe.FileCache", MemoryCache)
    def test_cache_only_read_does_not_start_a_probe(self, _provider):
        MemoryCache.value = {"ok": True, "found": True, "message": "verified"}

        result = get_cached_resource_availability(123, "tv", 1)

        self.assertTrue(result["found"])
        self.assertTrue(result["cached"])

    @patch("app.services.resource_probe.resolve_provider_key", return_value="quark")
    @patch("app.services.resource_probe.FileCache", MemoryCache)
    @patch("app.services.resource_probe._probe_resource_availability")
    def test_refresh_bypasses_cached_result(self, probe, _provider):
        MemoryCache.value = {"ok": True, "found": True, "message": "old"}
        probe.return_value = {"ok": True, "found": False, "message": "fresh"}

        result = probe_resource_availability(123, "tv", 2, refresh=True)

        self.assertFalse(result["cached"])
        self.assertFalse(result["found"])
        self.assertEqual(1, probe.call_count)

    @patch("app.services.resource_probe.resolve_provider_key", return_value="quark")
    @patch("app.services.resource_probe.FileCache", MemoryCache)
    @patch("app.services.resource_probe._probe_resource_availability")
    def test_slow_negative_probe_cannot_replace_concurrent_positive_result(self, probe, _provider):
        def finish_after_positive(*args, **kwargs):
            MemoryCache.value = {"ok": True, "found": True, "message": "verified"}
            return {"ok": True, "found": False, "message": "stale negative"}

        probe.side_effect = finish_after_positive

        result = probe_resource_availability(123, "tv", 1)

        self.assertTrue(result["found"])
        self.assertEqual("verified", result["message"])
        self.assertTrue(MemoryCache.value["found"])

    def test_moviepilot_candidate_is_reported_as_found_and_requires_review(self):
        candidate = ResourceCandidate(
            "https://115.com/s/example",
            provider="moviepilot_115",
            cloud_type="115",
            reasons=("external_organize_requires_confirmation",),
        )
        resolution = LinkResolution(
            False,
            "needs_review",
            "确认后提交 MoviePilot",
            reviewed_candidates=(candidate,),
        )
        with (
            patch("app.services.resource_probe.resolve_media_target", return_value=MediaTarget(1, "movie", "测试")),
            patch("app.services.resource_probe.resolve_movie_source", return_value=resolution),
        ):
            result = _probe_resource_availability(1, "movie")
        self.assertTrue(result["found"])
        self.assertTrue(result["requires_review"])
        self.assertEqual(["115"], result["cloud_types"])
        self.assertEqual("", result["share_url"])
        self.assertEqual("https://115.com/s/example", result["source_share_url"])
        self.assertEqual(["https://115.com/s/example"], [item["share_url"] for item in result["candidates"]])

    def test_unverified_p115_candidate_is_reported_as_found(self):
        candidate = ResourceCandidate(
            "https://115cdn.com/s/example",
            provider="p115",
            cloud_type="115",
            reasons=("provider_inspection_unavailable",),
        )
        resolution = LinkResolution(
            False,
            "needs_review",
            "PanSou 已找到 115 候选资源，但 Cookie 无法验证",
            reviewed_candidates=(candidate,),
        )
        with (
            patch("app.services.resource_probe.resolve_media_target", return_value=MediaTarget(1, "movie", "测试")),
            patch("app.services.resource_probe.resolve_movie_source", return_value=resolution),
        ):
            result = _probe_resource_availability(1, "movie", provider="p115")

        self.assertTrue(result["found"])
        self.assertTrue(result["requires_review"])
        self.assertEqual(1, result["candidate_count"])
        self.assertEqual("https://115cdn.com/s/example", result["source_share_url"])

    def test_tv_probe_checks_all_aired_episodes_not_only_latest(self):
        target = MediaTarget(
            94997,
            "tv",
            "龙之家族",
            season_number=3,
            episodes=(
                EpisodeTarget(3, 1, "2026-06-21"),
                EpisodeTarget(3, 2, "2026-06-28"),
                EpisodeTarget(3, 3, "2099-01-01"),
            ),
        )
        resolution = LinkResolution(
            True,
            "matched",
            "found",
            matches=(
                type("Match", (), {"episode_numbers": (1,)})(),
                type("Match", (), {"episode_numbers": (2,)})(),
            ),
        )
        with (
            patch("app.services.resource_probe.resolve_media_target", return_value=target),
            patch("app.services.resource_probe.get_transfer_provider", return_value=object()),
            patch("app.services.resource_probe.resolve_standard_tv_source", return_value=resolution) as resolver,
        ):
            result = _probe_resource_availability(94997, "tv", 3, "p115")

        probed_target = resolver.call_args.args[0]
        self.assertEqual((1, 2), tuple(episode.episode_number for episode in probed_target.episodes))
        self.assertTrue(result["found"])
        self.assertEqual(3, result["total_episode_count"])
        self.assertEqual([1, 2], result["aired_episode_numbers"])
        self.assertEqual(2, result["aired_episode_count"])
        self.assertEqual(2, result["available_episode_count"])

    def test_discovery_uses_resolver_for_canonical_search_and_fallbacks(self):
        settings = type("Settings", (), {"pansou_search_timeout_seconds": 45})()
        with (
            patch("app.services.resource_probe.PansouClient") as pansou_cls,
            patch("app.services.resource_probe.get_settings", return_value=settings),
            patch("app.services.resource_probe.resolve_media_target", return_value=MediaTarget(1, "movie", "挽救计划")) as resolve_target,
            patch("app.services.resource_probe.get_transfer_provider", return_value=object()),
            patch("app.services.resource_probe.resolve_movie_source", return_value=LinkResolution(False, "no_resource", "没有候选")) as resolver,
        ):
            result = _probe_resource_availability(1, "movie", title="挽救计划", year="2026")

        self.assertFalse(result["found"])
        self.assertEqual("no_resource", result["stage"])
        resolve_target.assert_called_once()
        pansou_cls.return_value.search_detailed.assert_not_called()
        self.assertEqual(6, resolver.call_args.kwargs["max_queries"])

    def test_probe_snapshot_keeps_all_same_search_provider_links_for_transfer(self):
        urls = [
            "https://pan.quark.cn/s/episode-one",
            "https://pan.quark.cn/s/episode-two",
        ]
        pansou_result = type("SearchResult", (), {
            "items": [{"share_url": url, "provider": "quark", "cloud_type": "quark"} for url in urls],
        })()
        resolution = LinkResolution(True, "ready", "found", share_url=urls[0])
        settings = type("Settings", (), {"pansou_search_timeout_seconds": 45})()

        def resolve_with_snapshot(*args, **kwargs):
            kwargs["pansou"].search_detailed("测试电影", result_mode="all")
            return resolution

        with (
            patch("app.services.resource_probe.PansouClient") as pansou_cls,
            patch("app.services.resource_probe.get_settings", return_value=settings),
            patch("app.services.resource_probe.resolve_media_target", return_value=MediaTarget(1, "movie", "测试电影")),
            patch("app.services.resource_probe.get_transfer_provider", return_value=object()),
            patch("app.services.resource_probe.resolve_movie_source", side_effect=resolve_with_snapshot),
        ):
            pansou_cls.return_value.configured.return_value = True
            pansou_cls.return_value.search_detailed.return_value = pansou_result
            result = _probe_resource_availability(1, "movie", provider="quark", title="测试电影")

        self.assertTrue(result["plan_reusable"])
        self.assertEqual(urls, result["transfer_share_urls"])


if __name__ == "__main__":
    unittest.main()
