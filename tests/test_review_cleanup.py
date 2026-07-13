import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.review import _supersede_related_reviews
from app.core.config import get_settings
from app.db.database import db, init_db


class ReviewCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(os.environ, {"DB_PATH": str(Path(self.tempdir.name) / "test.db")})
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_success_supersedes_only_other_reviews_for_same_media(self):
        with db() as conn:
            jobs = []
            for tmdb_id in (10, 10, 20):
                cursor = conn.execute(
                    "INSERT INTO transfer_jobs(tmdb_id,media_type,target,status) VALUES(?, 'tv', 'cloud', 'needs_review')",
                    (tmdb_id,),
                )
                jobs.append(int(cursor.lastrowid))
                conn.execute("INSERT INTO candidates(job_id,share_url) VALUES(?, 'https://example.test/share')", (jobs[-1],))

        count = _supersede_related_reviews({"id": jobs[0], "tmdb_id": 10, "media_type": "tv"})

        self.assertEqual(1, count)
        with db() as conn:
            rows = conn.execute(
                "SELECT status,stage FROM transfer_jobs WHERE id IN (?,?) ORDER BY id",
                (jobs[1], jobs[2]),
            ).fetchall()
            decisions = conn.execute(
                "SELECT decision FROM candidates WHERE job_id IN (?,?) ORDER BY job_id",
                (jobs[1], jobs[2]),
            ).fetchall()
        self.assertEqual(("failed", "superseded"), tuple(rows[0]))
        self.assertEqual(("needs_review", "created"), tuple(rows[1]))
        self.assertEqual("superseded", decisions[0][0])
        self.assertEqual("pending", decisions[1][0])


if __name__ == "__main__":
    unittest.main()
