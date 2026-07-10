import unittest
from datetime import datetime, timezone

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.tracking_engine_v2 import compute_next_check


class TrackingScheduleTests(unittest.TestCase):
    def target(self):
        return MediaTarget(
            1,
            "tv",
            "测试剧",
            season_number=1,
            episodes=(
                EpisodeTarget(1, 1, "2026-07-09"),
                EpisodeTarget(1, 2, "2026-07-12"),
            ),
        )

    def test_due_unsaved_episode_runs_now(self):
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        result = compute_next_check(self.target(), {1: "pending", 2: "pending"}, now, timezone_name="Asia/Shanghai")
        self.assertEqual(now.isoformat(timespec="seconds"), result)

    def test_saved_episode_schedules_next_tmdb_air_date(self):
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        result = compute_next_check(
            self.target(),
            {1: "saved", 2: "pending"},
            now,
            check_hour=10,
            timezone_name="Asia/Shanghai",
        )
        self.assertEqual("2026-07-12T02:00:00+00:00", result)

    def test_all_handled_has_no_next_check(self):
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        result = compute_next_check(self.target(), {1: "saved", 2: "triggered"}, now, timezone_name="Asia/Shanghai")
        self.assertEqual("", result)

    def test_invalid_future_air_date_does_not_crash_scheduler(self):
        target = MediaTarget(
            1,
            "tv",
            "Invalid date fixture",
            season_number=1,
            episodes=(EpisodeTarget(1, 1, "not-a-date"),),
        )
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(now.isoformat(timespec="seconds"), compute_next_check(target, {}, now))


if __name__ == "__main__":
    unittest.main()
