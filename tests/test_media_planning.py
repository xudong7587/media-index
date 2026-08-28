from datetime import date

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.media_planning import (
    MEDIA_PLAN_VERSION,
    build_episode_coverage,
    build_media_plan,
    positive_episode_numbers,
    target_episode_coverage,
)
from app.api.transfers import MediaPlanInput, TransferCreate, _transfer_with_media_plan


def test_positive_episode_numbers_is_the_shared_normalizer():
    assert positive_episode_numbers([3, "1", 3, 0, -1, "bad"]) == (1, 3)


def test_coverage_distinguishes_missing_from_pending_transfer():
    coverage = build_episode_coverage(
        total=range(1, 6),
        aired=range(1, 5),
        available=(1, 2, 4),
        transferred=(1,),
    )
    assert coverage.missing_episode_numbers == (3,)
    assert coverage.pending_transfer_episode_numbers == (2, 4)
    assert coverage.as_dict()["missing"] == 1


def test_target_coverage_respects_air_dates():
    target = MediaTarget(
        7,
        "tv",
        "测试剧",
        season_number=1,
        episodes=(
            EpisodeTarget(1, 1, "2026-08-01"),
            EpisodeTarget(1, 2, "2026-09-01"),
        ),
    )
    coverage = target_episode_coverage(target, available=(1,), today=date(2026, 8, 28))
    assert coverage.total_episode_numbers == (1, 2)
    assert coverage.aired_episode_numbers == (1,)
    assert coverage.available_episode_numbers == (1,)


def test_media_plan_is_short_lived_protocol_not_persistence():
    plan = build_media_plan(
        entrypoint="discovery",
        provider="quark",
        identity={"tmdb_id": 7, "media_type": "tv", "title": "测试剧", "season_number": 1},
        episode_numbers=(2, 1, 2),
        preferred_share_urls=("https://pan.quark.cn/s/a", "https://pan.quark.cn/s/a"),
        ttl_seconds=300,
    )
    assert plan["version"] == MEDIA_PLAN_VERSION
    assert plan["episode_numbers"] == [1, 2]
    assert plan["preferred_share_urls"] == ["https://pan.quark.cn/s/a"]
    assert plan["expires_at"] > plan["generated_at"]


def test_transfer_entrypoints_consume_the_same_media_plan_protocol():
    plan = MediaPlanInput.model_validate(
        build_media_plan(
            entrypoint="browser_extension",
            provider="p115",
            identity={
                "tmdb_id": 77,
                "media_type": "tv",
                "category": "anime",
                "title": "统一计划",
                "year": "2026",
                "season_number": 2,
            },
            episode_numbers=(3, 1),
            preferred_share_urls=("https://115.com/s/a",),
        )
    )
    payload = _transfer_with_media_plan(
        TransferCreate(tmdb_id=0, media_type="movie", media_plan=plan)
    )
    assert payload.tmdb_id == 77
    assert payload.media_type == "tv"
    assert payload.category == "anime"
    assert payload.season_number == 2
    assert payload.provider == "p115"
    assert payload.episode_numbers == [1, 3]
    assert payload.preferred_share_urls == ["https://115.com/s/a"]
    assert payload.request_source == "browser_extension"
