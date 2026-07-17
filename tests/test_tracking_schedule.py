import unittest
from datetime import datetime, time, timezone

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.tracking_engine_v2 import _due_episode_numbers, compute_next_check


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

    def test_same_day_episode_waits_until_selected_release_time(self):
        target = MediaTarget(
            1,
            "tv",
            "测试剧",
            season_number=1,
            episodes=(EpisodeTarget(1, 2, "2026-07-10"),),
        )
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        result = compute_next_check(target, {}, now, check_time="10:30", timezone_name="Asia/Shanghai")
        self.assertEqual("2026-07-10T02:30:00+00:00", result)

    def test_same_day_episode_is_due_after_selected_release_time(self):
        target = MediaTarget(
            1,
            "tv",
            "测试剧",
            season_number=1,
            episodes=(EpisodeTarget(1, 2, "2026-07-10"),),
        )
        now = datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc)
        result = compute_next_check(target, {}, now, check_time="10:30", timezone_name="Asia/Shanghai")
        self.assertEqual(now.isoformat(timespec="seconds"), result)

    def test_all_handled_has_no_next_check(self):
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        result = compute_next_check(self.target(), {1: "saved", 2: "triggered"}, now, timezone_name="Asia/Shanghai")
        self.assertEqual("", result)

    def test_invalid_air_date_only_schedules_metadata_refresh(self):
        target = MediaTarget(
            1,
            "tv",
            "Invalid date fixture",
            season_number=1,
            episodes=(EpisodeTarget(1, 1, "not-a-date"),),
        )
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(
            "2026-07-10T02:00:00+00:00",
            compute_next_check(target, {}, now, check_time="10:00", timezone_name="Asia/Shanghai"),
        )

    def test_search_batch_only_contains_confirmed_new_unsaved_episodes(self):
        local_now = datetime(2026, 7, 10, 10, 30, tzinfo=timezone.utc)
        episodes = [
            {"episode_number": 4, "status": "pending", "air_date": "2026-07-09"},
            {"episode_number": 5, "status": "pending", "air_date": "2026-07-10"},
            {"episode_number": 6, "status": "pending", "air_date": ""},
            {"episode_number": 7, "status": "saved", "air_date": "2026-07-10"},
            {"episode_number": 8, "status": "pending", "air_date": "2026-07-11"},
        ]
        self.assertEqual({5}, _due_episode_numbers(episodes, 4, local_now, time(10, 0)))

    def test_search_batch_waits_until_manual_time(self):
        local_now = datetime(2026, 7, 10, 9, 59, tzinfo=timezone.utc)
        episodes = [{"episode_number": 5, "status": "pending", "air_date": "2026-07-10"}]
        self.assertEqual(set(), _due_episode_numbers(episodes, 4, local_now, time(10, 0)))

    def test_manual_run_bypasses_only_todays_time_not_future_air_dates(self):
        local_now = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)
        episodes = [
            {"episode_number": 8, "status": "pending", "air_date": "2026-07-17"},
            {"episode_number": 9, "status": "pending", "air_date": "2026-07-18"},
            {"episode_number": 10, "status": "pending", "air_date": "2026-07-24"},
            {"episode_number": 11, "status": "pending", "air_date": "2026-07-25"},
        ]
        self.assertEqual(
            {8},
            _due_episode_numbers(episodes, 7, local_now, time(14, 0), force=True),
        )


if __name__ == "__main__":
    unittest.main()
