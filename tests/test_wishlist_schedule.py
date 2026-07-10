import unittest
from datetime import datetime, timezone

from app.domain.media import EpisodeTarget, MediaTarget
from app.services.wishlist_schedule import compute_wishlist_next_check


class WishlistScheduleTests(unittest.TestCase):
    def test_future_episode_uses_tmdb_air_date_at_default_nine(self):
        target = MediaTarget(
            1,
            "variety",
            "Test Show",
            season_number=2,
            episodes=(EpisodeTarget(2, 1, "2026-07-12"),),
        )
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)

        next_check, tmdb_date = compute_wishlist_next_check(target, 9, now, timezone_name="Asia/Shanghai")

        self.assertEqual("2026-07-12T01:00:00+00:00", next_check)
        self.assertEqual("2026-07-12", tmdb_date)

    def test_already_released_item_retries_next_selected_hour(self):
        target = MediaTarget(1, "movie", "Test Movie", release_date="2026-07-01")
        now = datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc)

        next_check, tmdb_date = compute_wishlist_next_check(target, 9, now, timezone_name="Asia/Shanghai")

        self.assertEqual("2026-07-11T01:00:00+00:00", next_check)
        self.assertEqual("2026-07-01", tmdb_date)

    def test_card_selected_hour_changes_schedule(self):
        target = MediaTarget(1, "movie", "Test Movie", release_date="2026-08-01")
        now = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)

        next_check, _ = compute_wishlist_next_check(target, 21, now, timezone_name="Asia/Shanghai")

        self.assertEqual("2026-08-01T13:00:00+00:00", next_check)


if __name__ == "__main__":
    unittest.main()
