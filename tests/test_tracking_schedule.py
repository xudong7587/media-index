import unittest
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.tracking_engine_v2 import (
    _due_episode_numbers,
    _manual_due_episode_numbers,
    _resolution_needs_review,
    _uses_legacy_openlist_auto_sync,
    compute_auto_start_episode,
    compute_next_check,
)


class TrackingScheduleTests(unittest.TestCase):

    def test_native_quark_never_enters_legacy_openlist_auto_sync(self):
        self.assertTrue(_uses_legacy_openlist_auto_sync("qas"))
        self.assertTrue(_uses_legacy_openlist_auto_sync("p115"))
        self.assertFalse(_uses_legacy_openlist_auto_sync("quark"))

    def test_source_not_updated_never_becomes_user_review_work(self):
        self.assertFalse(_resolution_needs_review("source_not_updated"))
        self.assertFalse(_resolution_needs_review("no_resource"))
        self.assertTrue(_resolution_needs_review("needs_review"))

    def test_manual_catch_up_can_select_aired_episode_before_saved_progress(self):
        local_now = datetime(2026, 7, 24, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        episodes = [
            {"episode_number": 3, "status": "pending", "air_date": "2026-07-01"},
            {"episode_number": 8, "status": "saved", "air_date": "2026-07-08"},
            {"episode_number": 9, "status": "pending", "air_date": "2026-07-25"},
        ]

        self.assertEqual({3}, _manual_due_episode_numbers(episodes, {3, 8, 9}, local_now))
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
        target = MediaTarget(
            1,
            "tv",
            "测试剧",
            season_number=1,
            episodes=(EpisodeTarget(1, 1, "2026-07-09"),),
        )
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        result = compute_next_check(target, {1: "pending"}, now, timezone_name="Asia/Shanghai")
        self.assertEqual(now.isoformat(timespec="seconds"), result)

    def test_new_ongoing_task_starts_from_tmdb_next_air_date(self):
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        statuses = {1: "pending", 2: "pending"}
        floor = compute_auto_start_episode(
            self.target(),
            statuses,
            now,
            check_time="10:00",
            timezone_name="Asia/Shanghai",
        )
        result = compute_next_check(
            self.target(),
            statuses,
            now,
            check_time="10:00",
            timezone_name="Asia/Shanghai",
            progress_floor=floor,
        )

        self.assertEqual(1, floor)
        self.assertEqual("2026-07-12T02:00:00+00:00", result)

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

    def test_search_batch_respects_auto_start_episode_floor(self):
        local_now = datetime(2026, 7, 12, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        episodes = [
            {"episode_number": 1, "status": "pending", "air_date": "2026-07-01"},
            {"episode_number": 2, "status": "pending", "air_date": "2026-07-12"},
        ]

        self.assertEqual({2}, _due_episode_numbers(episodes, 1, local_now, time(10, 0)))

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

    def test_manual_run_retries_review_episode_but_scheduler_does_not(self):
        local_now = datetime(2026, 7, 17, 15, 0, tzinfo=timezone.utc)
        episodes = [{"episode_number": 10, "status": "needs_review", "air_date": "2026-07-17"}]
        self.assertEqual(set(), _due_episode_numbers(episodes, 9, local_now, time(14, 0)))
        self.assertEqual({10}, _due_episode_numbers(episodes, 9, local_now, time(14, 0), force=True))


if __name__ == "__main__":
    unittest.main()
