from unittest.mock import patch

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.organized_media_followup import reconcile_organized_media_followup


def _target(*, status: str) -> MediaTarget:
    return MediaTarget(
        92026,
        "tv",
        "花开锦绣",
        category="tv",
        series_year="2026",
        season_number=1,
        status=status,
        episodes=(
            EpisodeTarget(1, 1, "2026-08-01"),
            EpisodeTarget(1, 2, "2026-08-02"),
            EpisodeTarget(1, 3, "2099-08-03" if status == "Returning Series" else "2026-08-03"),
        ),
    )


def test_ongoing_complete_aired_coverage_registers_future_tracking_without_backfill():
    with patch(
        "app.services.organized_media_followup.register_tracking_task",
        return_value={"id": 12},
    ) as register:
        result = reconcile_organized_media_followup(
            99,
            provider="quark",
            target=_target(status="Returning Series"),
            final_names=("花开锦绣.2026.S01E01.mp4", "花开锦绣.2026.S01E02.mp4"),
        )

    assert result.state == "tracking"
    assert result.tracking_task_id == 12
    assert register.call_args.args[0].backfill_existing is False


def test_ended_missing_coverage_waits_for_explicit_formal_library_backfill():
    with patch(
        "app.services.organized_media_followup.register_tracking_task",
        return_value={"id": 13},
    ) as register, patch(
        "app.services.organized_media_followup._persist_backfill_confirmation"
    ) as persist:
        result = reconcile_organized_media_followup(
            100,
            provider="quark",
            target=_target(status="Ended"),
            final_names=("花开锦绣.2026.S01E01.mp4", "花开锦绣.2026.S01E03.mp4"),
        )

    assert result.state == "awaiting_backfill_confirmation"
    assert result.missing_episode_numbers == (2,)
    assert result.total_episode_count == 3
    assert result.available_episode_count == 2
    assert register.call_args.args[0].backfill_existing is False
    persist.assert_called_once()
    assert "直接进入正式媒体库" in result.message


def test_ended_complete_coverage_finishes_without_tracking_task():
    with patch("app.services.organized_media_followup.register_tracking_task") as register:
        result = reconcile_organized_media_followup(
            101,
            provider="quark",
            target=_target(status="Ended"),
            final_names=(
                "花开锦绣.2026.S01E01.mp4",
                "花开锦绣.2026.S01E02.mp4",
                "花开锦绣.2026.S01E03.mp4",
            ),
        )

    assert result.state == "complete"
    register.assert_not_called()
